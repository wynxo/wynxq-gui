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

def _matching_tasks(self) -> list[dict]:
    needle = self._search.strip().casefold()
    if not needle:
        return self._tasks
    if len(needle) >= self.DEEP_SEARCH_LENGTH:
        return self.store.search(needle, limit=max(1, len(self._tasks)))
    return [task for task in self._tasks
            if needle in str(task.get("title", "")).casefold()
            or needle in str(task.get("preview", "")).casefold()]


def _grouped_tasks(self) -> list[dict]:
    buckets: dict[str, list] = {}
    for raw in self._matching_tasks():
        task = dict(raw)
        session = self._run_sessions.get(str(task.get("id", "")))
        task["running"] = bool(session and session.get("busy"))
        task["runStatus"] = str(session.get("status", "")) if session else ""
        if session:
            task["model"] = session.get("model", task.get("model", ""))
            task["endpoint"] = session.get("endpoint", task.get("endpoint", ""))
        name = "Pinned" if task.get("pinned") else group_for(task.get("updated_at", 0))
        buckets.setdefault(name, []).append(task)
    return [{"title": name, "items": buckets[name]} for name in GROUP_ORDER if buckets.get(name)]


@Slot(str)
def setSearch(self, text):
    text = str(text or "")
    if text == self._search:
        return
    self._search = text
    self.tasksChanged.emit()


@Slot(int)
def openAdjacentTask(self, delta):
    """Move to the next or previous chat even while another one generates."""
    order = [item["id"] for group in self._grouped_tasks() for item in group["items"]]
    if not order:
        return
    if self._task_id not in order:
        self.openTask(order[0])
        return
    position = order.index(self._task_id) + int(delta)
    if 0 <= position < len(order):
        self.openTask(order[position])


def _active_session(self):
    return self._run_sessions.get(str(self._task_id or ""))


def _sync_active_session(self, session: dict | None) -> None:
    """Project one task-owned run onto the properties the shell reads."""
    if not session:
        self._busy = False
        self._run_job = None
        self._pending_permission = None
        self._session_auto = False
        return
    self.messages = session["messages"]
    self._history = session["history"]
    self._busy = bool(session.get("busy"))
    self._run_job = session.get("job")
    self._status = str(session.get("status", "Ready when you are"))
    self._token_rate = str(session.get("token_rate", "—"))
    self._run_metrics = dict(session.get("metrics") or _blank_metrics())
    self._activity = list(session.get("activity") or [])
    self._think_started = float(session.get("think_started", 0.0) or 0.0)
    self._think_seconds = float(session.get("think_seconds", 0.0) or 0.0)
    self._turn_had_message = bool(session.get("turn_had_message"))
    self._error = str(session.get("error", ""))
    self._error_title = str(session.get("error_title", ""))
    self._error_actions = list(session.get("error_actions") or [])
    self._pending_permission = session.get("permission")
    self._permission_event = session.get("permission_event", threading.Event())
    self._permission_answer = bool(session.get("permission_answer", False))
    self._session_auto = bool(session.get("session_auto", False))


def _new_message_model(self, history=None):
    model = Messages(self)
    if history:
        model.replace(history)
    return model


def _load_task_runtime(self, task: dict) -> None:
    target_endpoint = str(task.get("endpoint") or self._default_endpoint).strip().rstrip("/")
    target_model = str(task.get("model") or self._default_model).strip()
    endpoint_changed = target_endpoint != self._endpoint
    model_changed = target_model != self._model
    self._endpoint = target_endpoint
    self._model = target_model

    # Merely opening another chat on the same Ollama server must not tear
    # down the known-good connection or launch a redundant network probe.
    # Re-probe capabilities only when the model actually changed or the
    # current capability set is unknown.
    if not endpoint_changed:
        self._decorate_catalog()
        if self._online and (model_changed or not self._model_capabilities):
            self._refresh_model_capabilities()
        return

    cached = self._endpoint_catalog_cache.get(target_endpoint)
    if cached:
        models, resident = cached
        self._models = [m["name"] for m in models]
        self._catalog = [self._catalog_entry(m) for m in models]
        self._resident_models = system_info.resident_models(resident)
        self._loaded_models = [entry["name"] for entry in self._resident_models]
        self._online = True
        self._decorate_catalog()
        self._refresh_model_capabilities()
    else:
        self._online = False
        self._models = []
        self._catalog = []
        self._resident_models = []
        self._loaded_models = []
        self.catalogChanged.emit()
        self.refreshModels()


def _reset_run_state(self):
    self._activity = []
    self._think_seconds = 0.0
    self._token_rate = "—"
    self._run_metrics = _blank_metrics()
    self._status = "Ready when you are"


@Slot(str)
def setDraft(self, text):
    self._draft_text = str(text)


def _save_draft(self):
    """Park what is in the composer against the task being left."""
    if self._draft_text or self._attachments:
        self._drafts[self._task_id] = (self._draft_text, list(self._attachments))
    else:
        self._drafts.pop(self._task_id, None)


