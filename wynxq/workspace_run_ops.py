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
from .memory_learning import learnable_memories
from .usage import TokenUsageTracker
from .endpoint_policy import endpoint_scope, validate_workspace_endpoint
from .planning import PLAN_STATES, PlanningAgentEngine, _install_plan_tool
from .workspace_checkpoint import (
    _checkpoint_delta, _restore_workspace_checkpoint, _snapshot_git_workspace,
)

def _begin_workspace_checkpoint(self):
    self._workspace_checkpoint = None
    self.checkpointChanged.emit()
    if self._task_mode != "work" or not self._working_directory:
        return
    before = _snapshot_git_workspace(self._working_directory)
    if before is None:
        return
    self._workspace_checkpoint = {
        "root": str(Path(self._working_directory).resolve()),
        "task": self._task_id,
        "before_all": before,
    }


def _finalize_workspace_checkpoint(self):
    checkpoint = self._workspace_checkpoint
    if not checkpoint or "before_all" not in checkpoint:
        return
    if checkpoint.get("root") != str(Path(self._working_directory).resolve()):
        self._workspace_checkpoint = None
        self.checkpointChanged.emit()
        self.changed.emit()
        return
    after = _snapshot_git_workspace(checkpoint["root"])
    if after is None:
        self._workspace_checkpoint = None
        self.changed.emit()
        return
    before, after = _checkpoint_delta(checkpoint.pop("before_all"), after)
    if not before:
        self._workspace_checkpoint = None
    else:
        checkpoint["before"] = before
        checkpoint["after"] = after
    self.checkpointChanged.emit()
    self.changed.emit()


@Slot()
def undoLastRun(self):
    if self._busy:
        self.toast.emit("Stop the current run before undoing it.")
        return
    if not self.canUndoRun:
        self.toast.emit("There is no safe agent checkpoint to undo.")
        return
    checkpoint = self._workspace_checkpoint
    try:
        count = _restore_workspace_checkpoint(
            checkpoint["root"], checkpoint["before"], checkpoint["after"])
    except (OSError, RuntimeError) as exc:
        self.toast.emit(str(exc))
        return
    viewer_path = self.dock.filePath
    self._workspace_checkpoint = None
    self.checkpointChanged.emit()
    self.dock.refreshFiles()
    self.dock.refreshChanges()
    if viewer_path and not self.dock.fileModified:
        self.dock.openFile(viewer_path)
    self.changed.emit()
    self.toast.emit(f"Undid agent changes in {count} file{'s' if count != 1 else ''}.")


def _finalize_checkpoint_for_run(self, task_id: str, state: dict) -> None:
    checkpoint = state.get("checkpoint")
    if not checkpoint or "before_all" not in checkpoint:
        return
    after = _snapshot_git_workspace(checkpoint["root"])
    if after is None:
        state["checkpoint"] = None
        return
    before, after = _checkpoint_delta(checkpoint.pop("before_all"), after)
    state["checkpoint"] = None if not before else {
        **checkpoint, "before": before, "after": after,
    }
    if state["checkpoint"]:
        self._task_checkpoints[task_id] = state["checkpoint"]
    else:
        self._task_checkpoints.pop(task_id, None)
    if task_id == self._task_id:
        self._workspace_checkpoint = state["checkpoint"]
        self.checkpointChanged.emit()
        self.changed.emit()


def _settle_plan_for_run(self, task_id: str, state: dict, outcome: str) -> None:
    plan = self._normalise_plan(state.get("plan_steps", []))
    changed = False
    for item in plan:
        if item["status"] == "in_progress":
            item["status"] = ("failed" if outcome == "failed" else
                              "pending" if outcome == "cancelled" else "completed")
            changed = True
    if changed:
        state["plan_steps"] = plan
        self.store.set_setting(self._plan_key(task_id), plan)
        if task_id == self._task_id:
            self._set_plan(plan, persist=False)


def _start_run(self, history):
    self._begin_workspace_checkpoint()
    checkpoint = self._workspace_checkpoint
    self._refresh_project_instructions()
    self._context_omitted_turns = 0
    self.contextStateChanged.emit()

    usage = TokenUsageTracker(self.store)
    usage.reset()
    self._usage = usage
    self.usageChanged.emit()

    mode = self._task_mode
    project = self._working_directory
    state = self._launch_run(
        history, self._planning_engine_class(),
        tools_allowed=mode == "work",
        desktop_enabled=mode == "work" and self.desktopEnabled,
        project=project,
        extras={
            "usage": usage,
            "conversation_tokens": self._read_conversation_tokens(self._task_id),
            "context_omitted_turns": 0,
            "plan_steps": [dict(step) for step in self._plan_steps],
            "checkpoint": checkpoint,
            "task_mode": mode,
        },
    )
    self._workspace_checkpoint = state.get("checkpoint")
    self._journal_active_run(self._task_id, True)


