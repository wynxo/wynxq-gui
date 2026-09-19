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

@Slot(str, int)
def moveTab(self, name, direction):
    name = str(name or "")
    if name not in self._tab_order:
        return
    old = self._tab_order.index(name)
    new = max(0, min(len(self._tab_order) - 1, old + int(direction or 0)))
    if new == old:
        return
    self._tab_order.pop(old)
    self._tab_order.insert(new, name)
    self._remember("dock_tab_order", list(self._tab_order))
    self.changed.emit()


@Slot(str, bool)
def setTabHidden(self, name, hidden):
    name = str(name or "")
    if name not in TABS:
        return
    hidden = bool(hidden)
    if hidden and name not in self._hidden_tabs:
        if len(TABS) - len(self._hidden_tabs) <= 1:
            self.toast.emit("Keep at least one workspace tool on the rail.")
            return
        self._hidden_tabs.add(name)
    elif not hidden and name in self._hidden_tabs:
        self._hidden_tabs.remove(name)
    else:
        return
    self._remember("dock_hidden_tabs", sorted(self._hidden_tabs))
    if self._tab in self._hidden_tabs:
        visible = [item for item in self._tab_order if item not in self._hidden_tabs]
        if visible:
            self._select_tab(visible[0])
    self.changed.emit()


@Slot()
def resetTabLayout(self):
    self._tab_order = list(TABS)
    self._hidden_tabs.clear()
    self._remember("dock_tab_order", list(self._tab_order))
    self._remember("dock_hidden_tabs", [])
    self.changed.emit()


def _remember(self, key: str, value) -> None:
    if self._store is not None:
        self._store.set_setting(key, value)


@Slot(bool)
def setVisible(self, value):
    value = bool(value)
    if value == self._visible:
        return
    self._visible = value
    self._remember("dock_visible", value)
    if value:
        self._on_tab_shown(self._tab)
    else:
        self._poll.stop()
    self.changed.emit()


@Slot()
def toggle(self):
    self.setVisible(not self._visible)


@Slot(int)
def setWidth(self, value):
    value = max(MIN_WIDTH, min(int(value or DEFAULT_WIDTH), MAX_WIDTH))
    if value == self._width:
        return
    self._width = value
    self._remember("dock_width", value)
    self.changed.emit()


@Slot(str)
def setTab(self, name):
    """The user picked a tab. From here on it is theirs."""
    name = str(name or "")
    if name not in TABS:
        return
    self._tab_pinned = True
    self._remember("dock_tab_pinned", True)
    self._select_tab(name)


@Slot(str)
def openTab(self, name):
    """Show a tab and the dock with it — for a shortcut or the palette."""
    name = str(name or "")
    if name not in TABS:
        return
    if name in self._hidden_tabs:
        self._hidden_tabs.remove(name)
        self._remember("dock_hidden_tabs", sorted(self._hidden_tabs))
        self.changed.emit()
    if self._visible and self._tab == name:
        self.setVisible(False)
        return
    self._tab_pinned = True
    self._remember("dock_tab_pinned", True)
    self._select_tab(name)
    self.setVisible(True)


def _select_tab(self, name: str) -> None:
    if name == self._tab:
        self._on_tab_shown(name)
        return
    self._tab = name
    self._remember("dock_tab", name)
    self._on_tab_shown(name)
    self.changed.emit()


def suggest(self, name: str, *, open_dock: bool = False) -> None:
    """A hint from the app, not a command.

    Honoured only while the user has never chosen a tab by hand. This is
    the whole of the dock's "adaptive" behaviour: it can be helpful once,
    and after that it stays where it was put.
    """
    if name not in TABS or self._tab_pinned:
        return
    if open_dock and not self._visible:
        self.setVisible(True)
    if self._visible or open_dock:
        self._select_tab(name)


def _on_tab_shown(self, name: str) -> None:
    if not self._visible:
        return
    if name == "terminal":
        self.startTerminal()
        self._poll.start()
    else:
        self._poll.stop()
    if name == "changes":
        self.refreshChanges()
    if name == "files" and self.tree.root and self.tree.rowCount() == 0:
        self.tree.reload()


def _block_dirty_transition(self, action: str) -> bool:
    """Refuse any transition that would replace an unsaved editor buffer."""
    if not self._viewer_dirty:
        return False
    name = str(self._viewer.get("name") or "the open file")
    self.toast.emit(f"Save or discard edits in {name} before {action}.")
    return True


def set_project(self, path: str) -> bool:
    path = str(path or "")
    if path == self._project:
        return True
    if self._block_dirty_transition("switching projects"):
        return False
    self._search_generation += 1
    self._search_debounce.stop()
    self._project = path
    self.tree.set_root(path)
    self._file_filter = ""
    self._search_results = []
    self._viewer = {}
    self._viewer_buffer = ""
    self._viewer_dirty = False
    self._change_path = ""
    self._diff = {"rows": [], "error": "", "path": "", "binary": False}
    self._changes = {"repository": False, "branch": "", "files": [],
                     "added": 0, "removed": 0, "error": ""}
    if self._shell is not None:
        self.restartTerminal()
    self.changed.emit()
    self.filesChanged.emit()
    self.viewerChanged.emit()
    self.changesChanged.emit()
    self.contextChanged.emit()
    if path:
        self.refreshChanges()
    return True
