"""Live token animation state plus exact persisted usage accounting.

Ollama reports exact token counts at the end of each model pass. The UI wants
feedback while text is still streaming, so the tracker estimates only the
currently-open pass from visible text, then reconciles to Ollama's exact count
as soon as metrics arrive. Only exact metrics are ever written to history.
"""
from __future__ import annotations

import copy
import time

from . import context as ctx


def _blank_metrics() -> dict:
    return {
        "tokens": 0,
        "prompt_tokens": 0,
        "cached_prompt_tokens": 0,
        "load_ms": 0.0,
        "total_ms": 0.0,
        "tokens_per_second": 0.0,
    }


def _blank_bucket() -> dict:
    return {
        "tokens": 0,
        "outputTokens": 0,
        "promptTokens": 0,
        "cachedTokens": 0,
        "runs": 0,
        "averageRate": 0.0,
    }


def _blank_summary() -> dict:
    return {name: _blank_bucket() for name in ("today", "week", "month", "allTime")}


class TokenUsageTracker:
    """One controller's live counter backed by a Store usage ledger.

    Small controller/unit-test stores predate the usage ledger. Live accounting
    is still useful with those stores, so persistence is feature-detected rather
    than made a hard requirement of the controller's storage interface.
    """

    def __init__(self, store, clock=None):
        self.store = store
        self._clock = clock or time.monotonic
        self._summary = _blank_summary()
        self.refresh()
        self.reset()

    def reset(self) -> None:
        self.live_output_tokens = 0
        self.live_rate = 0.0
        self._live_rate_exact = False
        self._segment_text = ""
        self._segment_started: float | None = None
        self._exact_base = 0
        self._weighted_rate = 0.0
        self._metrics = _blank_metrics()
        self._recorded = False

    @property
    def metrics(self) -> dict:
        return dict(self._metrics)

    @property
    def live_rate_exact(self) -> bool:
        return bool(self._live_rate_exact)

    @property
    def summary(self) -> dict:
        return copy.deepcopy(self._summary)

    def refresh(self) -> bool:
        """Refresh day/week/month buckets when a long-running UI asks for them."""
        summary = getattr(self.store, "token_usage_summary", None)
        fresh = summary() if callable(summary) else _blank_summary()
        changed = fresh != self._summary
        self._summary = fresh
        return changed

    def stream(self, text: str) -> bool:
        """Advance the provisional count from text that became visible.

        ``estimate_tokens`` is deliberately kept out of persistence. Chunk
        boundaries are transport details and can split a model token; measuring
        the full open segment avoids accumulating a rounding error per chunk.
        """
        text = str(text or "")
        if not text:
            return False
        now = float(self._clock())
        before_tokens = self.live_output_tokens
        before_rate = self.live_rate
        if self._segment_started is None:
            self._segment_started = now
            # A new model pass must not display the previous pass's exact
            # throughput while the next pass has not produced a measurement.
            self.live_rate = 0.0
            self._live_rate_exact = False
        self._segment_text += text
        estimate = max(0, int(ctx.estimate_tokens(self._segment_text)))
        self.live_output_tokens = self._exact_base + estimate
        elapsed = max(0.0, now - self._segment_started)
        if estimate and elapsed >= 0.12:
            self.live_rate = estimate / elapsed
        return (before_tokens != self.live_output_tokens
                or abs(before_rate - self.live_rate) >= 0.05)

    def exact_metrics(self, event: dict) -> bool:
        """Reconcile the current pass to Ollama's exact final metrics."""
        output = max(0, int(event.get("tokens", 0) or 0))
        prompt = max(0, int(event.get("prompt_tokens", 0) or 0))
        cached = max(0, int(event.get("cached_prompt_tokens", 0) or 0))
        load_ms = max(0.0, float(event.get("load_ms", 0.0) or 0.0))
        total_ms = max(0.0, float(event.get("total_ms", 0.0) or 0.0))
        raw_rate = event.get("tokens_per_second", 0.0)
        rate = max(0.0, float(raw_rate)) if isinstance(raw_rate, (int, float)) else 0.0

        self._metrics["tokens"] += output
        self._metrics["prompt_tokens"] += prompt
        self._metrics["cached_prompt_tokens"] += cached
        self._metrics["load_ms"] += load_ms
        self._metrics["total_ms"] += total_ms
        if output and rate:
            self._weighted_rate += rate * output
        total_output = int(self._metrics["tokens"])
        self._metrics["tokens_per_second"] = (
            self._weighted_rate / total_output if total_output else rate
        )

        before_tokens = self.live_output_tokens
        before_rate = self.live_rate
        self._exact_base = total_output
        self.live_output_tokens = total_output
        self.live_rate = rate or self._metrics["tokens_per_second"]
        self._live_rate_exact = bool(self.live_rate)
        self._segment_text = ""
        self._segment_started = None
        return (before_tokens != self.live_output_tokens
                or abs(before_rate - self.live_rate) >= 0.05)

    def finalize(self, conversation_id: str, model: str,
                 created_at: float | None = None) -> bool:
        """Write this run once, then refresh every period shown by the UI."""
        if self._recorded:
            return False
        self._recorded = True
        record = getattr(self.store, "record_token_usage", None)
        if not callable(record):
            return False
        stored = bool(record(conversation_id, model, self._metrics,
                             created_at=created_at))
        if stored:
            self.refresh()
        return stored
