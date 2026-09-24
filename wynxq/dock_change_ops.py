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

def _run(self, fn, done):
    """Queue `fn` off the GUI thread and hand its result to `done`.

    Only one worker is started at a time. Besides avoiding redundant I/O,
    this matters for PySide on Linux: creating overlapping QThreads while a
    Git subprocess and native directory scan are active can segfault inside
    Qt/Python instead of raising an exception. Queued work is still fully
    asynchronous from the GUI's point of view.

    The result is delivered through a bound slot rather than a closure.
    A closure is not a QObject, so Qt cannot sever it when this controller
    is destroyed, and a Git call landing after teardown would then reach
    into freed memory. Going through `_deliver` gives the connection a
    receiver, and Qt drops it with the receiver.
    """
    worker = _Worker(fn, self)
    worker.callback = done
    worker.done.connect(self._deliver)
    worker.failed.connect(self._deliver_failure)
    worker.settled.connect(self._retire_worker)
    self._workers.add(worker)
    if self._active_worker is None:
        self._active_worker = worker
        worker.start()
    else:
        self._worker_queue.append(worker)
    return worker


def _start_next_worker(self) -> None:
    if self._active_worker is not None:
        return
    while self._worker_queue:
        worker = self._worker_queue.pop(0)
        if worker not in self._workers:
            continue
        self._active_worker = worker
        worker.start()
        return


@Slot(object, object)
def _deliver(self, worker, payload):
    callback = getattr(worker, "callback", None)
    if callable(callback):
        callback(payload)


@Slot(object, str)
def _deliver_failure(self, worker, message):
    self.toast.emit(message)


@Slot(object)
def _retire_worker(self, worker):
    # QThread.finished() is emitted before thread-local cleanup is
    # guaranteed complete. Join here before another worker starts so Python
    # and native thread-local teardown cannot overlap the next task.
    if worker is not None:
        worker.wait()
    self._workers.discard(worker)
    if worker is self._active_worker:
        self._active_worker = None
    if worker in self._worker_queue:
        self._worker_queue.remove(worker)
    if worker is not None:
        worker.deleteLater()
    self._start_next_worker()


@Slot()
def refreshChanges(self):
    if not self._project or self._changes_busy:
        return
    self._changes_busy = True
    self.changesChanged.emit()
    project = self._project

    def finish(result):
        self._changes_busy = False
        if project == self._project:
            self._changes = result
            base = Path(project).resolve()
            self.tree.set_dirty({str(base / entry["path"]) for entry in result["files"]})
            if self._change_path and not any(
                    entry["path"] == self._change_path for entry in result["files"]):
                self._change_path = ""
                self._diff = {"rows": [], "error": "", "path": "", "binary": False}
        self.changesChanged.emit()

    self._run(lambda: diffs.changed_files(project), finish)


@Slot(str)
def openDiff(self, path):
    path = str(path or "")
    if not self._project or not path:
        return
    self._change_path = path
    untracked = any(entry["path"] == path and entry.get("untracked")
                    for entry in self._changes.get("files", []))
    self._diff = {"rows": [], "error": "Loading…", "path": path, "binary": False}
    self.changesChanged.emit()
    project = self._project

    def finish(result):
        if project == self._project and self._change_path == path:
            self._diff = result
        self.changesChanged.emit()

    self._run(lambda: diffs.file_diff(project, path, untracked), finish)


@Slot()
def closeDiff(self):
    self._change_path = ""
    self._diff = {"rows": [], "error": "", "path": "", "binary": False}
    self.changesChanged.emit()


@Slot(str, result=bool)
def revertChange(self, path):
    """Discard one file's changes. The UI confirms before calling this."""
    path = str(path or "")
    if not self._project or not path:
        return False
    untracked = any(entry["path"] == path and entry.get("untracked")
                    for entry in self._changes.get("files", []))
    result = diffs.revert_file(self._project, path, untracked)
    if not result.get("ok"):
        self.toast.emit(result.get("error") or "Could not revert that file")
        return False
    self.toast.emit(("Deleted " if result.get("deleted") else "Reverted ") + Path(path).name)
    if self._viewer.get("path"):
        try:
            if Path(self._viewer["path"]) == Path(self._project) / path:
                self.openFile(self._viewer["path"]) if Path(self._viewer["path"]).exists() \
                    else self.closeFile()
        except (OSError, ValueError):
            pass
    self.closeDiff()
    self.refreshChanges()
    return True


@Slot(str, result=str)
def absolutePath(self, relative):
    if not self._project:
        return ""
    try:
        return str(files.resolve_within(self._project, str(relative)))
    except (OSError, ValueError):
        return ""


__all__ = ['refreshChanges', 'openDiff', 'closeDiff', 'revertChange', 'absolutePath']
