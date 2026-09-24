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

def _read_conversation_tokens(self, task_id: str | None = None) -> int:
    getter = getattr(self.store, "conversation_token_usage", None)
    target = str(self._task_id if task_id is None else task_id or "")
    if not target or not callable(getter):
        return 0
    try:
        return max(0, int((getter(target) or {}).get("tokens", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _reset_usage_context(self) -> None:
    """Use a fresh tracker so leaving a live chat never resets its counter."""
    self._usage = TokenUsageTracker(self.store)
    self._usage.reset()
    self._conversation_tokens = self._read_conversation_tokens()
    self.usageChanged.emit()


def _finalize_usage(self) -> bool:
    """Record one run and update the cached current-chat total exactly once."""
    if not self._usage.finalize(self._task_id, self._model):
        return False
    metrics = self._usage.metrics
    self._conversation_tokens += max(0, int(metrics.get("tokens", 0) or 0))
    self._conversation_tokens += max(0, int(metrics.get("prompt_tokens", 0) or 0))
    self.usageChanged.emit()
    return True


@Slot()
def refreshTokenUsage(self):
    if self._usage.refresh():
        self.usageChanged.emit()


@Slot(str, result=bool)
def selectEndpoint(self, endpoint):
    previous = self._endpoint
    result = Controller.selectEndpoint(self, endpoint)
    if result and self._endpoint != previous:
        self.endpointChanged.emit()
    return result


@Slot(str, result=bool)
def setEndpoint(self, endpoint):
    previous = self._endpoint
    result = Controller.setEndpoint(self, endpoint)
    if result and self._endpoint != previous:
        self.endpointChanged.emit()
    return result


def _set_project(self, path: str):
    """Switch folders only after the dock accepts losing its current state.

    A dirty editor buffer is owned by the dock. Let that boundary veto the
    transition before updating settings/recent-project history, otherwise a
    refused switch would leave the controller and dock pointing at different
    projects.
    """
    path = str(path or "")
    if path == self._working_directory:
        return True
    if not self.dock.set_project(path):
        return False
    self._working_directory = path
    self.store.set_setting("working_directory", path)
    fresh_instructions = project_instructions.summary(path)
    if fresh_instructions != self._project_instructions_summary:
        self._project_instructions_summary = fresh_instructions
        self.contextStateChanged.emit()
    if path:
        self._recent_projects = [path] + [p for p in self._recent_projects if p != path]
        del self._recent_projects[self.RECENT_PROJECT_LIMIT:]
        self.store.set_setting("recent_projects", self._recent_projects)
        self.dock.suggest("files")
    self.changed.emit()
    return True


@Slot()
def chooseProject(self):
    from PySide6.QtWidgets import QFileDialog
    start = self._working_directory or ctx.default_directory()
    path = QFileDialog.getExistingDirectory(None, "Choose a project folder", start)
    if path and self._set_project(path):
        self.toast.emit(f"Working in {ctx.working_directory_label(path)}")


__all__ = ['refreshTokenUsage', 'selectEndpoint', 'setEndpoint', 'chooseProject']
