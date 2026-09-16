"""The workspace dock: the tools on the right-hand side of the window.

One QObject per concern, assembled here and exposed to QML as `bridge.dock`.
The main controller stays about the conversation; the dock owns Files,
Terminal, Changes, Context, Memory, Activity, Browser and Preview.

Three rules shape everything below:

* Nothing blocks the GUI thread. The shell is read from a socket notifier;
  Git runs on a worker; the file tree is loaded one level at a time.
* The dock never moves the panel the user is looking at. It may *open* itself
  and it may suggest a tab, but a tab the user selected by hand is theirs until
  they change it.
* Every path is proved to be inside the project before it reaches the UI.
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, Property, Qt, QSocketNotifier,
    QThread, QTimer, Signal, Slot,
)

from . import browser as browser_policy
from . import diffs
from . import project_files as files
from .activity import ActivityLog
from .terminal import ShellSession

TABS = ("files", "terminal", "changes", "context", "memory", "activity", "browser", "preview")

TAB_META = {
    "files":    {"label": "Files",    "icon": "folder",   "shortcut": "Ctrl+Shift+E"},
    "terminal": {"label": "Terminal", "icon": "terminal", "shortcut": "Ctrl+`"},
    "changes":  {"label": "Changes",  "icon": "branch",   "shortcut": "Ctrl+Shift+G"},
    "context":  {"label": "Context",  "icon": "layers",   "shortcut": "Ctrl+Shift+K"},
    "memory":   {"label": "Memory",   "icon": "memory",   "shortcut": "Ctrl+Shift+M"},
    "activity": {"label": "Activity", "icon": "bolt",     "shortcut": "Ctrl+Shift+A"},
    "browser":  {"label": "Browser",  "icon": "globe",    "shortcut": "Ctrl+Shift+W"},
    "preview":  {"label": "Preview",  "icon": "image",    "shortcut": "Ctrl+Shift+U"},
}

MIN_WIDTH = 280
MAX_WIDTH = 900
DEFAULT_WIDTH = 380


# A worker that outlives its owner is parked here rather than freed. Deleting a
# QThread while its `run` is still on the stack is a crash, and a Git call that
# has not returned yet is exactly when shutdown happens.
_ORPHANED: set = set()


class _Worker(QThread):
    """One-shot background call. Git and directory walks use this."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as exc:                      # pragma: no cover - defensive
            self.failed.emit(str(exc))