def _restore_draft(self):
    text, attachments = self._drafts.pop(self._task_id, ("", []))
    self._draft_text = text
    self._attachments = attachments
    self.draftChanged.emit()
    self.attachmentsChanged.emit()


@Slot()
def newTask(self):
    previous = self._task_id
    previous_state = self._run_sessions.get(previous)
    if previous_state and previous_state.get("computer_control_active"):
        previous_state["computer_control_active"] = False
        self._release_desktop_control(previous)
    self._save_draft()
    self._task_id = ""
    self._task_title = "New task"
    self._history = []
    self._history_tokens = 0
    self.messages = self._new_message_model()
    self._load_task_runtime({
        "endpoint": self._default_endpoint,
        "model": self._default_model,
    })
    self._reset_run_state()
    self._busy = False
    self._run_job = None
    self._pending_permission = None
    self._session_auto = False
    self._clear_error()
    self.cancelRegion()
    self._restore_draft()
    self.activityChanged.emit()
    self.permissionChanged.emit()
    self.changed.emit()
    self.focusComposer.emit()


@Slot(str)
def openTask(self, task_id):
    task_id = str(task_id or "")
    task = self.store.get_conversation(task_id)
    if not task:
        return
    switching = task_id != self._task_id
    if switching:
        previous = self._task_id
        previous_state = self._run_sessions.get(previous)
        if previous_state and previous_state.get("computer_control_active"):
            previous_state["computer_control_active"] = False
            self._release_desktop_control(previous)
        self._save_draft()
        self.cancelRegion()
    self._task_id = task_id
    self._task_title = task["title"]
    self._load_task_runtime(task)
    if switching:
        self._restore_draft()
    session = self._run_sessions.get(task_id)
    if session:
        self._sync_active_session(session)
    else:
        self._history = self.store.get_messages(task_id)
        self.messages = self._new_message_model(self._history)
        self._reset_run_state()
        self._busy = False
        self._run_job = None
        self._pending_permission = None
        self._session_auto = False
        self._clear_error()
    self._recount_history_tokens()
    self.activityChanged.emit()
    self.permissionChanged.emit()
    self.changed.emit()
    self.scrollToEnd.emit()


@Slot(str)
def deleteTask(self, task_id):
    task_id = str(task_id or "")
    session = self._run_sessions.get(task_id)
    if session and session.get("busy"):
        self.toast.emit("Stop that chat before deleting it.")
        return
    self._run_sessions.pop(task_id, None)
    self.store.delete_conversation(task_id)
    self._drafts.pop(task_id, None)
    if task_id == self._task_id:
        self._draft_text = ""
        self.clearAttachments()
        self.newTask()
    self._refresh_tasks()
    self.toast.emit("Chat deleted")


@Slot(str, str)
def renameTaskById(self, task_id, title):
    if not str(title).strip():
        return
    self.store.rename_conversation(task_id, str(title).strip()[:200])
    if task_id == self._task_id:
        self._task_title = str(title).strip()[:200]
    self._refresh_tasks()
    self.changed.emit()


def _maybe_generate_task_title(self, task_id: str, history: list[dict], state: dict) -> None:
    """Replace the first-message fallback with a local model-generated title.

    A manual rename always wins. We check the stored title both before and
    after generation so a rename performed while the title job is running
    can never be overwritten by a late model response.
    """
    task_id = str(task_id or "")
    if not task_id or task_id in self._title_generating:
        return

    user_messages = [
        message for message in history
        if message.get("role") == "user"
        and not ctx.is_context_message(message)
        and str(message.get("content", "") or "").strip()
    ]
    assistant_messages = [
        message for message in history
        if message.get("role") == "assistant"
        and str(message.get("content", "") or "").strip()
    ]
    if not user_messages or not assistant_messages:
        return

    first_user = str(user_messages[0].get("content", "") or "").strip()
    fallback_title = derive_title(first_user)
    task = self.store.get_conversation(task_id)
    if not task or str(task.get("title", "")) != fallback_title:
        return

    # Steering can add another user message before the first finished turn.
    # A couple of short excerpts make the generated title reflect that
    # correction without feeding the title request the whole conversation.
    user_excerpt = "\n".join(
        str(message.get("content", "") or "").strip()
        for message in user_messages[:3]
    )[:1800]
    assistant_excerpt = str(assistant_messages[-1].get("content", "") or "").strip()[:1800]
    endpoint = str(state.get("endpoint") or self._endpoint)
    model = str(state.get("model") or self._model)
    self._title_generating.add(task_id)

    def settled():
        self._title_generating.discard(task_id)

    def generated(title):
        settled()
        current = self.store.get_conversation(task_id)
        if not current or str(current.get("title", "")) != fallback_title:
            return
        title = str(title or "").strip()[:200]
        if not title or title == fallback_title:
            return
        self.store.rename_conversation(task_id, title)
        session = self._run_sessions.get(task_id)
        if session is not None:
            session["title"] = title
        if task_id == self._task_id:
            self._task_title = title
            self.changed.emit()
        self._refresh_tasks()

    def failed(_message):
        # Title generation is polish, not a reason to surface a task error.
        # The deterministic first-message title remains a perfectly usable fallback.
        settled()

    self._job(
        lambda cancel, emit: self._ollama_client(endpoint).generate_title(
            model, user_excerpt, assistant_excerpt, cancel),
        generated,
        failed,
    )


