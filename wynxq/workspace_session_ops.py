"""WorkspaceController behavior slice.

The public Qt/QML surface remains on WorkspaceController; implementation is
split by responsibility so session, usage/project, task, and run behavior can
evolve independently.
"""
from __future__ import annotations

import copy
from pathlib import Path
import time

from PySide6.QtCore import QTimer, Slot

from . import context as ctx
from . import project_instructions
from .controller import Controller, _blank_metrics
from .usage import TokenUsageTracker
from .endpoint_policy import endpoint_scope, validate_workspace_endpoint
from .planning import PLAN_STATES, PlanningAgentEngine, _install_plan_tool
from .workspace_checkpoint import (
    _checkpoint_delta, _restore_workspace_checkpoint, _snapshot_git_workspace,
)

def _emit_mode(self) -> None:
    self.modeChanged.emit()
    self.changed.emit()


@staticmethod
def _mode_key(task_id: str) -> str:
    return f"task_mode:{task_id}"


@staticmethod
def _plan_key(task_id: str) -> str:
    return f"task_plan:{task_id}"


@classmethod
def _draft_key(cls, task_id: str) -> str:
    return cls.DRAFT_KEY_PREFIX + (str(task_id or "") or "__new__")


def _set_last_task(self, task_id: str) -> None:
    self.store.set_setting(self.LAST_TASK_KEY, str(task_id or ""))


def _persist_current_draft(self) -> None:
    self.store.set_setting(self._draft_key(self._task_id), str(self._draft_text or ""))


def _restore_workspace_session(self) -> None:
    """Restore passive UI state only; never resume a model/tool run."""
    self._recover_interrupted_runs()
    task_id = str(self.store.get_setting(self.LAST_TASK_KEY, "") or "")
    if task_id and self.store.get_conversation(task_id):
        self._recover_interrupted_plan(task_id)
        self.openTask(task_id)
        return
    if task_id:
        self._set_last_task("")
    # Controller starts on a blank task but does not normally restore a
    # draft until a task switch. Do that once for restart continuity.
    self._restore_draft()


def _save_draft(self):
    Controller._save_draft(self, )
    if hasattr(self, "_draft_persist_timer"):
        self._draft_persist_timer.stop()
    self._persist_current_draft()


def _restore_draft(self):
    Controller._restore_draft(self, )
    if self._draft_text:
        return
    saved = self.store.get_setting(self._draft_key(self._task_id), "")
    if isinstance(saved, str) and saved:
        self._draft_text = saved
        self.draftChanged.emit()


@Slot(str)
def setDraft(self, text):
    Controller.setDraft(self, text)
    if hasattr(self, "_draft_persist_timer"):
        self._draft_persist_timer.start()


def _saved_mode(self, task_id: str) -> str:
    mode = str(self.store.get_setting(self._mode_key(task_id), "chat") or "chat")
    # Coding tasks now use the same Work toolset as desktop tasks. Persist
    # this small migration so reopening or duplicating keeps that intent.
    if mode == "codex":
        mode = "work"
        self.store.set_setting(self._mode_key(task_id), mode)
    return mode if mode in self.VALID_TASK_MODES else "chat"


@staticmethod
def _normalise_plan(steps) -> list[dict]:
    result, seen = [], set()
    for index, item in enumerate(list(steps or [])[:8]):
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title", "")).split())[:180]
        if not title:
            continue
        identifier = "".join(ch for ch in str(item.get("id", "")).strip()[:48]
                             if ch.isalnum() or ch in "-_.") or f"step-{index + 1}"
        if identifier in seen:
            identifier = f"{identifier}-{index + 1}"
        seen.add(identifier)
        status = str(item.get("status", "pending"))
        if status not in PLAN_STATES:
            status = "pending"
        result.append({"id": identifier, "title": title, "status": status})
    return result


def _saved_plan(self, task_id: str) -> list[dict]:
    """Read persisted plan state without pretending a normal read is a restart."""
    return self._normalise_plan(self.store.get_setting(self._plan_key(task_id), []))