# ---------------------------------------------------------------- file tree
class FileTree(QAbstractListModel):
    """A flattened, lazily expanded directory tree.

    Flat because a ListView can virtualise it; lazy because a project is not a
    thing you read all of. Expanding a folder splices its children in after it.
    """

    NAME, PATH, DEPTH, IS_DIR, EXPANDED, KIND, SIZE, LOADING, SELECTED, DIRTY = (
        Qt.UserRole + i for i in range(1, 11))

    ROLES = {NAME: b"name", PATH: b"path", DEPTH: b"depth", IS_DIR: b"isDir",
             EXPANDED: b"expanded", KIND: b"kind", SIZE: b"sizeLabel",
             LOADING: b"loading", SELECTED: b"selected", DIRTY: b"dirty"}

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self._root = ""
        self._expanded: set[str] = set()
        self._selected = ""
        self._show_hidden = False
        self._dirty: set[str] = set()
        self._error = ""

    def roleNames(self):
        return self.ROLES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == self.SELECTED:
            return row["path"] == self._selected
        if role == self.DIRTY:
            return row["path"] in self._dirty
        if role == self.EXPANDED:
            return row["path"] in self._expanded
        return row.get(self.ROLES.get(role, b"").decode(), "")

    # ---------------------------------------------------------------- state
    @property
    def root(self) -> str:
        return self._root

    @property
    def error(self) -> str:
        return self._error

    def set_show_hidden(self, value: bool) -> None:
        if bool(value) == self._show_hidden:
            return
        self._show_hidden = bool(value)
        self.reload()

    @property
    def show_hidden(self) -> bool:
        return self._show_hidden

    def set_selected(self, path: str) -> None:
        if path == self._selected:
            return
        self._selected = str(path or "")
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1),
                                  [self.SELECTED])

    def set_dirty(self, paths) -> None:
        """Mark the files Git reports as changed, so the tree shows them."""
        fresh = {str(path) for path in paths}
        if fresh == self._dirty:
            return
        self._dirty = fresh
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1),
                                  [self.DIRTY])

    # ----------------------------------------------------------- structure
    def set_root(self, root: str) -> None:
        root = str(root or "")
        if root == self._root:
            return
        self._root = root
        self._expanded.clear()
        self._selected = ""
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self._rows = []
        self._error = ""
        if self._root:
            try:
                self._rows = self._level(self._root, 0)
            except (OSError, ValueError) as exc:
                self._error = files.explain(exc, "This project folder")
        self.endResetModel()
        self.changed.emit()

    def _level(self, directory: str, depth: int) -> list[dict]:
        entries = files.list_directory(self._root, directory, self._show_hidden)
        rows = []
        for entry in entries:
            row = dict(entry)
            row["depth"] = depth
            row["loading"] = False
            rows.append(row)
            if row["isDir"] and row["path"] in self._expanded:
                try:
                    rows.extend(self._level(row["path"], depth + 1))
                except (OSError, ValueError):
                    self._expanded.discard(row["path"])
        return rows

    def _index_of(self, path: str) -> int:
        for position, row in enumerate(self._rows):
            if row["path"] == path:
                return position
        return -1

    def toggle(self, path: str) -> None:
        position = self._index_of(path)
        if position < 0 or not self._rows[position]["isDir"]:
            return
        if path in self._expanded:
            self.collapse(path, position)
        else:
            self.expand(path, position)

    def expand(self, path: str, position: int = -1) -> None:
        position = position if position >= 0 else self._index_of(path)
        if position < 0 or path in self._expanded:
            return
        depth = self._rows[position]["depth"]
        try:
            children = self._level(path, depth + 1)
        except (OSError, ValueError) as exc:
            self._error = files.explain(exc, "That folder")
            self.changed.emit()
            return
        self._expanded.add(path)
        if children:
            self.beginInsertRows(QModelIndex(), position + 1, position + len(children))
            self._rows[position + 1:position + 1] = children
            self.endInsertRows()
        self.dataChanged.emit(self.index(position), self.index(position), [self.EXPANDED])
        self.changed.emit()

    def collapse(self, path: str, position: int = -1) -> None:
        position = position if position >= 0 else self._index_of(path)
        if position < 0 or path not in self._expanded:
            return
        depth = self._rows[position]["depth"]
        last = position
        while last + 1 < len(self._rows) and self._rows[last + 1]["depth"] > depth:
            self._expanded.discard(self._rows[last + 1]["path"])
            last += 1
        self._expanded.discard(path)
        if last > position:
            self.beginRemoveRows(QModelIndex(), position + 1, last)
            del self._rows[position + 1:last + 1]
            self.endRemoveRows()
        self.dataChanged.emit(self.index(position), self.index(position), [self.EXPANDED])
        self.changed.emit()

    def reveal(self, path: str) -> int:
        """Expand every ancestor of `path` and return its row, or -1."""
        if not self._root or not path:
            return -1
        try:
            target = files.resolve_within(self._root, path)
        except (OSError, ValueError):
            return -1
        base = Path(self._root).resolve()
        try:
            parts = target.relative_to(base).parts
        except ValueError:
            return -1
        current = base
        for part in parts[:-1]:
            current = current / part
            self.expand(str(current))
        return self._index_of(str(target))


