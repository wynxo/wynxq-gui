"""Inference-only history fitting for long local-model conversations.

The conversation database is the archive.  This module only builds a temporary
view small enough for one Ollama request, then merges the model's newly generated
messages back onto the untouched full history.  It never deletes old turns.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass

from . import context as ctx

COMPACTION_PREFIX = "Wynxq context window note:"
MESSAGE_OVERHEAD = 12
IMAGE_TOKEN_ESTIMATE = 900
MIN_HISTORY_BUDGET = 768


@dataclass(frozen=True)
class Fit:
    messages: list[dict]
    omitted_turns: int = 0
    estimated_tokens: int = 0
    original_count: int = 0

    @property
    def compacted(self) -> bool:
        return self.omitted_turns > 0


def message_tokens(message: dict) -> int:
    """Conservative token estimate for history fitting, independent of Ollama."""
    if not isinstance(message, dict):
        return MESSAGE_OVERHEAD
    total = MESSAGE_OVERHEAD
    total += ctx.estimate_tokens(str(message.get("content", "")))
    total += ctx.estimate_tokens(str(message.get("thinking", "")))
    calls = message.get("tool_calls")
    if calls:
        try:
            total += ctx.estimate_tokens(json.dumps(calls, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            total += 128
    images = message.get("images") or []
    if isinstance(images, list):
        total += len(images) * IMAGE_TOKEN_ESTIMATE
    return total


def _groups(messages: list[dict]) -> tuple[list[dict], list[list[dict]]]:
    """Split into pinned system context and coherent user turns.

    Attachment context messages belong to the user turn that follows them, and
    assistant tool calls/results remain with the user turn that caused them.
    """
    systems: list[dict] = []
    turns: list[list[dict]] = []
    current: list[dict] = []
    has_user = False

    for message in messages:
        item = copy.deepcopy(message)
        role = item.get("role")
        if role == "system":
            systems.append(item)
            continue
        if role == "user" and ctx.is_context_message(item):
            if current and has_user:
                turns.append(current)
                current = []
                has_user = False
            current.append(item)
            continue
        if role == "user":
            if current and has_user:
                turns.append(current)
                current = []
            current.append(item)
            has_user = True
            continue
        current.append(item)
    if current:
        turns.append(current)
    return systems, turns


def _group_tokens(group: list[dict]) -> int:
    return sum(message_tokens(message) for message in group)


def _clip_context_message(message: dict, max_tokens: int) -> dict:
    """Clip only generated attachment-context prose, never the user's request."""
    item = copy.deepcopy(message)
    if not ctx.is_context_message(item) or item.get("images"):
        return item
    content = str(item.get("content", ""))
    if message_tokens(item) <= max_tokens:
        return item
    # Four chars/token is the same intentionally rough estimator used by the UI.
    max_chars = max(320, max_tokens * 4 - 160)
    if len(content) <= max_chars:
        return item
    keep_head = max_chars * 3 // 4
    keep_tail = max_chars - keep_head
    item["content"] = (
        content[:keep_head].rstrip()
        + "\n\n[Wynxq clipped older attached context to fit this model window.]\n\n"
        + content[-keep_tail:].lstrip()
    )
    return item


def _fit_latest_turn(group: list[dict], budget: int) -> list[dict]:
    """Keep the latest request intact, trimming only its bulky attached text."""
    if _group_tokens(group) <= budget:
        return copy.deepcopy(group)
    result = copy.deepcopy(group)
    actual_user_cost = sum(message_tokens(m) for m in result
                           if m.get("role") == "user" and not ctx.is_context_message(m))
    other_cost = sum(message_tokens(m) for m in result
                     if not (m.get("role") == "user" and ctx.is_context_message(m)))
    available = max(256, budget - max(actual_user_cost, other_cost))
    for index, message in enumerate(result):
        if ctx.is_context_message(message):
            result[index] = _clip_context_message(message, available)
    return result


def history_budget(num_ctx: int) -> int:
    """Leave headroom for system prompt, memory, repo guidance and model output."""
    try:
        window = max(2048, int(num_ctx))
    except (TypeError, ValueError):
        window = 16384
    reserve = max(2048, int(window * 0.28))
    return max(MIN_HISTORY_BUDGET, window - reserve)


def fit_history(messages: list[dict], num_ctx: int, budget: int | None = None) -> Fit:
    """Return recent coherent turns for inference without mutating ``messages``."""
    original = copy.deepcopy(list(messages or []))
    limit = history_budget(num_ctx) if budget is None else max(256, int(budget))
    systems, turns = _groups(original)
    pinned_cost = sum(message_tokens(message) for message in systems)
    available = max(256, limit - pinned_cost)
    full_cost = pinned_cost + sum(_group_tokens(turn) for turn in turns)
    if full_cost <= limit:
        return Fit(original, 0, full_cost, len(original))
    if not turns:
        return Fit(systems, 0, pinned_cost, len(original))

    kept_reversed: list[list[dict]] = []
    used = 0
    for reverse_index, turn in enumerate(reversed(turns)):
        cost = _group_tokens(turn)
        if not kept_reversed:
            latest = _fit_latest_turn(turn, available)
            kept_reversed.append(latest)
            used = _group_tokens(latest)
            continue
        if used + cost > available:
            break
        kept_reversed.append(copy.deepcopy(turn))
        used += cost

    kept = list(reversed(kept_reversed))
    omitted = max(0, len(turns) - len(kept))
    if omitted:
        note = {
            "role": "system",
            "content": (
                f"{COMPACTION_PREFIX} {omitted} older conversation turn"
                f"{'s were' if omitted != 1 else ' was'} omitted from this inference request "
                "to fit the model context window. The full conversation remains saved. "
                "Do not claim those turns were deleted; ask the user if an omitted detail is needed."
            ),
        }
        systems = [*systems, note]
    fitted = [*systems, *(message for turn in kept for message in turn)]
    return Fit(fitted, omitted, sum(message_tokens(m) for m in fitted), len(original))


def strip_compaction(messages: list[dict]) -> list[dict]:
    return [message for message in list(messages or [])
            if not (message.get("role") == "system"
                    and str(message.get("content", "")).startswith(COMPACTION_PREFIX))]


def merge_generated(full_history: list[dict], fitted_input: list[dict], engine_result: list[dict]) -> list[dict]:
    """Append only new engine output onto untouched full history.

    ``engine_result`` begins with the fitted inference input.  The prefix may
    contain clipped copies and a compaction marker, so positional length—not
    object equality—is the safe boundary for the newly generated tail.
    """
    prefix = len(list(fitted_input or []))
    result = list(engine_result or [])
    if len(result) < prefix:
        # Fail closed: never replace a complete archive with a suspiciously
        # shorter model result.
        return copy.deepcopy(list(full_history or []))
    generated = copy.deepcopy(result[prefix:])
    generated = strip_compaction(generated)
    return copy.deepcopy(list(full_history or [])) + generated
