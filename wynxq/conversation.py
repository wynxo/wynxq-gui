"""Conversation presentation model and task-list grouping helpers.

This module owns the data shape exposed to QML for a conversation. Keeping it
separate from :mod:`wynxq.controller` prevents the application coordinator
from also being the transcript model, while preserving controller-level imports
for compatibility.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from . import context as ctx
from . import markdown as md
from .agent_tools import action_summary


def derive_title(text: str, limit: int = 52) -> str:
    """Name a chat from its first message, cutting on a word boundary."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "New task"
    if len(cleaned) <= limit:
        return cleaned.rstrip(" .,;:!?-")
    cut = cleaned[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" .,;:!?-") + "…"


def group_for(timestamp: float, now: float | None = None) -> str:
    """Bucket a conversation into the sidebar's date sections."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    day = datetime.fromtimestamp(timestamp).date()
    if day >= today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if day > today - timedelta(days=8):
        return "Previous 7 days"
    if day > today - timedelta(days=31):
        return "Previous 30 days"
    return "Older"


GROUP_ORDER = ["Pinned", "Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]

# Tool name -> the icon and verb shown in the inline activity timeline.
TOOL_PRESENTATION = {
    "screenshot": ("eye", "Inspecting the screen"),
    "list_apps": ("grid", "Listing installed apps"),
    "open_app": ("launch", "Opening an application"),
    "browser_open": ("globe", "Opening in Wynxq Browser"),
    "run_command": ("terminal", "Running a command"),
    "click": ("cursor", "Clicking"),
    "move_pointer": ("cursor", "Moving the pointer"),
    "drag": ("paint", "Dragging"),
    "type_text": ("keyboard", "Typing"),
    "press_key": ("keyboard", "Pressing keys"),
    "hold_key": ("keyboard", "Holding keys"),
    "hold_button": ("cursor", "Holding a mouse button"),
    "scroll": ("scroll", "Scrolling"),
    "wait": ("clock", "Waiting"),
    "remember": ("memory", "Saving to memory"),
    "forget": ("memory", "Forgetting a note"),
}

STARTERS = [
    {"title": "Open an app", "icon": "launch", "prompt": "Open KCalc for me."},
    {"title": "Run a command", "icon": "terminal", "prompt": "Check my disk space and explain what you find."},
    {"title": "Help me code", "icon": "code", "prompt": "Inspect this project and help me understand how it works."},
    {"title": "Read my screen", "icon": "eye", "prompt": "What is on my screen? Help me with it."},
]


class Messages(QAbstractListModel):
    """Conversation rows: user turns, assistant turns, and activity groups.

    Assistant text is segmented incrementally (see :mod:`wynxq.markdown`) so a
    streaming response only rewrites the block that is still open.
    """

    KIND, BODY, THOUGHT, BLOCKS, TAIL, TAIL_KIND, TAIL_LANG, TAIL_LABEL, \
        STEPS, STREAMING, THINK_SECONDS, THINK_DONE, ATTACHMENTS = \
        (Qt.UserRole + i for i in range(1, 14))

    ROLES = {
        KIND: b"kind", BODY: b"body", THOUGHT: b"thought", BLOCKS: b"blocks",
        TAIL: b"tail", TAIL_KIND: b"tailKind", TAIL_LANG: b"tailLanguage",
        TAIL_LABEL: b"tailLabel", STEPS: b"steps", STREAMING: b"streaming",
        THINK_SECONDS: b"thinkSeconds", THINK_DONE: b"thinkDone",
        ATTACHMENTS: b"attachments",
    }
    # Compatibility alias: "speaker" mirrors "kind" for user/assistant rows.
    ROLES[Qt.UserRole + 20] = b"speaker"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[dict] = []
        self._documents: dict[int, md.StreamingDocument] = {}

    def roleNames(self):
        return self.ROLES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.UserRole + 20:
            return item.get("kind", "")
        return item.get(self.ROLES.get(role, b"").decode(), "")

    def _emit(self, row: int, roles: list) -> None:
        index = self.index(row)
        self.dataChanged.emit(index, index, roles)

    @staticmethod
    def _row(kind: str, **fields) -> dict:
        row = {"kind": kind, "speaker": kind, "body": "", "thought": "", "blocks": [],
               "tail": "", "tailKind": md.MARKDOWN, "tailLanguage": "", "tailLabel": "",
               "steps": [], "streaming": False, "thinkSeconds": 0.0, "thinkDone": False,
               "attachments": []}
        row.update(fields)
        return row

    @staticmethod
    def context_step(message: dict) -> dict:
        return {"name": "context", "icon": "paperclip", "label": "Context attached",
                "summary": ctx.context_message_label(message), "detail": "",
                "state": "done", "ms": 0, "output": ""}

    def replace(self, messages):
        """Rebuild the view from stored history.

        Tool results become activity groups and attached context folds into a
        chip, so reopening a chat never dumps a whole file back into the
        transcript as if the user had typed it.
        """
        self.beginResetModel()
        self.items = []
        self._documents = {}
        pending_steps: list[dict] = []
        pending_attachments: list[dict] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                pending_steps.append(self._stored_step(message))
                continue
            if ctx.is_context_message(message):
                pending_attachments.extend(ctx.context_message_attachments(message))
                continue
            if pending_steps:
                self.items.append(self._row("activity", steps=pending_steps))
                pending_steps = []
            if role not in ("user", "assistant"):
                continue
            if message.get("images") and str(message.get("content", "")).startswith("Current desktop screenshot ("):
                continue
            body, thought = message.get("content", ""), message.get("thinking", "")
            if not body and not thought:
                continue
            row = self._row(role, body=body, thought=thought, thinkDone=bool(thought),
                            blocks=md.segment(body) if role == "assistant" else [],
                            attachments=list(pending_attachments) if role == "user" else [])
            self.items.append(row)
            if role == "user":
                pending_attachments = []
        if pending_steps:
            self.items.append(self._row("activity", steps=pending_steps))
        self.endResetModel()

    @staticmethod
    def _stored_step(message: dict) -> dict:
        name = message.get("tool_name", "action")
        icon, label = TOOL_PRESENTATION.get(name, ("bolt", name.replace("_", " ").capitalize()))
        try:
            result = json.loads(message.get("content", "{}"))
        except (ValueError, TypeError):
            result = {}
        if not isinstance(result, dict):
            result = {}
        failed = bool(result.get("error")) or result.get("ok") is False
        summary = action_summary(name, result) if name in {"run_command", "open_app"} else ""
        return {"name": name, "icon": icon, "label": label, "summary": summary,
                "detail": str(result.get("error") or "")[:200],
                "state": "declined" if result.get("declined") else ("failed" if failed else "done"),
                "ms": 0, "output": str(result.get("output") or result.get("error") or "")[:32000]}

    def append_message(self, kind: str, body: str = "", thought: str = "", streaming: bool = False,
                       attachments: list[dict] | None = None) -> int:
        row = len(self.items)
        self.beginInsertRows(QModelIndex(), row, row)
        item = self._row(kind, body=body, thought=thought, streaming=streaming,
                         attachments=list(attachments or []))
        if kind == "assistant":
            document = md.StreamingDocument()
            if body:
                document.append(body)
                item["blocks"] = document.blocks
                item["tail"] = document.tail
            self._documents[row] = document
        elif body:
            item["blocks"] = []
        self.items.append(item)
        self.endInsertRows()
        return row

    def append_activity(self, step: dict) -> int:
        """Add a step, reusing the trailing activity group when there is one."""
        if self.items and self.items[-1]["kind"] == "activity":
            row = len(self.items) - 1
            self.items[row]["steps"] = self.items[row]["steps"] + [step]
            self._emit(row, [self.STEPS])
            return row
        row = len(self.items)
        self.beginInsertRows(QModelIndex(), row, row)
        self.items.append(self._row("activity", steps=[step]))
        self.endInsertRows()
        return row

    def update_last_step(self, **fields) -> None:
        for row in range(len(self.items) - 1, -1, -1):
            if self.items[row]["kind"] != "activity":
                return
            steps = list(self.items[row]["steps"])
            if not steps:
                return
            steps[-1] = {**steps[-1], **fields}
            self.items[row]["steps"] = steps
            self._emit(row, [self.STEPS])
            return

    def stream(self, field: str, text: str) -> None:
        if not self.items or self.items[-1]["kind"] != "assistant":
            self.append_message("assistant", streaming=True)
        row = len(self.items) - 1
        item = self.items[row]
        item[field] += text
        if field == "thought":
            self._emit(row, [self.THOUGHT])
            return
        document = self._documents.get(row)
        if document is None:
            document = self._documents[row] = md.StreamingDocument()
        before = len(document.blocks)
        document.append(text)
        item["tail"] = document.tail
        item["tailKind"] = document.tail_kind
        item["tailLanguage"] = document.tail_language
        item["tailLabel"] = document.tail_label
        roles = [self.BODY, self.TAIL, self.TAIL_KIND, self.TAIL_LANG, self.TAIL_LABEL]
        if len(document.blocks) != before:
            item["blocks"] = document.blocks
            roles.append(self.BLOCKS)
        self._emit(row, roles)

    def finish_stream(self, think_seconds: float = 0.0, final_message: dict | None = None) -> None:
        """Close the stream and reconcile it with Ollama's authoritative message."""
        if not self.items or self.items[-1]["kind"] != "assistant":
            return
        row = len(self.items) - 1
        item = self.items[row]
        roles = [self.BLOCKS, self.TAIL, self.STREAMING, self.THINK_SECONDS, self.THINK_DONE]
        if final_message is not None:
            item["body"] = str(final_message.get("content", "") or "")
            item["thought"] = str(final_message.get("thinking", "") or "")
            item["blocks"] = md.segment(item["body"])
            self._documents.pop(row, None)
            roles.extend([self.BODY, self.THOUGHT])
        else:
            document = self._documents.get(row)
            if document is not None:
                item["blocks"] = document.finish()
        item["tail"] = ""
        item["streaming"] = False
        item["thinkDone"] = bool(item["thought"])
        if think_seconds:
            item["thinkSeconds"] = round(think_seconds, 1)
        self._emit(row, roles)

    def mark_idle(self) -> None:
        for row, item in enumerate(self.items):
            if item.get("streaming"):
                item["streaming"] = False
                self._emit(row, [self.STREAMING])

    def message_indices(self) -> list[int]:
        """Row indices that correspond to real messages, newest last."""
        return [i for i, item in enumerate(self.items) if item["kind"] in ("user", "assistant")]

    # Legacy alias kept so existing callers and tests keep working.
    def append(self, speaker, body="", thought=""):
        return self.append_message(speaker, body, thought)


__all__ = [
    "GROUP_ORDER", "STARTERS", "TOOL_PRESENTATION", "Messages",
    "derive_title", "group_for",
]
