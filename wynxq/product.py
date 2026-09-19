"""Top-level product behavior for Wynxq GUI.

WorkspaceController keeps the durable task/workspace machinery. ProductController
adds the interaction model exposed by the shell: Chat is a true tool-free mode,
while Work is the same task with local coding/tools enabled and a live autonomy
level. Users can move between them whenever the task is idle; the selected task
mode is persisted immediately so reopening a conversation never guesses.

The product controller also owns the runtime worker used by the real app. Ollama,
Git-adjacent tooling and command execution are normal Python work, so they run on
a ``threading.Thread`` rather than inside a PySide ``QThread``. Qt signals are
used only to marshal results and streaming events back onto the GUI thread.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Property, Signal, Slot

from .engine import PERMISSION_MODES
from .workspace import WorkspaceController


class _ProductJob(QObject):
    """One cancellable Python-thread job with Qt signals for GUI delivery."""

    event = Signal(object)
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.result_callback = None
        self.failure_callback = None
        self.event_callback = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="wynxq-product-job",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            self.result.emit(self.function(self.cancel, self.event.emit))
        except Exception as exc:  # pragma: no cover - defensive runtime boundary
            self.failed.emit(str(exc) or type(exc).__name__)
        finally:
            self.finished.emit()

    def isRunning(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait(self, msec: int = 0) -> bool:
        thread = self._thread
        if thread is None:
            return True
        timeout = None if not msec or msec < 0 else msec / 1000.0
        thread.join(timeout)
        return not thread.is_alive()


class ProductController(WorkspaceController):
    """Workspace controller with live Chat / Work switching."""

    def _job(self, fn, result=None, failure=None, event=None):
        """Run product work outside Qt-owned threads and deliver on the GUI thread."""
        job = _ProductJob(fn, self)
        job.result_callback = result
        job.failure_callback = failure or self._show_error
        job.event_callback = event
        job.result.connect(self._deliver_product_result)
        job.failed.connect(self._deliver_product_failure)
        job.event.connect(self._deliver_product_event)
        job.finished.connect(self._retire_product_job)
        self._jobs.add(job)
        job.start()
        return job

    @Slot(object)
    def _deliver_product_result(self, payload):
        job = self.sender()
        callback = getattr(job, "result_callback", None)
        if callable(callback):
            callback(payload)

    @Slot(str)
    def _deliver_product_failure(self, message):
        job = self.sender()
        callback = getattr(job, "failure_callback", None)
        if callable(callback):
            callback(message)

    @Slot(object)
    def _deliver_product_event(self, event):
        job = self.sender()
        callback = getattr(job, "event_callback", None)
        if callable(callback):
            callback(event)

    @Slot()
    def _retire_product_job(self):
        job = self.sender()
        if job is None:
            return
        # ``finished`` is emitted from the Python worker just before its target
        # returns. Join that tiny tail before deleting the QObject or starting
        # teardown so neither Python nor Qt can observe a half-retired job.
        job.wait()
        self._jobs.discard(job)
        job.deleteLater()

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
            self.toast.emit(f"Work mode — {self._permission_mode.title()} autonomy")
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