def _recover_interrupted_plan(self, task_id: str) -> None:
    """On process startup only, stale running steps become pending.

    A restart cannot prove an in-progress action completed, but opening,
    duplicating or inspecting a task during the same process must preserve
    its live status exactly as stored.
    """
    plan = self._saved_plan(task_id)
    interrupted = False
    for step in plan:
        if step["status"] == "in_progress":
            step["status"] = "pending"
            interrupted = True
    if interrupted:
        self.store.set_setting(self._plan_key(task_id), plan)


def _journal_active_run(self, task_id: str, active: bool) -> None:
    """Persist the IDs of runs that would need recovery after a hard crash."""
    task_id = str(task_id or "")
    if not task_id:
        return
    raw = self.store.get_setting(self.ACTIVE_RUNS_KEY, [])
    current = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        value = str(item or "")
        if value and value not in seen:
            current.append(value)
            seen.add(value)
    if active and task_id not in seen:
        current.append(task_id)
    elif not active:
        current = [value for value in current if value != task_id]
    self.store.set_setting(self.ACTIVE_RUNS_KEY, current[:64])


def _recover_interrupted_runs(self) -> None:
    """Repair every run left journaled by an unclean process exit.

    Tool execution is never resumed automatically. We only move persisted plan
    steps from in_progress back to pending, then clear the journal.
    """
    raw = self.store.get_setting(self.ACTIVE_RUNS_KEY, [])
    task_ids = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        task_id = str(item or "")
        if task_id and task_id not in seen:
            task_ids.append(task_id)
            seen.add(task_id)
    for task_id in task_ids:
        if self.store.get_conversation(task_id):
            self._recover_interrupted_plan(task_id)
    if task_ids or raw:
        self.store.set_setting(self.ACTIVE_RUNS_KEY, [])


def _persist_task_mode(self, task_id: str | None = None) -> None:
    target = str(task_id or self._task_id or "")
    if target:
        self.store.set_setting(self._mode_key(target), self._task_mode)


def _persist_plan(self, task_id: str | None = None) -> None:
    target = str(task_id or self._task_id or "")
    if target:
        self.store.set_setting(self._plan_key(target), self._plan_steps)


def _set_plan(self, steps, *, persist: bool = True) -> None:
    fresh = self._normalise_plan(steps)
    if fresh == self._plan_steps:
        return
    self._plan_steps = fresh
    if persist:
        self._persist_plan()
    self.planChanged.emit()


def _settle_plan(self, outcome: str) -> None:
    if not self._plan_steps:
        return
    changed = False
    fresh = []
    for step in self._plan_steps:
        item = dict(step)
        if item["status"] == "in_progress":
            item["status"] = ("failed" if outcome == "failed" else
                              "pending" if outcome == "cancelled" else "completed")
            changed = True
        fresh.append(item)
    if changed:
        self._set_plan(fresh)


@staticmethod
def _strip_plan_history(history) -> list[dict]:
    """The plan is workspace state, not conversation/activity evidence."""
    cleaned = []
    for message in list(history or []):
        if message.get("role") == "tool" and message.get("tool_name") == "update_plan":
            continue
        if message.get("role") == "assistant" and message.get("tool_calls"):
            item = copy.deepcopy(message)
            calls = [call for call in item.get("tool_calls", [])
                     if call.get("function", {}).get("name") != "update_plan"]
            if calls:
                item["tool_calls"] = calls
            else:
                item.pop("tool_calls", None)
            if item.get("content") or item.get("thinking") or calls:
                cleaned.append(item)
            continue
        cleaned.append(copy.deepcopy(message))
    return cleaned


def _refresh_project_instructions(self) -> None:
    fresh = project_instructions.summary(self._working_directory)
    if fresh != self._project_instructions_summary:
        self._project_instructions_summary = fresh
        self.contextStateChanged.emit()
        self.changed.emit()
