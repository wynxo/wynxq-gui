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

@Slot(str, result=bool)
def setTaskMode(self, mode):
    """Choose the mode for a blank task exactly once."""
    mode = str(mode or "").strip().lower()
    if mode not in self.VALID_TASK_MODES or self._busy or self._connecting:
        return False
    if self._task_id or self._task_mode_locked:
        return mode == self._task_mode
    self._task_mode = mode
    self._task_mode_locked = True
    self._emit_mode()
    return True


@Slot(str)
def newTaskMode(self, mode):
    mode = str(mode or "").strip().lower()
    if mode not in self.VALID_TASK_MODES:
        return
    Controller.newTask(self, )
    self._reset_usage_context()
    self._set_last_task("")
    self._set_plan([], persist=False)
    if self._task_id or self._busy:
        return
    self._task_mode = "chat"
    self._task_mode_locked = False
    if mode == "chat":
        self._emit_mode()
    else:
        self.setTaskMode(mode)


@Slot()
def newTask(self):
    Controller.newTask(self, )
    self._reset_usage_context()
    self._set_last_task("")
    self._set_plan([], persist=False)
    if not self._task_id:
        self._task_mode = "chat"
        self._task_mode_locked = False
        self._emit_mode()


def _grouped_tasks(self) -> list[dict]:
    """The sidebar's groups, with each task's product on it."""
    groups = Controller._grouped_tasks(self, )
    for group in groups:
        group["items"] = [{**task, "mode": self._saved_mode(str(task.get("id", "")))}
                          for task in group["items"]]
    return groups


@Slot(str)
def openTask(self, task_id):
    Controller.openTask(self, task_id)
    if self._task_id != task_id:
        return
    self._set_last_task(task_id)
    self._task_mode = self._saved_mode(task_id)
    self._task_mode_locked = True
    state = self._active_session()
    if state and state.get("usage") is not None:
        self._usage = state["usage"]
        self._conversation_tokens = int(state.get(
            "conversation_tokens", self._read_conversation_tokens(task_id)))
        self._context_omitted_turns = int(state.get("context_omitted_turns", 0) or 0)
        self._set_plan(state.get("plan_steps", self._saved_plan(task_id)), persist=False)
    else:
        self._reset_usage_context()
        self._context_omitted_turns = 0
        self._set_plan(self._saved_plan(task_id), persist=False)
    self._workspace_checkpoint = self._task_checkpoints.get(task_id)
    if state and state.get("checkpoint"):
        self._workspace_checkpoint = state.get("checkpoint")
    self.usageChanged.emit()
    self.contextStateChanged.emit()
    self.checkpointChanged.emit()
    self._emit_mode()


def _learn_user_memory(self, text: str) -> int:
    """Quietly persist high-confidence durable facts from an accepted message.

    This path is deliberately independent of model tool calling. A small or
    tool-less local model should still remember a preferred name or a stable
    repo convention. The Markdown memory file remains the source of truth,
    and its normal dedupe/size/privacy rules still apply.
    """
    if not self._memory_enabled or self._task_mode != "work":
        return 0
    stored = 0
    identity_prefixes = ("User prefers to be called ", "User's preferred name is ")
    for candidate in learnable_memories(text, self._working_directory):
        try:
            note = candidate["note"]
            # A preferred name is a single-valued identity slot, not a list
            # of likes. Replace an older name instead of injecting two
            # contradictory names into every future task.
            if candidate["scope"] == "global" and note.startswith(identity_prefixes):
                existing = self.memory.notes("global")
                same = any(item.casefold() == note.casefold() for item in existing)
                if not same:
                    self.memory.forget("User prefers to be called", "global")
                    self.memory.forget("User's preferred name is", "global")
            result = self.memory.remember(
                note, candidate["scope"], self._working_directory)
        except (OSError, ValueError):
            continue
        stored += int(bool(result.get("stored")))
    if stored:
        self.memoryChanged.emit()
    return stored


@Slot(str)
def send(self, text):
    previous_task = self._task_id
    before_messages = len(self._history)
    # Learn only messages the base controller would actually accept. Never
    # turn an offline draft, an empty submit or a click while busy into
    # durable profile data. Learning happens before the run starts so the
    # same turn can benefit from the freshly updated memory if useful.
    accepted_text = str(text).strip()
    accepted = bool(accepted_text and not self._busy and not self._connecting and self._online)
    if accepted:
        self._learn_user_memory(accepted_text)

    was_new = not self._task_id
    if was_new and not self._task_mode_locked:
        self._task_mode = "chat"
        self._task_mode_locked = True
        self._emit_mode()
    Controller.send(self, text)
    sent = len(self._history) > before_messages
    if sent:
        self._draft_persist_timer.stop()
        # A newly created task changes the draft key mid-send, so clear both
        # the source slot and the final task slot. The submitted text now
        # belongs to conversation history, not the composer.
        self.store.set_setting(self._draft_key(previous_task), "")
        self.store.set_setting(self._draft_key(self._task_id), "")
        self._set_last_task(self._task_id)
    if was_new and self._task_id:
        self._persist_task_mode()
        self._persist_plan()
        self.modeChanged.emit()


@Slot(str)
def deleteTask(self, task_id):
    task_id = str(task_id or "")
    if task_id:
        self.store.set_setting(self._draft_key(task_id), "")
        if str(self.store.get_setting(self.LAST_TASK_KEY, "") or "") == task_id:
            self._set_last_task("")
    Controller.deleteTask(self, task_id)


@Slot()
def clearTask(self):
    task_id = self._task_id
    Controller.clearTask(self, )
    if task_id and self._task_id == task_id:
        self._reset_usage_context()
        self._set_plan([])


@Slot()
def duplicateTask(self):
    if self._busy or not self._task_id:
        return
    mode = self._task_mode
    plan = [dict(step) for step in self._plan_steps]
    previous = self._task_id
    Controller.duplicateTask(self, )
    if self._task_id and self._task_id != previous:
        self._task_mode = mode
        self._task_mode_locked = True
        self._set_plan(plan)
        self._persist_task_mode()
        self._emit_mode()


@Slot(str)
def duplicateTaskById(self, task_id):
    if self._busy:
        return
    mode = self._saved_mode(task_id)
    plan = self._saved_plan(task_id)
    previous = self._task_id
    Controller.duplicateTaskById(self, task_id)
    if self._task_id and self._task_id != previous:
        self._task_mode = mode
        self._task_mode_locked = True
        self._set_plan(plan)
        self._persist_task_mode()
        self._emit_mode()


@Slot(int)
def branchFrom(self, row):
    if self._busy or not self._task_id:
        return
    mode = self._task_mode
    plan = [dict(step) for step in self._plan_steps]
    previous = self._task_id
    Controller.branchFrom(self, row)
    if self._task_id and self._task_id != previous:
        self._task_mode = mode
        self._task_mode_locked = True
        self._set_plan(plan)
        self._persist_task_mode()
        self._emit_mode()


def shutdown(self):
    """Stop the workspace exactly once, even when a host calls twice.

    Snapshot/demo controllers are rotated during rendering, so an older
    controller may already have closed its store when process cleanup calls
    shutdown again. Production close paths also benefit from idempotence.
    """
    if getattr(self, "_workspace_shutdown", False):
        return
    if hasattr(self, "_draft_persist_timer"):
        self._draft_persist_timer.stop()
    self._persist_current_draft()
    self._set_last_task(self._task_id)
    self.store.set_setting(self.ACTIVE_RUNS_KEY, [])
    self._workspace_shutdown = True
    Controller.shutdown(self, )