# ------------------------------------------------------------- terminal view
class TerminalLines(QAbstractListModel):
    """Terminal scrollback as pre-rendered StyledText rows.

    Colour is resolved in Python against a palette QML pushes down, the same
    way code highlighting already works, so the view stays a plain ListView of
    Text items rather than a nest of per-span Repeaters.
    """

    HTML, TEXT = Qt.UserRole + 1, Qt.UserRole + 2
    ROLES = {HTML: b"html", TEXT: b"text"}

    DEFAULT_PALETTE = {
        "text": "#d6d5d0", "black": "#5a5a55", "red": "#e58b7c", "green": "#84c98f",
        "yellow": "#d9b06a", "blue": "#8fb3e0", "magenta": "#c9a3e8", "cyan": "#83c9c2",
        "white": "#d6d5d0", "brightBlack": "#8b8b85", "brightRed": "#f0a294",
        "brightGreen": "#9ad9a4", "brightYellow": "#e8c583", "brightBlue": "#a6c4ec",
        "brightMagenta": "#d8b8f0", "brightCyan": "#9adad3", "brightWhite": "#f2f2ee",
        "dim": "#8b8b85",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self.palette = dict(self.DEFAULT_PALETTE)

    def roleNames(self):
        return self.ROLES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()].get(self.ROLES.get(role, b"").decode(), "")

    def set_palette(self, palette: dict) -> None:
        for key, value in (palette or {}).items():
            if key in self.palette and isinstance(value, str) and value.startswith("#"):
                self.palette[key] = value

    def _render(self, spans: list[dict]) -> str:
        if not spans:
            return ""
        pieces = []
        for span in spans:
            text = html.escape(span.get("text", "")).replace(" ", "&nbsp;")
            if not text:
                continue
            colour = ""
            name = span.get("fg", "")
            if span.get("inverse"):
                colour = self.palette.get("brightWhite", "")
            elif name:
                if span.get("bold") and not name.startswith("bright"):
                    name = "bright" + name.capitalize()
                colour = self.palette.get(name, "")
            elif span.get("dim"):
                colour = self.palette.get("dim", "")
            styles = []
            if colour:
                styles.append(f"color:{colour}")
            fragment = text
            if span.get("bold"):
                fragment = f"<b>{fragment}</b>"
            if span.get("italic"):
                fragment = f"<i>{fragment}</i>"
            if span.get("underline"):
                fragment = f"<u>{fragment}</u>"
            if styles:
                fragment = f'<span style="{";".join(styles)}">{fragment}</span>'
            pieces.append(fragment)
        return "".join(pieces)

    def sync(self, rows: list[dict]) -> None:
        """Reconcile against fresh scrollback without resetting the view."""
        rendered = [{"html": self._render(row["spans"]), "text": row["text"]}
                    for row in rows]
        common = min(len(rendered), len(self._rows))
        first_change = -1
        for position in range(common):
            if rendered[position] != self._rows[position]:
                first_change = position
                break
        if len(rendered) < len(self._rows):
            self.beginRemoveRows(QModelIndex(), len(rendered), len(self._rows) - 1)
            del self._rows[len(rendered):]
            self.endRemoveRows()
        if first_change >= 0:
            end = min(len(rendered), len(self._rows))
            self._rows[first_change:end] = rendered[first_change:end]
            self.dataChanged.emit(self.index(first_change), self.index(end - 1),
                                  [self.HTML, self.TEXT])
        if len(rendered) > len(self._rows):
            start = len(self._rows)
            self.beginInsertRows(QModelIndex(), start, len(rendered) - 1)
            self._rows.extend(rendered[start:])
            self.endInsertRows()

    def clear(self) -> None:
        if not self._rows:
            return
        self.beginResetModel()
        self._rows = []
        self.endResetModel()


