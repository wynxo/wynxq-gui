"""The run timeline behind the Activity panel.

The inline activity in the conversation is a summary: one line per action, no
history once the task is reopened. The Activity panel is the full record of the
current session — every step, its state, its timing, its output — grouped by the
turn that produced it.

States are fixed and total: queued, running, waiting, done, failed, cancelled.
Anything the engine reports that is not one of those is normalised here rather
than leaking an unknown state into the UI.
"""
from __future__ import annotations

import time

QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED = (
    "queued", "running", "waiting", "done", "failed", "cancelled")

STATES = (QUEUED, RUNNING, WAITING, DONE, FAILED, CANCELLED)
TERMINAL_STATES = frozenset({DONE, FAILED, CANCELLED})

# What the engine calls a state, and what the panel calls it.
ALIASES = {
    "declined": CANCELLED, "stopped": CANCELLED, "skipped": CANCELLED,
    "error": FAILED, "ok": DONE, "complete": DONE, "completed": DONE,
    "pending": QUEUED, "active": RUNNING,
}

MAX_EVENTS = 600
MAX_OUTPUT = 4000


def normalise_state(value) -> str:
    state = str(value or "").strip().lower()
    state = ALIASES.get(state, state)
    return state if state in STATES else QUEUED


def format_duration(ms) -> str:
    try:
        value = float(ms or 0)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value < 1000:
        return f"{round(value)}ms"
    if value < 60000:
        return f"{value / 1000:.1f}s"
    minutes, seconds = divmod(int(value / 1000), 60)
    return f"{minutes}m {seconds:02d}s"


class ActivityLog:
    """An ordered list of events, grouped into turns.

    Append-only apart from `update_last`, which the engine uses to settle a step
    it already announced. Bounded, so a 400-step run does not grow without end.
    """

    def __init__(self, max_events: int = MAX_EVENTS):
        self.max_events = max_events
        self.events: list[dict] = []
        self._turn = 0
        self._sequence = 0
        self.revision = 0

    # ---------------------------------------------------------------- write
    def begin_turn(self, title: str = "") -> int:
        self._turn += 1
        self.append({
            "kind": "turn", "label": str(title or f"Turn {self._turn}"),
            "icon": "bolt", "state": RUNNING, "summary": "", "output": "",
            "detail": "",
        })
        return self._turn

    def append(self, event: dict) -> dict:
        self._sequence += 1
        entry = {
            "id": self._sequence,
            "turn": self._turn,
            "kind": str(event.get("kind", "step")),
            "name": str(event.get("name", "")),
            "icon": str(event.get("icon") or "bolt"),
            "label": str(event.get("label", "")),
            "summary": str(event.get("summary", "")),
            "detail": str(event.get("detail", ""))[:MAX_OUTPUT],
            "output": str(event.get("output", ""))[:MAX_OUTPUT],
            "state": normalise_state(event.get("state", QUEUED)),
            "ms": float(event.get("ms", 0) or 0),
            "risk": str(event.get("risk", "normal")),
            "at": time.time(),
        }
        entry["durationLabel"] = format_duration(entry["ms"])
        self.events.append(entry)
        while len(self.events) > self.max_events:
            self.events.pop(0)
        self.revision += 1
        return entry

    def update_last(self, **fields) -> dict | None:
        """Settle the most recent step event."""
        for entry in reversed(self.events):
            if entry["kind"] != "step":
                continue
            if "state" in fields:
                entry["state"] = normalise_state(fields["state"])
            if "ms" in fields:
                entry["ms"] = float(fields["ms"] or 0)
                entry["durationLabel"] = format_duration(entry["ms"])
            for key in ("output", "detail", "summary", "label", "icon"):
                if key in fields:
                    entry[key] = str(fields[key] or "")[:MAX_OUTPUT]
            self.revision += 1
            return entry
        return None

    def settle_turn(self, state: str = DONE) -> None:
        """Close the open turn header and anything still shown as running."""
        resolved = normalise_state(state)
        for entry in reversed(self.events):
            if entry["kind"] == "turn" and entry["state"] == RUNNING:
                entry["state"] = resolved
                break
        for entry in self.events:
            if entry["state"] in (RUNNING, WAITING, QUEUED) and entry["kind"] == "step":
                entry["state"] = CANCELLED if resolved == CANCELLED else resolved
        self.revision += 1

    def clear(self) -> None:
        self.events.clear()
        self._turn = 0
        self._sequence = 0
        self.revision += 1

    # ----------------------------------------------------------------- read
    @property
    def running(self) -> bool:
        return any(entry["state"] in (RUNNING, WAITING) for entry in self.events)

    def counts(self) -> dict:
        totals = {state: 0 for state in STATES}
        elapsed = 0.0
        for entry in self.events:
            if entry["kind"] != "step":
                continue
            totals[entry["state"]] += 1
            elapsed += entry["ms"]
        totals["total"] = sum(totals[state] for state in STATES)
        totals["elapsed"] = elapsed
        totals["elapsedLabel"] = format_duration(elapsed)
        return totals

    def rows(self) -> list[dict]:
        """Newest turn last, exactly as the panel scrolls."""
        return [dict(entry) for entry in self.events]

    def summary(self) -> str:
        counts = self.counts()
        if not counts["total"]:
            return ""
        parts = [f"{counts['total']} step" + ("" if counts["total"] == 1 else "s")]
        if counts[FAILED]:
            parts.append(f"{counts[FAILED]} failed")
        if counts[CANCELLED]:
            parts.append(f"{counts[CANCELLED]} cancelled")
        if counts["elapsedLabel"]:
            parts.append(counts["elapsedLabel"])
        return " · ".join(parts)
