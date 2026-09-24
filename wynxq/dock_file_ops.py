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

@Slot(bool)
def setShowHidden(self, value):
    value = bool(value)
    changed = value != self.tree.show_hidden
    self.tree.set_show_hidden(value)
    self._remember("dock_show_hidden", value)
    if changed and self._file_filter.strip():
        self._search_generation += 1
        self._search_debounce.stop()
        self._search_results = []
        if len(self._file_filter.strip()) >= 2 and self._project:
            self._search_debounce.start()
    self.filesChanged.emit()


@Slot(str)
def setFileFilter(self, text):
    text = str(text or "")
    if text == self._file_filter:
        return
    self._file_filter = text
    self._search_generation += 1
    self._search_debounce.stop()
    self._search_results = []
    self.filesChanged.emit()
    if len(text.strip()) >= 2 and self._project:
        self._search_debounce.start()


@Slot()
def _start_file_search(self):
    needle = self._file_filter.strip()
    project = self._project
    show_hidden = self.tree.show_hidden
    generation = self._search_generation
    if len(needle) < 2 or not project:
        return

    def search():
        try:
            return files.search_tree(
                project, needle, limit=120, show_hidden=show_hidden)
        except (OSError, ValueError):
            return []

    def finish(results):
        if generation != self._search_generation:
            return
        if project != self._project or needle != self._file_filter.strip():
            return
        if show_hidden != self.tree.show_hidden:
            return
        self._search_results = list(results or [])
        self.filesChanged.emit()

    self._run(search, finish)


@Slot()
def refreshFiles(self):
    self.tree.reload()
    if self._file_filter:
        filter_text, self._file_filter = self._file_filter, ""
        self.setFileFilter(filter_text)


@Slot(str)
def toggleFolder(self, path):
    self.tree.toggle(str(path))


@Slot(str)
def revealFile(self, path):
    row = self.tree.reveal(str(path))
    if row >= 0:
        self.tree.set_selected(str(path))
        self.revealRow.emit(row)


@Slot(str, result=bool)
def openFile(self, path):
    if not self._project or not path:
        return False
    try:
        target = str(files.resolve_within(self._project, str(path)))
    except (OSError, ValueError):
        target = str(path)
    if self._viewer_dirty:
        # Reopening the same file must never reload its on-disk copy over
        # the user's buffer. Another file is a destructive transition and
        # is refused until the caller explicitly saves or discards first.
        if target == str(self._viewer.get("path", "")):
            return True
        if self._block_dirty_transition("opening another file"):
            return False
    try:
        record = files.read_file(self._project, str(path))
    except (OSError, ValueError) as exc:
        name = Path(str(path)).name
        self._viewer = {"path": str(path), "name": name, "lines": 0, "text": "",
                        "error": files.explain(exc, f"“{name}”")}
        self._viewer_buffer = ""
        self._viewer_dirty = False
        self.viewerChanged.emit()
        return False
    base = Path(self._project).resolve()
    try:
        record["relative"] = str(Path(record["path"]).relative_to(base))
    except ValueError:
        record["relative"] = record["name"]
    self._viewer = record
    self._viewer_buffer = record.get("text", "")
    self._viewer_dirty = False
    self.tree.set_selected(record["path"])
    self.viewerChanged.emit()
    if record.get("image"):
        self._preview = {"kind": "image", "title": record["name"],
                         "image": record["image"], "path": record["path"]}
        self.previewChanged.emit()
    return True


@Slot(result=bool)
def closeFile(self):
    if self._block_dirty_transition("closing the file"):
        return False
    self._viewer = {}
    self._viewer_buffer = ""
    self._viewer_dirty = False
    self.tree.set_selected("")
    self.viewerChanged.emit()
    return True


@Slot(str)
def setFileBuffer(self, text):
    text = str(text)
    if text == self._viewer_buffer:
        return
    self._viewer_buffer = text
    dirty = text != self._viewer.get("text", "")
    if dirty != self._viewer_dirty:
        self._viewer_dirty = dirty
        self.viewerChanged.emit()


@Slot(result=bool)
def saveFile(self):
    if not self._viewer_dirty or not self._viewer.get("path"):
        return False
    try:
        files.write_file(self._project, self._viewer["path"], self._viewer_buffer)
    except (OSError, ValueError) as exc:
        self.toast.emit(files.explain(exc, f"“{self._viewer.get('name', 'That file')}”"))
        return False
    self._viewer["text"] = self._viewer_buffer
    self._viewer_dirty = False
    self.viewerChanged.emit()
    self.toast.emit(f"Saved {self._viewer.get('name', 'file')}")
    self.refreshChanges()
    return True


@Slot()
def revertFileBuffer(self):
    self._viewer_buffer = self._viewer.get("text", "")
    if self._viewer_dirty:
        self._viewer_dirty = False
    self.viewerChanged.emit()


__all__ = ['setShowHidden', 'setFileFilter', 'refreshFiles', 'toggleFolder', 'revealFile', 'openFile', 'closeFile', 'setFileBuffer', 'saveFile', 'revertFileBuffer']
