"""Small runtime helpers used by the Qt application coordinator.

These objects deliberately know nothing about QML layout or conversation
storage. They isolate background-job plumbing, desktop-run scoping, portal
token persistence, and value formatting from the main Controller.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot

from .desktop_common import SessionTokens


def _bounded_int(value, low, high, default):
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def _bounded_float(value, low, high, default):
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return default


def _blank_metrics() -> dict:
    return {"tokens": 0, "prompt_tokens": 0, "cached_prompt_tokens": 0,
            "load_ms": 0.0, "total_ms": 0.0, "tokens_per_second": 0.0}


def _human_bytes(count) -> str:
    try:
        size = float(count)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if size >= 100 or unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


class Job(QThread):
    event = Signal(dict)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.function(self.cancel, self.event.emit))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class CaptureVisibility(QObject):
    """A GUI-thread acknowledgement before the worker captures the desktop."""
    requested = Signal(object)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._requests = set()
        self.requested.connect(self._apply)

    @Property(bool, notify=changed)
    def hidden(self):
        return bool(self._requests)

    @Slot(object)
    def _apply(self, request):
        token, hide, ready = request
        if hide:
            self._requests.add(token)
        else:
            self._requests.discard(token)
        self.changed.emit()
        # Wait for Qt and the compositor to present the transparent HUD.
        if ready is not None:
            QTimer.singleShot(120, ready.set)

    @contextmanager
    def capture(self, cancel=None):
        from .desktop_common import DesktopCancelled, DesktopError
        token, ready = object(), threading.Event()
        self.requested.emit((token, True, ready))
        try:
            deadline = time.monotonic() + 2.0
            while not ready.wait(0.02):
                if cancel is not None and cancel.is_set():
                    raise DesktopCancelled("Desktop capture stopped")
                if time.monotonic() >= deadline:
                    raise DesktopError("The desktop overlay did not clear for capture. Try again.")
            if cancel is not None and cancel.is_set():
                raise DesktopCancelled("Desktop capture stopped")
            yield
        finally:
            self.requested.emit((token, False, None))


class _RunDesktop:
    """Foreground-gated view of the shared desktop for one conversation run."""
    _NONVISUAL_DESKTOP = {"open_app", "list_apps", "wait"}

    def __init__(self, owner, task_id: str):
        self.owner = owner
        self.task_id = str(task_id)

    def status(self):
        status = dict(self.owner.desktop.status() if self.owner.desktop else {})
        if self.task_id != self.owner._task_id:
            status["connected"] = False
            status["detail"] = "Screen control pauses while this task is in the background"
        return status

    def execute(self, name, arguments, cancel=None):
        if name not in self._NONVISUAL_DESKTOP and self.task_id != self.owner._task_id:
            return {"ok": False, "error":
                    "Screen interaction is foreground-only. Open this task to continue visual control."}
        if name not in self._NONVISUAL_DESKTOP and hasattr(self.owner.desktop, "begin_control"):
            self.owner.desktop.begin_control(self.task_id)
        if name == "screenshot":
            with self.owner._capture_visibility.capture(cancel):
                if self.task_id != self.owner._task_id:
                    return {"ok": False, "error": "Screen capture paused: the task is in the background."}
                return self.owner.desktop.execute(name, arguments, cancel)
        return self.owner.desktop.execute(name, arguments, cancel)


class _StoredTokens(SessionTokens):
    """Keeps the portal's restore token in the same private database as the
    rest of the settings, so screen control stops asking on every launch."""

    def __init__(self, store):
        super().__init__()
        self._store = store

    def load(self) -> str:
        return str(self._store.get_setting("desktop_restore_token", "") or "")

    def save(self, token: str) -> None:
        self._store.set_setting("desktop_restore_token", str(token or ""))


__all__ = [
    "Job", "_RunDesktop", "_StoredTokens", "_blank_metrics", "_bounded_float",
    "_bounded_int", "_human_bytes",
]
