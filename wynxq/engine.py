"""Bounded Ollama agent/tool loop, independent of Qt.

Events passed to emit: token/thinking/status/error (text), tool_start
(name,args,risk,summary,confirming), tool_end (name,result,ms,declined),
metrics (tokens,tokens_per_second), session (permission_mode,visual,max_steps),
message_end (message), and cancelled. run returns the complete history;
its runtime system prompt is never added to that returned history.

Transport, prompt policy, transcript shaping, and concrete tool execution live
in focused pure-Python modules. This file owns orchestration and the action
budget only.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Callable

from .commands import run_command
from .agent_tools import (
    ASK, AUTO, BROWSER_TOOLS, FULL, LEGACY_MODES, LOW_RISK, MANUAL,
    MEMORY_TOOLS, PERMISSION_DETAILS, PERMISSION_LABELS, PERMISSION_MODES,
    SAFE, SENSITIVE, TOOLS, _AUTO_OBSERVE, _COORD, _DESTRUCTIVE,
    _DESTRUCTIVE_PATTERNS, _NONVISUAL, _SCHEMAS, _tool, _validate,
    action_risk, action_summary, command_risk, needs_confirmation,
    normalise_mode, validate_tool_call,
)
from .agent_prompt import _CHAT_SYSTEM, _SYSTEM, build_system_prompt
from .engine_support import (
    _ThinkingTextRouter, _normalise_assistant_channels, append_screen,
    fresh_history, latest_user_query, model_history,
)
from .memory import GLOBAL as MEMORY_GLOBAL
from .ollama import (
    DEFAULT_ENDPOINT, DEFAULT_MODEL, Cancelled, OllamaClient, OllamaError,
    _interruptible, _stopped, validate_endpoint,
)
from .tool_execution import ToolExecutor


LOG = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, client: OllamaClient, desktop, memory=None,
                 browser_open: Callable[[str], dict] | None = None):
        self.client, self.desktop, self.memory = client, desktop, memory
        self.browser_open = browser_open
        # Optional read-only cross-chat recall provider, installed by the GUI
        # controller. It runs on the worker thread inside run(), never on Qt.
        self.history_recall = None

    def run(self, messages: list[dict], model: str, desktop_enabled: bool, cancel,
            emit: Callable[[dict], None], think: bool = False, max_steps: int = 20,
            num_ctx: int = 16384, temperature: float = 0.7, keep_alive: str = "5m",
            permission_mode: str | Callable[[], str] = SAFE, project: str = "",
            confirm: Callable[[str, dict, str], bool] | None = None,
            tools_allowed: bool = True) -> list[dict]:
        """Answer the conversation, running tools until the model stops asking.

        tools_allowed is Chat mode's switch. With it off the model gets no
        shell, desktop, project, planning, or memory-writing tools at all.
        Unsolicited tool calls are rejected before any action is dispatched.
        A callable permission_mode is re-read before each action so a user
        can tighten or relax the active run without restarting it.
        """
        history = fresh_history(messages)
        permission_source = permission_mode

        def current_permission_mode() -> str:
            try:
                value = permission_source() if callable(permission_source) else permission_source
            except Exception:
                LOG.exception("Permission mode provider failed; falling back to Safe")
                value = SAFE
            return normalise_mode(value)

        initial_permission_mode = current_permission_mode()
        max_steps = max(1, min(int(max_steps), 100))
        num_ctx = max(2048, min(int(num_ctx), 131072))
        temperature = max(0.0, min(float(temperature), 2.0))
        keep_alive = str(keep_alive).strip()[:32] or "5m"
        active_message: dict | None = None

        def event(kind: str, **fields):
            emit({"type": kind, **fields})

        pending_screens = []

        def remember_screen(result: dict) -> None:
            pending_screens.append(result)

        try:
            if _stopped(cancel):
                raise Cancelled("Stopped")
            event("status", text="Checking model capabilities…")
            capabilities = set(_interruptible(lambda: self.client.capabilities(model), cancel))
            if _stopped(cancel):
                raise Cancelled("Stopped")

            status = self.desktop.status() if self.desktop else {}
            model_has_tools = "tools" in capabilities
            memory_tools = (
                MEMORY_TOOLS
                if tools_allowed and self.memory is not None and model_has_tools
                else set()
            )
            tools_enabled = tools_allowed and self.desktop is not None and model_has_tools
            visual = (
                tools_enabled and desktop_enabled and status.get("connected")
                and "vision" in capabilities
            )
            browser_tools = BROWSER_TOOLS if self.browser_open is not None else set()
            available_schemas = set(_SCHEMAS) - (BROWSER_TOOLS - browser_tools)
            nonvisual = _NONVISUAL | browser_tools
            # Tool availability is an execution boundary, including memory writes.
            # A model cannot opt itself into Work by emitting a tool call.
            allowed = (
                ((available_schemas if visual else nonvisual.copy()) - MEMORY_TOOLS
                 if tools_enabled else set())
                | memory_tools
            )

            query = latest_user_query(history)
            remembered = ""
            if self.memory is not None:
                remembered = self.memory.prompt(project, query)
            recalled = ""
            if callable(self.history_recall):
                try:
                    recalled = str(self.history_recall(query) or "")
                except Exception:
                    LOG.exception("Past-chat recall failed; continuing without it")

            system = build_system_prompt(
                tools_allowed=tools_allowed,
                tools_enabled=tools_enabled,
                visual=visual,
                permission_mode=initial_permission_mode,
                browser_available=self.browser_open is not None,
                memory_tools_enabled=bool(memory_tools),
                project=project,
                remembered=remembered,
                recalled=recalled,
            )

            if not tools_allowed:
                event("status", text="Chat task: answering only, with no commands or desktop actions.")
            elif desktop_enabled and not tools_enabled:
                reason = (
                    "This model does not advertise tool calling."
                    if not model_has_tools else "Desktop permission is not connected."
                )
                event("status", text=reason + " Chat remains available.")
            elif tools_enabled and not visual:
                event(
                    "status",
                    text=(
                        "Local commands and app launching are ready. "
                        "Screen control requires a connected desktop and a vision model."
                    ),
                )
            elif visual:
                event("status", text="Local tools are ready. Screen control is available on demand.")

            if tools_enabled:
                event(
                    "session",
                    permission_mode=initial_permission_mode,
                    visual=visual,
                    max_steps=max_steps,
                )

            executor = ToolExecutor(
                desktop=self.desktop,
                memory=self.memory,
                browser_open=self.browser_open,
                project=project,
                cancel=cancel,
                emit=emit,
                permission_mode=current_permission_mode,
                confirm=confirm,
                visual=visual,
                append_screen=remember_screen,
            )

            steps = 0
            for _turn in range(max_steps + 1):
                if _stopped(cancel):
                    raise Cancelled("Stopped")
                event(
                    "status",
                    text="Thinking…" if think and "thinking" in capabilities else "Working…",
                )

                payload = {
                    "model": model,
                    "messages": [{"role": "system", "content": system}]
                                + model_history(history, capabilities),
                    "options": {"num_ctx": num_ctx, "temperature": temperature},
                    "keep_alive": keep_alive,
                }
                if "thinking" in capabilities:
                    payload["think"] = bool(think)
                if allowed:
                    payload["tools"] = [
                        tool for tool in TOOLS
                        if tool["function"]["name"] in allowed
                    ]

                active_message = {"role": "assistant", "content": ""}
                tagged_thinking = _ThinkingTextRouter()

                def append_assistant_text(kind: str, text: str) -> None:
                    text = str(text or "")
                    if not text:
                        return
                    field = "thinking" if kind == "thinking" else "content"
                    active_message[field] = active_message.get(field, "") + text
                    event(kind, text=text)

                calls = []
                complete = False
                for chunk in self.client.stream_chat(payload, cancel):
                    if _stopped(cancel):
                        raise Cancelled("Stopped")
                    message = chunk.get("message", {})
                    if message.get("thinking"):
                        append_assistant_text("thinking", message["thinking"])
                    if message.get("content"):
                        for channel, text in tagged_thinking.feed(message["content"]):
                            append_assistant_text(channel, text)
                    new_calls = message.get("tool_calls") or []
                    if not isinstance(new_calls, list):
                        raise OllamaError("Model returned malformed tool calls")
                    if new_calls and not allowed:
                        raise OllamaError(
                            "This model requested a tool, but tools are disabled in this task. "
                            "Start a Work task for actions, or retry with a conversational request."
                        )
                    calls.extend(new_calls)
                    if len(calls) > 32:
                        raise OllamaError("Model requested too many actions in one response")
                    if chunk.get("done"):
                        complete = True
                        duration = chunk.get("eval_duration") or 0
                        tokens = chunk.get("eval_count") or 0
                        event(
                            "metrics",
                            tokens=tokens,
                            prompt_tokens=chunk.get("prompt_eval_count") or 0,
                            cached_prompt_tokens=chunk.get("prompt_eval_cached_count") or 0,
                            load_ms=round((chunk.get("load_duration") or 0) / 1e6, 1),
                            total_ms=round((chunk.get("total_duration") or 0) / 1e6, 1),
                            tokens_per_second=round(tokens * 1e9 / duration, 1)
                            if duration else 0,
                        )

                for channel, text in tagged_thinking.flush():
                    append_assistant_text(channel, text)
                if not complete:
                    raise OllamaError(
                        "Ollama's response ended before completion. Please retry."
                    )

                active_message = _normalise_assistant_channels(active_message)
                if calls:
                    active_message["tool_calls"] = calls
                history.append(active_message)
                event("message_end", message=copy.deepcopy(active_message))
                active_message = None
                if not calls:
                    return history

                # Coordinates must be based on an observation the model has actually
                # received, not one captured halfway through this batch of calls.
                saw_screen = any(m.get("images") and str(m.get("content", "")).startswith(
                    "Current desktop screenshot (") for m in payload["messages"])
                screen_changed = False
                visual_input = available_schemas - _NONVISUAL - {"screenshot"}

                def report_blocked(name: str, args: dict, result: dict) -> dict:
                    """Emit the same activity contract as an executable tool call."""
                    event(
                        "tool_start",
                        name=name,
                        args=args,
                        risk=action_risk(name, args),
                        summary=action_summary(name, args),
                        confirming=False,
                        blocked=True,
                    )
                    event("tool_end", name=name, ms=0, result=result, blocked=True)
                    return result

                for index, call in enumerate(calls):
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    name = function.get("name", "")
                    args = function.get("arguments", {})
                    if _stopped(cancel):
                        for pending in calls[index:]:
                            pending_name = (
                                pending.get("function", {}).get("name", "")
                                if isinstance(pending, dict) else ""
                            )
                            history.append({
                                "role": "tool",
                                "tool_name": pending_name,
                                "content": json.dumps({
                                    "ok": False,
                                    "error": "Cancelled before execution",
                                }),
                            })
                        raise Cancelled("Stopped")

                    if visual and name in visual_input and (not saw_screen or screen_changed):
                        result = {
                            "ok": False,
                            "error": "Visual action deferred: read a fresh screenshot in a new response "
                                     "before choosing coordinates or keyboard input. Call screenshot if needed.",
                        }
                        result = report_blocked(name, args, result)
                    elif steps >= max_steps:
                        result = {
                            "ok": False,
                            "error": "Action limit reached. Ask the user to continue.",
                        }
                        result = report_blocked(name, args, result)
                    else:
                        steps += 1
                        try:
                            result = executor.execute(name, args, allowed)
                        except Cancelled:
                            history.append({
                                "role": "tool",
                                "tool_name": name,
                                "content": json.dumps({
                                    "ok": False,
                                    "error": "Stopped during execution; the action may be partial",
                                }),
                            })
                            for pending in calls[index + 1:]:
                                pending_name = (
                                    pending.get("function", {}).get("name", "")
                                    if isinstance(pending, dict) else ""
                                )
                                history.append({
                                    "role": "tool",
                                    "tool_name": pending_name,
                                    "content": json.dumps({
                                        "ok": False,
                                        "error": "Cancelled before execution",
                                    }),
                                })
                            raise

                    if name == "screenshot" or name in _AUTO_OBSERVE:
                        screen_changed = True
                    if result.get("screen_observation_error") or (
                            name == "screenshot" and (not result.get("ok", True) or not result.get("image"))):
                        # Do not let a failed new capture leave old coordinates usable.
                        history[:] = fresh_history(history)
                        pending_screens.clear()
                    summary = {
                        key: value for key, value in result.items()
                        if key != "image"
                    }
                    history.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(summary, ensure_ascii=False),
                    })
                    if name == "screenshot":
                        remember_screen(result)

                for observation in pending_screens:
                    append_screen(history, observation)
                pending_screens.clear()

                if steps >= max_steps:
                    text = (
                        f"Stopped at the {max_steps}-action limit. Review the actions above, "
                        "then send a follow-up to continue."
                    )
                    history.append({"role": "assistant", "content": text})
                    event("token", text=text)
                    event("message_end", message=history[-1])
                    event("status", text="Action limit reached")
                    return history
            return history
        except Cancelled:
            if active_message and (
                active_message.get("content") or active_message.get("thinking")
            ):
                history.append(active_message)
                event("message_end", message=copy.deepcopy(active_message))
            event("cancelled")
            event("status", text="Stopped")
            return history
        except Exception as exc:
            LOG.warning("Agent request failed: %s", exc)
            if active_message and (
                active_message.get("content") or active_message.get("thinking")
            ):
                history.append(active_message)
                event("message_end", message=copy.deepcopy(active_message))
            event("error", text=str(exc))
            return history