# ------------------------------------------------------------------ the dock
class DockController(QObject):
    """Everything the right-hand workspace needs, and nothing else."""

    changed = Signal()
    filesChanged = Signal()
    viewerChanged = Signal()
    terminalChanged = Signal()
    changesChanged = Signal()
    contextChanged = Signal()
    activityChanged = Signal()
    browserChanged = Signal()
    previewChanged = Signal()
    revealRow = Signal(int)
    toast = Signal(str)

    def __init__(self, store=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._owner = parent
        setting = store.get_setting if store else (lambda key, default=None: default)

        self._visible = bool(setting("dock_visible", False))
        self._width = max(MIN_WIDTH, min(int(setting("dock_width", DEFAULT_WIDTH) or DEFAULT_WIDTH), MAX_WIDTH))
        tab = str(setting("dock_tab", "files") or "files")
        self._tab = tab if tab in TABS else "files"
        # Set the moment the user clicks a tab. While it is set, nothing in the
        # app is allowed to change the visible panel underneath them.
        self._tab_pinned = bool(setting("dock_tab_pinned", False))
        self._project = ""

        self.tree = FileTree(self)
        self.tree.set_show_hidden(bool(setting("dock_show_hidden", False)))
        self.tree.changed.connect(self.filesChanged)
        self._file_filter = ""
        self._search_results: list[dict] = []

        self._viewer: dict = {}
        self._viewer_buffer = ""
        self._viewer_dirty = False

        self.lines = TerminalLines(self)
        self._shell: ShellSession | None = None
        self._notifier: QSocketNotifier | None = None
        self._shell_cwd = ""
        self._shell_error = ""
        self._terminal_started = False

        self._changes: dict = {"repository": False, "branch": "", "files": [],
                               "added": 0, "removed": 0, "error": ""}
        self._change_path = ""
        self._diff: dict = {"rows": [], "error": "", "path": "", "binary": False}
        self._changes_busy = False
        self._workers: set[_Worker] = set()

        self.log = ActivityLog()
        self._activity_revision = -1

        self._browser_url = ""
        self._browser_pending = ""
        self._browser_title = ""
        self._browser_loading = False
        self._browser_progress = 0.0
        self._browser_can_back = False
        self._browser_can_forward = False
        self._browser_error = ""

        self._preview: dict = {}

        # One cheap poll while the terminal is on screen keeps the header's
        # working directory honest without a timer per panel.
        self._poll = QTimer(self)
        self._poll.setInterval(1500)
        self._poll.timeout.connect(self._poll_shell)

    # ------------------------------------------------------------ shell state
    @Property(bool, notify=changed)
    def visible(self):
        return self._visible

    @Property(int, notify=changed)
    def width(self):
        return self._width

    @Property(str, notify=changed)
    def tab(self):
        return self._tab

    @Property("QVariantList", constant=True)
    def tabs(self):
        return [{"id": name, **TAB_META[name]} for name in TABS]

    @Property(int, constant=True)
    def minimumWidth(self):
        return MIN_WIDTH

    @Property(int, constant=True)
    def maximumWidth(self):
        return MAX_WIDTH

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

    # ----------------------------------------------------------- the project
    @Property(str, notify=changed)
    def projectPath(self):
        return self._project

    @Property(str, notify=changed)
    def projectName(self):
        return Path(self._project).name if self._project else ""

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

    # ---------------------------------------------------------------- files
    @Property(QObject, constant=True)
    def fileModel(self):
        return self.tree

    @Property(bool, notify=filesChanged)
    def showHidden(self):
        return self.tree.show_hidden

    @Property(str, notify=filesChanged)
    def fileFilter(self):
        return self._file_filter

    @Property("QVariantList", notify=filesChanged)
    def fileMatches(self):
        return self._search_results

    @Property(str, notify=filesChanged)
    def fileError(self):
        return self.tree.error

    @Slot(bool)
    def setShowHidden(self, value):
        self.tree.set_show_hidden(bool(value))
        self._remember("dock_show_hidden", bool(value))
        self.filesChanged.emit()

    @Slot(str)
    def setFileFilter(self, text):
        text = str(text or "")
        if text == self._file_filter:
            return
        self._file_filter = text
        needle = text.strip()
        if len(needle) < 2 or not self._project:
            self._search_results = []
        else:
            try:
                self._search_results = files.search_tree(
                    self._project, needle, limit=120, show_hidden=self.tree.show_hidden)
            except (OSError, ValueError):
                self._search_results = []
        self.filesChanged.emit()

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

    # --------------------------------------------------------- file viewer
    @Property("QVariantMap", notify=viewerChanged)
    def file(self):
        return dict(self._viewer)

    @Property(str, notify=viewerChanged)
    def filePath(self):
        return str(self._viewer.get("path", ""))

    @Property(bool, notify=viewerChanged)
    def fileModified(self):
        return self._viewer_dirty

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

    # -------------------------------------------------------------- terminal
    @Property(QObject, constant=True)
    def terminalModel(self):
        return self.lines

    @Property(bool, notify=terminalChanged)
    def terminalRunning(self):
        return bool(self._shell and self._shell.running)

    @Property(str, notify=terminalChanged)
    def terminalShell(self):
        return self._shell.shell_name if self._shell else ""

    @Property(str, notify=terminalChanged)
    def terminalDirectory(self):
        return self._shell_cwd

    @Property(str, notify=terminalChanged)
    def terminalDirectoryLabel(self):
        path = self._shell_cwd or self._project
        if not path:
            return ""
        try:
            home = str(Path.home())
            return "~" + path[len(home):] if path.startswith(home) else path
        except (OSError, RuntimeError):
            return path

    @Property(str, notify=terminalChanged)
    def terminalError(self):
        return self._shell_error

    @Property(bool, notify=terminalChanged)
    def terminalStarted(self):
        return self._terminal_started

    @Slot("QVariantMap")
    def setTerminalPalette(self, palette):
        self.lines.set_palette(dict(palette or {}))
        if self._shell is not None:
            self.lines.sync(self._shell.screen.rows())

    @Slot()
    def startTerminal(self):
        if self._shell is not None and self._shell.running:
            return
        self._teardown_shell()
        session = ShellSession(cwd=self._project or str(Path.home()))
        try:
            session.start()
        except Exception as exc:
            self._shell_error = f"Could not start a shell: {exc}"
            self._terminal_started = True
            self.terminalChanged.emit()
            return
        self._shell = session
        self._shell_error = ""
        self._shell_cwd = session.cwd
        self._terminal_started = True
        self._notifier = QSocketNotifier(session.fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._drain_shell)
        self.terminalChanged.emit()

    @Slot()
    def restartTerminal(self):
        self._teardown_shell()
        self.lines.clear()
        self._terminal_started = False
        self.terminalChanged.emit()
        if self._visible and self._tab == "terminal":
            self.startTerminal()

    def _teardown_shell(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self._shell is not None:
            self._shell.stop()
            self._shell = None

    def _drain_shell(self, *_):
        if self._shell is None:
            return
        produced = self._shell.read()
        if produced:
            self.lines.sync(self._shell.screen.rows())
        if not self._shell.running:
            if self._notifier is not None:
                self._notifier.setEnabled(False)
            self.terminalChanged.emit()

    def _poll_shell(self):
        if self._shell is None or not self._shell.running:
            return
        directory = self._shell.working_directory()
        if directory != self._shell_cwd:
            self._shell_cwd = directory
            self.terminalChanged.emit()

    @Slot(str)
    def sendTerminal(self, text):
        if self._shell is None or not self._shell.running:
            self.startTerminal()
        if self._shell is None:
            return
        self._shell.send_line(str(text))

    @Slot(str)
    def writeTerminal(self, text):
        if self._shell is not None:
            self._shell.write(str(text))

    @Slot(str)
    def runInTerminal(self, command):
        """Show a command in the terminal and run it there, opening the panel.

        Called from a menu the user opened, so it uses `openTab` rather than
        `suggest`: a suggestion is refused once a tab has been chosen by hand,
        and refusing to honour a click would be the wrong kind of consistent.
        """
        command = str(command or "").strip()
        if not command:
            return
        if self._tab != "terminal" or not self._visible:
            self._tab_pinned = True
            self._remember("dock_tab_pinned", True)
            self._select_tab("terminal")
            self.setVisible(True)
            self.changed.emit()
        self.startTerminal()
        self.sendTerminal(command)

    @Slot()
    def interruptTerminal(self):
        if self._shell is not None:
            self._shell.interrupt()

    @Slot()
    def clearTerminal(self):
        if self._shell is not None:
            self._shell.screen.clear()
        self.lines.clear()

    @Slot(result=str)
    def terminalText(self):
        return self._shell.screen.plain_text() if self._shell else ""

    @Slot(int, int)
    def resizeTerminal(self, columns, rows):
        if self._shell is not None:
            self._shell.resize(columns, rows)

    # --------------------------------------------------------------- changes
    @Property("QVariantList", notify=changesChanged)
    def changes(self):
        return self._changes.get("files", [])

    @Property(bool, notify=changesChanged)
    def isRepository(self):
        return bool(self._changes.get("repository"))

    @Property(str, notify=changesChanged)
    def branch(self):
        return str(self._changes.get("branch", ""))

    @Property(str, notify=changesChanged)
    def changesSummary(self):
        entries = self._changes.get("files", [])
        if not entries:
            return "No uncommitted changes"
        count = f"{len(entries)} file" + ("" if len(entries) == 1 else "s")
        return f"{count} · +{self._changes.get('added', 0)} −{self._changes.get('removed', 0)}"

    @Property(str, notify=changesChanged)
    def changesError(self):
        return str(self._changes.get("error", ""))

    @Property(bool, notify=changesChanged)
    def changesBusy(self):
        return self._changes_busy

    @Property(str, notify=changesChanged)
    def diffPath(self):
        return self._change_path

    @Property("QVariantList", notify=changesChanged)
    def diffRows(self):
        return self._diff.get("rows", [])

    @Property(str, notify=changesChanged)
    def diffError(self):
        return str(self._diff.get("error", ""))

    def _run(self, fn, done):
        """Run `fn` off the GUI thread and hand its result to `done`.

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
        worker.finished.connect(self._retire_worker)
        self._workers.add(worker)
        worker.start()
        return worker

    @Slot(object)
    def _deliver(self, payload):
        callback = getattr(self.sender(), "callback", None)
        if callable(callback):
            callback(payload)

    @Slot(str)
    def _deliver_failure(self, message):
        self.toast.emit(message)

    @Slot()
    def _retire_worker(self):
        worker = self.sender()
        self._workers.discard(worker)
        if worker is not None:
            worker.deleteLater()

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

    # --------------------------------------------------------------- context
    @Property("QVariantList", notify=contextChanged)
    def contextItems(self):
        """What the model can currently see, grouped for the Context panel.

        Composed from the controller's real state — attachments, the project,
        the open file, the browser — rather than a second store that could
        disagree with the composer.
        """
        groups: list[dict] = []
        owner = self._owner

        if self._project:
            groups.append({"title": "Workspace", "icon": "folderOpen", "items": [{
                "id": "project", "label": Path(self._project).name,
                "detail": self._project, "removable": False, "kind": "folder",
            }]})

        attachments = list(getattr(owner, "_attachments", []) or []) if owner else []
        if attachments:
            groups.append({"title": "Attached", "icon": "paperclip", "items": [{
                "id": "attachment:" + str(item.get("id", "")),
                "label": str(item.get("title", "")),
                "detail": str(item.get("subtitle", "")),
                "removable": True,
                "kind": str(item.get("kind", "file")),
                "tokens": int(item.get("tokens", 0) or 0),
            } for item in attachments]})

        if self._viewer.get("path"):
            groups.append({"title": "Open file", "icon": "file", "items": [{
                "id": "file", "label": self._viewer.get("name", ""),
                "detail": self._viewer.get("relative", ""),
                "removable": True, "kind": "file",
                "tokens": 0,
            }]})

        if self._browser_url:
            groups.append({"title": "Browser", "icon": "globe", "items": [{
                "id": "browser", "label": self._browser_title or browser_policy.display_url(self._browser_url),
                "detail": browser_policy.display_url(self._browser_url),
                "removable": True, "kind": "link",
            }]})

        changed = self._changes.get("files", [])
        if changed:
            groups.append({"title": "Changed files", "icon": "branch", "items": [{
                "id": "change:" + entry["path"], "label": entry["name"],
                "detail": f"+{entry['added']} −{entry['removed']}",
                "removable": False, "kind": "diff",
            } for entry in changed[:12]]})

        return groups

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

    # -------------------------------------------------------------- activity
    @Property("QVariantList", notify=activityChanged)
    def activityRows(self):
        return self.log.rows()

    @Property(str, notify=activityChanged)
    def activitySummary(self):
        return self.log.summary()

    @Property(bool, notify=activityChanged)
    def activityRunning(self):
        return self.log.running

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

    # --------------------------------------------------------------- browser
    @Property(bool, constant=True)
    def browserAvailable(self):
        return browser_policy.engine_available()

    @Property(str, constant=True)
    def browserUnavailableReason(self):
        return browser_policy.unavailable_reason()

    @Property(str, constant=True)
    def browserHome(self):
        return browser_policy.DEFAULT_HOME

    @Property(str, notify=browserChanged)
    def browserUrl(self):
        return self._browser_url

    @Property(str, notify=browserChanged)
    def browserRequest(self):
        return self._browser_pending

    @Property(str, notify=browserChanged)
    def browserDisplayUrl(self):
        return browser_policy.display_url(self._browser_url)

    @Property(str, notify=browserChanged)
    def browserTitle(self):
        return self._browser_title

    @Property(bool, notify=browserChanged)
    def browserLoading(self):
        return self._browser_loading

    @Property(float, notify=browserChanged)
    def browserProgress(self):
        return self._browser_progress

    @Property(bool, notify=browserChanged)
    def browserSecure(self):
        return browser_policy.is_secure(self._browser_url)

    @Property(str, notify=browserChanged)
    def browserTrust(self):
        """"secure", "local" or "insecure" — what the address bar's mark means."""
        if not self._browser_url:
            return ""
        if browser_policy.is_secure(self._browser_url):
            return "secure"
        return "local" if browser_policy.is_local(self._browser_url) else "insecure"

    @Property(str, notify=browserChanged)
    def browserError(self):
        return self._browser_error

    @Slot(str, result=bool)
    def navigate(self, text):
        target = browser_policy.normalize(text)
        if not target:
            self._browser_error = "That is not an address Wynxo can open"
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

    @Property(bool, notify=browserChanged)
    def browserCanGoBack(self):
        return self._browser_can_back

    @Property(bool, notify=browserChanged)
    def browserCanGoForward(self):
        return self._browser_can_forward

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

    # --------------------------------------------------------------- preview
    @Property("QVariantMap", notify=previewChanged)
    def preview(self):
        return dict(self._preview)

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

    # ------------------------------------------------------------- lifecycle
    def shutdown(self) -> None:
        """Tear down without leaving anything queued at a dead receiver.

        A worker that has finished may still have its `finished` signal waiting
        for an event loop that will never run again. Cutting the connections
        here — rather than trusting `deleteLater` — is what makes shutdown safe
        from a controller that is about to be freed.
        """
        self._poll.stop()
        self._teardown_shell()
        for worker in list(self._workers):
            # `quit` only ends a thread that runs an event loop; these do not,
            # so the wait is what matters. Git's own timeout bounds it.
            worker.quit()
            finished = worker.wait(2000)
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