@Slot(str)
def duplicateTaskById(self, task_id):
    if self._busy:
        return
    source = self.store.get_conversation(task_id)
    if not source:
        return
    copy_task = self.store.create_conversation(f"{source['title']} copy"[:200], source.get("model", ""), source.get("endpoint", ""))
    self.store.set_messages(copy_task["id"], self.store.get_messages(task_id), source.get("model", ""), source.get("endpoint", ""))
    self._refresh_tasks()
    self.openTask(copy_task["id"])
    self.toast.emit("Chat duplicated")


@Slot()
def duplicateTask(self):
    if self._busy or not self._task_id:
        return
    task = self.store.create_conversation(f"{self._task_title} copy"[:200], self._model, self._endpoint)
    self.store.set_messages(task["id"], list(self._history), self._model, self._endpoint)
    self._refresh_tasks()
    self.openTask(task["id"])
    self.toast.emit("Chat duplicated")


@Slot()
def clearTask(self):
    if self._busy or not self._task_id:
        return
    self._history = []
    self._history_tokens = 0
    self.store.set_messages(self._task_id, [], self._model, self._endpoint)
    self.messages.replace([])
    self._reset_run_state()
    self.activityChanged.emit()
    self._refresh_tasks()
    self.changed.emit()
    self.toast.emit("Conversation cleared")


@Slot(str)
def togglePin(self, task_id):
    task = self.store.get_conversation(task_id)
    if not task:
        return
    self.store.set_pinned(task_id, not bool(task.get("pinned")))
    self._refresh_tasks()
    self.changed.emit()


def _history_cut(self, row: int) -> list[dict]:
    """History up to and including the message shown at view ``row``.

    View rows and history entries do not line up: tool results and attached
    context are folded into activity groups, so the mapping is recomputed
    with exactly the rules the model uses.
    """
    seen = -1
    pending = False
    for position, message in enumerate(self._history):
        if ctx.is_context_message(message):
            continue
        if message.get("role") == "tool":
            pending = True
            continue
        if message.get("role") not in ("user", "assistant"):
            continue
        if message.get("images") and str(message.get("content", "")).startswith("Current desktop screenshot ("):
            continue
        if not message.get("content") and not message.get("thinking"):
            continue
        if pending:
            seen += 1        # The folded activity group occupies one row.
            pending = False
            if seen == row:
                return self._history[:position]
        seen += 1
        if seen == row:
            return self._history[:position + 1]
    return list(self._history)


@Slot(int)
def branchFrom(self, row):
    """Fork the conversation into a new chat that ends at ``row``."""
    if self._busy or not self._task_id:
        return
    history = self._history_cut(int(row))
    task = self.store.create_conversation(f"{self._task_title} branch"[:200], self._model, self._endpoint)
    self.store.set_messages(task["id"], history, self._model, self._endpoint)
    self._refresh_tasks()
    self.openTask(task["id"])
    self.toast.emit("Branched into a new chat")


@Slot(int, str)
def editMessage(self, row, text):
    """Replace a user message and re-run the conversation from there."""
    text = str(text).strip()
    if self._busy or not text or not self._online:
        return
    history = self._history_cut(int(row))
    while history and history[-1].get("role") != "user":
        history.pop()
    if not history:
        return
    history[-1] = {"role": "user", "content": text}
    self._history = history
    self.store.set_messages(self._task_id, history, self._model, self._endpoint)
    self.messages.replace(history)
    self._start_run(list(history))


@Slot()
def regenerate(self):
    if self._busy or not self._task_id or not self._online:
        return
    if self.desktopEnabled:
        self.toast.emit("Turn off screen control before regenerating so actions are not repeated.")
        return
    if self._last_turn_used_tools():
        self.toast.emit("This reply ran actions. Send a follow-up to avoid repeating them accidentally.")
        return
    history = list(self._history)
    while history and history[-1].get("role") != "user":
        history.pop()
    if not history:
        self.toast.emit("There is no message to regenerate.")
        return
    self._history = history
    self.store.set_messages(self._task_id, history, self._model, self._endpoint)
    self.messages.replace(history)
    self._start_run(history)


@Slot(str)
def regenerateWithPreset(self, name):
    """Retry a tool-free answer after applying one named runtime preset."""
    name = str(name or "")
    if not self.canRegenerate or name not in self.RUNTIME_PRESETS:
        return
    self.applyRuntimePreset(name)
    self.regenerate()
