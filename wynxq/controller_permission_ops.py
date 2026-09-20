"""Controller behavior slice.

This module contains implementation methods bound onto the public Controller
facade at class creation time. Keeping the Qt-facing API on Controller preserves
QML compatibility while separating unrelated responsibilities in source.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication

from . import context as ctx
from . import markdown as md
from . import notify
from . import system as system_info
from . import kwin
from .desktop import DesktopController
from .dock import DockController
from .agent_tools import (
    PERMISSION_DETAILS, PERMISSION_LABELS, PERMISSION_MODES, SAFE,
    action_summary, normalise_mode,
)
from .engine import AgentEngine, OllamaClient
from .memory import Memory
from .storage import Store
from .conversation import (
    GROUP_ORDER, STARTERS, TOOL_PRESENTATION, Messages, derive_title, group_for,
)
from .controller_support import (
    Job, _RunDesktop, _StoredTokens, _blank_metrics, _bounded_float,
    _bounded_int, _human_bytes,
)

def _confirm_action_for(self, task_id: str, name: str, args: dict, risk: str) -> bool:
    """Block only the run asking for permission; other chats stay usable."""
    state = self._run_sessions.get(str(task_id or ""))
    if not state:
        # Preserve the direct/foreground permission path used by small
        # controller hosts and tests that do not create a run session.
        if self._session_auto and risk != "destructive":
            return True
        self._permission_event.clear()
        self._permission_answer = False
        self._pending_permission = {
            "tool": name, "risk": risk, "summary": action_summary(name, args),
            "detail": json.dumps(args, ensure_ascii=False) if args else "",
            "command": str(args.get("command", "")) if name == "run_command" else "",
            "directory": (str(args.get("cwd") or self._working_directory or Path.home())
                          if name == "run_command" else ""),
        }
        self.permissionChanged.emit()
        self.changed.emit()
        allowed = self._permission_event.wait(self.PERMISSION_TIMEOUT)
        answer = bool(allowed and self._permission_answer)
        self._pending_permission = None
        self.permissionChanged.emit()
        self.changed.emit()
        return answer
    if state.get("session_auto") and risk != "destructive":
        return True
    event = state["permission_event"]
    event.clear()
    state["permission_answer"] = False
    state["permission"] = {
        "tool": name, "risk": risk, "summary": action_summary(name, args),
        "detail": json.dumps(args, ensure_ascii=False) if args else "",
        "command": str(args.get("command", "")) if name == "run_command" else "",
        "directory": (str(args.get("cwd") or state.get("project") or Path.home())
                      if name == "run_command" else ""),
    }
    if task_id == self._task_id:
        self._pending_permission = state["permission"]
        self.permissionChanged.emit()
        self.changed.emit()
    allowed = event.wait(self.PERMISSION_TIMEOUT)
    answer = bool(allowed and state.get("permission_answer"))
    state["permission"] = None
    if task_id == self._task_id:
        self._pending_permission = None
        self.permissionChanged.emit()
        self.changed.emit()
    return answer


def _confirm_action(self, name: str, args: dict, risk: str) -> bool:
    return self._confirm_action_for(self._task_id, name, args, risk)


@Slot(bool)
def resolvePermission(self, allowed):
    state = self._active_session()
    if state and state.get("permission") is not None:
        state["permission_answer"] = bool(allowed)
        self._permission_answer = bool(allowed)
        state["permission_event"].set()
        return
    if self._pending_permission is not None:
        self._permission_answer = bool(allowed)
        self._permission_event.set()


@Slot()
def allowRestOfTask(self):
    state = self._active_session()
    if state and state.get("permission") is not None:
        state["session_auto"] = True
        state["permission_answer"] = True
        self._session_auto = True
        state["permission_event"].set()
        self.toast.emit("Approving the rest of this task, except anything that cannot be undone")
        return
    if self._pending_permission is not None:
        self._session_auto = True
        self._permission_answer = True
        self._permission_event.set()
        self.toast.emit("Approving the rest of this task, except anything that cannot be undone")


@Slot(str)
def setPermissionMode(self, mode):
    mode = str(mode)
    if mode not in PERMISSION_MODES or mode == self._permission_mode:
        return
    self._permission_mode = mode
    self.store.set_setting("permission_mode", mode)
    for state in self._run_sessions.values():
        if state.get("busy"):
            state["session_auto"] = False
    self._session_auto = False
    self.changed.emit()
    self.toast.emit(f"Permission set to {PERMISSION_LABELS[mode]}")


def _memory_for_run(self):
    """The memory a run may read and write, or None while memory is off."""
    return self.memory if self._memory_enabled else None


@Slot(bool)
def setMemoryEnabled(self, enabled):
    enabled = bool(enabled)
    if enabled == self._memory_enabled:
        return
    self._memory_enabled = enabled
    self.store.set_setting("memory_enabled", enabled)
    self.memoryChanged.emit()
    self.changed.emit()
    self.toast.emit("Memory is on. Notes are read into every task."
                    if enabled else "Memory is off. The file is kept, but nothing reads it.")


@Slot(bool)
def setReferenceChatHistory(self, enabled):
    enabled = bool(enabled)
    if enabled == self._reference_chat_history:
        return
    self._reference_chat_history = enabled
    self.store.set_setting("reference_chat_history", enabled)
    self.memoryChanged.emit()
    self.changed.emit()
    self.toast.emit(
        "Past chats can be referenced when relevant."
        if enabled else "Past-chat reference is off."
    )


@Slot(str)
def saveMemory(self, text):
    """Save the memory file as edited in Wynxq, replacing what was there."""
    try:
        self.memory.write(text)
    except (OSError, ValueError) as exc:
        self.toast.emit(str(exc))
        return
    self.memoryChanged.emit()
    self.toast.emit("Memory saved")


@Slot(str)
def rememberNote(self, note):
    """Add one note by hand, the same way the model's remember tool does."""
    try:
        result = self.memory.remember(note, project=self._working_directory)
    except (OSError, ValueError) as exc:
        self.toast.emit(str(exc))
        return
    self.memoryChanged.emit()
    self.toast.emit("Remembered" if result.get("stored") else "Already remembered")


@Slot()
def clearMemory(self):
    try:
        self.memory.clear()
    except OSError as exc:
        self.toast.emit(str(exc))
        return
    self.memoryChanged.emit()
    self.toast.emit("Memory cleared")


@Slot()
def reloadMemory(self):
    """Re-read the file — it is plain Markdown, so anything may have edited it."""
    self.memoryChanged.emit()


@Slot()
def revealMemory(self):
    if not self.memory.exists():
        try:
            self.memory.clear()
        except OSError as exc:
            self.toast.emit(str(exc))
            return
        self.memoryChanged.emit()
    if not notify.open_path(str(self.memory.path)):
        self.copyText(str(self.memory.path))
        self.toast.emit("No application opened it, so the path was copied instead.")
