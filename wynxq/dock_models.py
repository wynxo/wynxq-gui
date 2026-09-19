"""Qt models and worker primitives used by the workspace dock.

The dock coordinator is intentionally kept separate from its list-model
implementations. This keeps file-tree and terminal rendering state testable
without growing :mod:`wynxq.dock` into another application-wide monolith.
"""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QThread, Signal

from . import project_files as files


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


__all__ = ["FileTree", "TerminalLines", "_ORPHANED", "_Worker"]
