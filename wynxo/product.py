"""Top-level product behavior for Wynxq GUI.

WorkspaceController keeps the durable task/workspace machinery. ProductController
adds the interaction model exposed by the shell: Chat is a true tool-free mode,
while Agent is the same task with local tools enabled and a live autonomy level.
Users can move between them whenever the task is idle; the selected task mode is
persisted immediately so reopening a conversation never guesses.
"""
from __future__ import annotations

from PySide6.QtCore import Property, Slot

from .engine import PERMISSION_MODES
from .workspace import WorkspaceController


class ProductController(WorkspaceController):
    """Workspace controller with live Chat / Agent switching."""

    @Property(bool, notify=WorkspaceController.modeChanged)
    def taskModeLocked(self):
        """The mode is editable whenever changing it cannot race a live run."""
        return bool(self._busy or self._connecting)

    @Slot(str, result=bool)
    def setTaskMode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in self.VALID_TASK_MODES or self._busy or self._connecting:
            return False
        if mode == self._task_mode:
            self._task_mode_locked = True
            return True

        self._task_mode = mode
        self._task_mode_locked = True
        self._session_auto = False
        if self._task_id:
            self._persist_task_mode()
        self._emit_mode()
        if mode == "chat":
            self.toast.emit("Chat mode — tools are off for this task")
        else:
            self.toast.emit(f"Agent mode — {self._permission_mode.title()} autonomy")
        return True

    @Slot(str)
    def setPermissionMode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in PERMISSION_MODES or mode == self._permission_mode:
            return
        # Changing autonomy invalidates a previous "allow the rest of this run"
        # choice immediately. WorkspaceController also re-reads the permission
        # mode before every tool action, so this is safe to change mid-run.
        self._session_auto = False
        super().setPermissionMode(mode)
