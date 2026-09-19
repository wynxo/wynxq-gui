"""Workspace-dock behavior slice bound onto DockController."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Property, QSocketNotifier, QTimer, Signal, Slot

from . import browser as browser_policy
from . import diffs
from . import project_files as files
from .activity import ActivityLog
from .terminal import ShellSession
from .dock_contract import DEFAULT_WIDTH, MAX_WIDTH, MIN_WIDTH, TABS, TAB_META
from .dock_models import FileTree, TerminalLines, _ORPHANED, _Worker

@Slot(str)
def removeContext(self, identifier):
    identifier = str(identifier or "")
    if identifier == "file":
        self.closeFile()
    elif identifier == "browser":
        self.clearBrowser()
    elif identifier.startswith("attachment:") and self._owner is not None:
        remove = getattr(self._owner, "removeAttachment", None)
        if callable(remove):
            remove(identifier.split(":", 1)[1])
    self.contextChanged.emit()


def refresh_context(self) -> None:
    self.contextChanged.emit()


@Slot()
def clearActivity(self):
    self.log.clear()
    self.activityChanged.emit()


def record(self, event: dict) -> None:
    self.log.append(event)
    self.activityChanged.emit()


def record_update(self, **fields) -> None:
    self.log.update_last(**fields)
    self.activityChanged.emit()


def begin_turn(self, title: str) -> None:
    self.log.begin_turn(title)
    self.activityChanged.emit()


def settle_turn(self, state: str) -> None:
    self.log.settle_turn(state)
    self.activityChanged.emit()