def _on_event(self, event, task_id=None):
    task_id = str(task_id or self._task_id or "")
    state = self._run_sessions.get(task_id)
    kind = event.get("type")

    if state and kind == "context_compacted":
        fresh = max(0, int(event.get("omitted_turns", 0) or 0))
        state["context_omitted_turns"] = fresh
        if task_id == self._task_id:
            self._context_omitted_turns = fresh
            self.contextStateChanged.emit()
            self.changed.emit()
        return

    if kind == "tool_start" and event.get("name") == "update_plan":
        fresh = self._normalise_plan(event.get("args", {}).get("steps", []))
        explanation = str(event.get("args", {}).get("explanation", "")).strip()
        status = explanation[:120] or "Planning"
        if state:
            state["plan_steps"] = fresh
            self.store.set_setting(self._plan_key(task_id), fresh)
            state["status"] = status
            if task_id == self._task_id:
                self._set_plan(fresh, persist=False)
                self._status = status
                self.changed.emit()
        else:
            # Direct foreground events (preview/small hosts/tests) still
            # behave exactly like the pre-concurrency controller.
            self._set_plan(fresh)
            self._status = status
            self.changed.emit()
        return
    if kind == "tool_end" and event.get("name") == "update_plan":
        return

    usage_dirty = False
    usage = state.get("usage") if state else self._usage
    if kind in ("token", "thinking"):
        usage_dirty = usage.stream(event.get("text", ""))
        if state and usage.live_rate > 0:
            state["token_rate"] = f"{usage.live_rate:.1f} tok/s"
    elif kind == "metrics":
        usage_dirty = usage.exact_metrics(event)

    Controller._on_event(self, event, task_id)
    if state and task_id == self._task_id:
        self._usage = usage
        if usage.live_rate > 0:
            self._token_rate = f"{usage.live_rate:.1f} tok/s"
    if usage_dirty and (not state or task_id == self._task_id):
        self.usageChanged.emit()


def _run_done(self, history, task_id=None):
    task_id = str(task_id or self._task_id or "")
    state = self._run_sessions.get(task_id)
    if state:
        job = state.get("job")
        stopped = bool(job and job.cancel.is_set())
        outcome = "cancelled" if stopped else (
            "failed" if state.get("error") else "completed")
        usage = state.get("usage")
        if usage and usage.finalize(task_id, state.get("model", "")):
            metrics = usage.metrics
            state["conversation_tokens"] = int(state.get("conversation_tokens", 0))
            state["conversation_tokens"] += max(0, int(metrics.get("tokens", 0) or 0))
            state["conversation_tokens"] += max(0, int(metrics.get("prompt_tokens", 0) or 0))
        cleaned = self._strip_plan_history(history)
        Controller._run_done(self, cleaned, task_id)
        self._journal_active_run(task_id, False)
        self._finalize_checkpoint_for_run(task_id, state)
        self._settle_plan_for_run(task_id, state, outcome)
        if task_id == self._task_id:
            self._usage = usage or self._usage
            self._conversation_tokens = int(state.get(
                "conversation_tokens", self._read_conversation_tokens(task_id)))
            self.usageChanged.emit()
        return
    Controller._run_done(self, self._strip_plan_history(history), task_id)
    self._journal_active_run(task_id, False)


def _run_failed(self, message, task_id=None):
    task_id = str(task_id or self._task_id or "")
    state = self._run_sessions.get(task_id)
    if state:
        usage = state.get("usage")
        if usage:
            usage.finalize(task_id, state.get("model", ""))
        Controller._run_failed(self, message, task_id)
        self._journal_active_run(task_id, False)
        self._finalize_checkpoint_for_run(task_id, state)
        self._settle_plan_for_run(task_id, state, "failed")
        if task_id == self._task_id:
            self._usage = usage or self._usage
            self._conversation_tokens = self._read_conversation_tokens(task_id)
            self.usageChanged.emit()
        return
    Controller._run_failed(self, message, task_id)
    self._journal_active_run(task_id, False)
