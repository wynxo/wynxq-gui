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

@Slot(str, result=bool)
def navigate(self, text):
    target = browser_policy.normalize(text)
    if not target:
        self._browser_error = "That is not an address Wynxq can open"
        self.browserChanged.emit()
        return False
    self._browser_error = ""
    self._browser_pending = target
    self._browser_loading = True
    self.browserChanged.emit()
    return True


@Slot(str, str)
def browserStateChanged(self, url, title):
    """Reported by the view, which is the only thing that knows for sure."""
    value = str(url or "")
    # The blank page the view starts on is not somewhere you have been.
    self._browser_url = "" if value in ("", "about:blank") else value
    self._browser_title = "" if not self._browser_url else str(title or "")
    self.browserChanged.emit()
    self.contextChanged.emit()


@Slot(bool, float)
def browserLoadState(self, loading, progress):
    self._browser_loading = bool(loading)
    self._browser_progress = max(0.0, min(float(progress or 0), 1.0))
    self.browserChanged.emit()


@Slot(bool, bool)
def browserHistoryState(self, back, forward):
    self._browser_can_back = bool(back)
    self._browser_can_forward = bool(forward)
    self.browserChanged.emit()


@Slot(str)
def browserFailed(self, message):
    self._browser_error = str(message or "")
    self._browser_loading = False
    self.browserChanged.emit()


@Slot()
def clearBrowser(self):
    self._browser_url = ""
    self._browser_title = ""
    self._browser_pending = ""
    self._browser_error = ""
    self.browserChanged.emit()
    self.contextChanged.emit()


@Slot(str, str, str)
def attachPage(self, url, title, text):
    """Hand the current page to the composer as one piece of context."""
    owner = self._owner
    if owner is None:
        return
    page = browser_policy.page_context(url, title, text)
    attach = getattr(owner, "attach_web_page", None)
    if callable(attach):
        attach(page)
        self.contextChanged.emit()


@Slot(str, str, str)
def showPreview(self, kind, title, payload):
    kind = str(kind or "")
    if kind not in ("image", "markdown", "html", "text"):
        return
    self._preview = {"kind": kind, "title": str(title or ""), "body": str(payload)}
    if kind == "image":
        self._preview["image"] = str(payload)
    self.previewChanged.emit()
    self.suggest("preview", open_dock=True)


@Slot()
def clearPreview(self):
    self._preview = {}
    self.previewChanged.emit()


def shutdown(self) -> None:
    """Tear down without leaving anything queued at a dead receiver.

    A worker that has finished may still have its `finished` signal waiting
    for an event loop that will never run again. Cutting the connections
    here — rather than trusting `deleteLater` — is what makes shutdown safe
    from a controller that is about to be freed.
    """
    self._search_generation += 1
    self._search_debounce.stop()
    self._poll.stop()
    self._teardown_shell()
    self._worker_queue.clear()
    for worker in list(self._workers):
        # Only the active worker can be running; queued workers have never
        # been started and are safe to detach immediately.
        if worker.isRunning():
            worker.quit()
            finished = worker.wait(2000)
        else:
            finished = True
        for signal in (worker.done, worker.failed, worker.finished):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        if finished:
            worker.setParent(None)          # now owned by Python alone
            continue
        # Still inside `run`. Keep a strong reference so neither Qt nor
        # Python frees a thread that is mid-call.
        worker.setParent(None)
        _ORPHANED.add(worker)
        worker.finished.connect(lambda w=worker: _ORPHANED.discard(w))
    self._workers.clear()
    self._active_worker = None


__all__ = ['navigate', 'browserStateChanged', 'browserLoadState', 'browserHistoryState', 'browserFailed', 'clearBrowser', 'attachPage', 'showPreview', 'clearPreview', 'shutdown']
