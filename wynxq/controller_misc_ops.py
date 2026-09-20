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

@Slot(str, result=str)
def renderMarkdown(self, text):
    """Prose rendered to the HTML subset Qt's rich text engine supports."""
    return md.to_html(str(text), self._html_palette)


@staticmethod
def _palette_hex(palette) -> dict:
    """QML hands colours over as QColor; the renderers want hex strings."""
    out = {}
    for key, value in dict(palette).items():
        if isinstance(value, QColor):
            out[str(key)] = value.name(QColor.HexRgb)
        else:
            colour = QColor(str(value))
            out[str(key)] = colour.name(QColor.HexRgb) if colour.isValid() else str(value)
    return out


@Slot("QVariantMap")
def setHtmlPalette(self, palette):
    self._html_palette = {**md.HTML_PALETTE, **self._palette_hex(palette)}
    self.paletteChanged.emit()


@Slot(str, str, result=str)
def highlight(self, code, language):
    """Rich text for a finished code block, coloured from the UI palette."""
    return md.highlight(str(code), str(language), self._code_palette)


@Slot("QVariantMap")
def setCodePalette(self, palette):
    self._code_palette = {**md.DEFAULT_PALETTE, **self._palette_hex(palette)}
    self.paletteChanged.emit()


@Slot(str)
def copyText(self, text):
    QGuiApplication.clipboard().setText(str(text))
    self.toast.emit("Copied to clipboard")


@Slot(str, str)
def saveCode(self, text, language):
    from PySide6.QtWidgets import QFileDialog
    suffix = {"python": ".py", "javascript": ".js", "typescript": ".ts", "shell": ".sh",
              "json": ".json", "yaml": ".yaml", "css": ".css", "html": ".html",
              "sql": ".sql", "go": ".go", "rust": ".rs", "java": ".java",
              "c": ".c", "cpp": ".cpp"}.get(md.normalise_language(language), ".txt")
    start = str(Path(self._working_directory or ctx.default_directory()) / f"wynxq-snippet{suffix}")
    target, _ = QFileDialog.getSaveFileName(None, "Save snippet", start)
    if not target:
        return
    try:
        Path(target).write_text(str(text), encoding="utf-8")
        self.toast.emit(f"Saved to {Path(target).name}")
    except OSError as exc:
        self._set_error("The snippet could not be saved", str(exc))


@Slot(str)
def copyAndOpenTerminal(self, text):
    """Wynxq never executes model output; it hands it to the user's terminal."""
    QGuiApplication.clipboard().setText(str(text))
    if notify.open_terminal(self._working_directory or str(Path.home())):
        self.toast.emit("Command copied — paste it in the terminal to run it")
    else:
        self.toast.emit("Command copied. No terminal emulator was found.")


@Slot()
def exportTask(self):
    if not self._task_id:
        return
    from PySide6.QtWidgets import QFileDialog
    default = f"{self._task_title[:60].strip() or 'wynxq-chat'}.md".replace("/", "-")
    target, _ = QFileDialog.getSaveFileName(None, "Export conversation", default, "Markdown (*.md)")
    if not target:
        return
    lines = [f"# {self._task_title}", "", f"*Exported from Wynxq · model {self._model}*", ""]
    for item in self.messages.items:
        if item["kind"] == "activity":
            lines.append("### Desktop actions")
            for step in item["steps"]:
                mark = {"done": "✓", "failed": "✗", "declined": "–"}.get(step["state"], "•")
                lines.append(f"- {mark} {step.get('summary') or step['label']}")
            lines.append("")
            continue
        lines.append(f"## {'You' if item['kind'] == 'user' else 'Wynxq'}")
        lines.append("")
        if item.get("thought"):
            lines += ["<details>", "<summary>Reasoning</summary>", "", item["thought"], "", "</details>", ""]
        lines += [item["body"], ""]
    try:
        Path(target).write_text("\n".join(lines), encoding="utf-8")
        self.toast.emit("Conversation exported")
    except OSError as exc:
        self._set_error("The conversation could not be exported", str(exc))


@Slot()
def clearError(self):
    self._clear_error()
    self.changed.emit()


def _clear_error(self):
    self._error = ""
    self._error_title = ""
    self._error_actions = []


def _set_error(self, title, detail="", actions=None):
    self._error_title = str(title)
    self._error = str(detail or title)
    self._error_actions = list(actions or [])
    self.changed.emit()


def _show_error(self, message):
    self._set_error("Something went wrong", message)


def _release_all_permission_waits(self) -> None:
    """Fail closed and wake every run before cancellation or process exit."""
    for state in self._run_sessions.values():
        if state.get("permission") is not None:
            state["permission_answer"] = False
            event = state.get("permission_event")
            if event is not None:
                event.set()
    if self._pending_permission is not None:
        self._permission_answer = False
        self._permission_event.set()


@Slot(result=bool)
def canClose(self):
    self._release_all_permission_waits()
    if self._jobs:
        for job in self._jobs:
            job.cancel.set()
        self._status = "Stopping background work…"
        self.changed.emit()
        return False
    return True


def shutdown(self):
    self._overlay_visible = False
    self.dock.shutdown()
    self._release_all_permission_waits()
    for job in list(self._jobs):
        job.cancel.set()
    for job in list(self._jobs):
        job.wait(2000)
    self.desktop.disconnect()
