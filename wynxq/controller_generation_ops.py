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
from .memory_service import MemoryService
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

def _launch_run(self, history, engine_class=AgentEngine, *, tools_allowed=True,
                desktop_enabled=None, project=None, extras=None):
    task_id = str(self._task_id or "")
    if not task_id:
        raise RuntimeError("A conversation must exist before generation starts")
    state = {
        "task_id": task_id,
        "title": self._task_title,
        "model": self._model,
        "endpoint": self._endpoint,
        "messages": self.messages,
        "history": list(history),
        "busy": True,
        "job": None,
        "status": "Thinking",
        "token_rate": "—",
        "metrics": _blank_metrics(),
        "activity": [],
        "think_started": 0.0,
        "think_seconds": 0.0,
        "turn_had_message": False,
        "run_started": time.monotonic(),
        "error": "",
        "error_title": "",
        "error_actions": [],
        "permission": None,
        "permission_event": threading.Event(),
        "permission_answer": False,
        "session_auto": False,
        "computer_control_active": False,
        "overlay_thought": "",
        "overlay_reply": "",
        "steering_messages": [],
        "queued_messages": [],
        "stop_requested": False,
        "permission_mode_snapshot": self._permission_mode,
        "project": str(self._working_directory if project is None else project or ""),
    }
    if extras:
        state.update(extras)
    self._run_sessions[task_id] = state
    self._sync_active_session(state)
    self._clear_error()
    self.dock.begin_turn(self._task_title if self._task_title != "New task" else "Turn")
    self.activityChanged.emit()
    self._refresh_tasks()
    self.changed.emit()

    run_desktop = _RunDesktop(self, task_id)
    browser_open = (lambda target: self._request_builtin_browser_for(task_id, target)) \
        if self.dock.browserAvailable else None
    engine = engine_class(
        self._ollama_client(state["endpoint"]), run_desktop, self._memory_for_run(),
        browser_open=browser_open,
    )
    memory_service = MemoryService(
        self._ollama_client(state["endpoint"]), self.memory, self.store, task_id,
        memory_enabled=lambda: self._memory_enabled,
        history_enabled=lambda: self._reference_chat_history,
    )
    # Capture the original dialogue before PlanningAgentEngine adds workspace
    # context or compacts it. This callback runs on the model worker, not Qt.
    original_history = [dict(message) for message in history]
    engine.prepare_memory = lambda _history, model, project, cancel, emit, num_ctx: (
        memory_service.prepare(original_history, model, project, cancel, emit, num_ctx)
    )
    enabled = self.desktopEnabled if desktop_enabled is None else bool(desktop_enabled)
    think = self._think
    num_ctx, temperature = self._num_ctx, self._temperature
    keep_alive, max_steps = self._keep_alive, self._max_steps

    def permission_mode():
        current = self._permission_mode
        if current != state["permission_mode_snapshot"]:
            state["session_auto"] = False
            state["permission_mode_snapshot"] = current
        return current

    job = self._job(
        lambda cancel, emit: engine.run(
            list(history), state["model"], enabled, cancel, emit, think=think,
            max_steps=max_steps, num_ctx=num_ctx, temperature=temperature,
            keep_alive=keep_alive, permission_mode=permission_mode,
            project=state["project"],
            confirm=lambda name, args, risk: self._confirm_action_for(
                task_id, name, args, risk),
            tools_allowed=bool(tools_allowed)),
        lambda result: self._run_done(result, task_id),
        lambda message: self._run_failed(message, task_id),
        lambda event: self._on_event(event, task_id),
    )
    state["job"] = job
    if task_id == self._task_id:
        self._run_job = job
        self.changed.emit()
    return state


def _start_run(self, history, *, extras=None):
    self._launch_run(history, AgentEngine, extras=extras)


def _resume_pending_followup(self, task_id: str, history=None, *, finishing=False) -> bool:
    """Resume steering/queue work only when its conversation owns the foreground."""
    task_id = str(task_id or "")
    state = self._run_sessions.get(task_id)
    if (not state or task_id != self._task_id or state.get("stop_requested")
            or (state.get("busy") and not finishing)):
        return False

    steering = list(state.get("steering_messages") or [])
    queued = list(state.get("queued_messages") or [])
    if not steering and not queued:
        return False

    continued = list(state.get("history") if history is None else history)
    if steering:
        for message in steering:
            continued.append({"role": "user", "content": message})
        remaining = queued
    else:
        next_message, remaining = queued[0], queued[1:]
        continued.append({"role": "user", "content": next_message})
        state["messages"].append_message("user", next_message)

    self._history = continued
    self.store.set_messages(task_id, continued, state["model"], state["endpoint"])
    # Route through the virtual run hook so WorkspaceController preserves
    # Chat/Work tool boundaries, planning, usage and checkpoints on restart.
    self._start_run(continued, extras={"queued_messages": remaining})
    self.scrollToEnd.emit()
    return True


@staticmethod
def _queued_text(text: str):
    lowered = text.casefold()
    if lowered == "/queue":
        return ""
    if lowered.startswith("/queue "):
        return text[7:].strip()
    return None


def _send_while_busy(self, text: str) -> None:
    state = self._active_session()
    if not state:
        return
    queued = self._queued_text(text)
    if queued is not None:
        if not queued:
            self.toast.emit("Use /queue followed by the message you want to send next.")
            return
        state.setdefault("queued_messages", []).append(queued)
        count = len(state["queued_messages"])
        state["status"] = f"Queued {count} message" + ("s" if count != 1 else "")
        self._sync_active_session(state)
        self.changed.emit()
        self.toast.emit("Queued — Wynxq will handle it after the current turn.")
        return

    # Steering is the default mid-run behavior. Ollama streaming is not
    # duplex, so cancel at the nearest boundary, retain the partial
    # assistant/tool history, then immediately resume with this instruction.
    state.setdefault("steering_messages", []).append(text)
    state["messages"].append_message("user", text)
    state["status"] = "Steering…"
    job = state.get("job")
    if job is not None:
        job.cancel.set()
    self._sync_active_session(state)
    self.changed.emit()
    self.scrollToEnd.emit()


@Slot(str)
def send(self, text):
    text = str(text).strip()
    if not text or self._connecting:
        return
    if self._busy:
        self._send_while_busy(text)
        return
    queued = self._queued_text(text)
    if queued is not None:
        if not queued:
            self.toast.emit("Use /queue followed by the message you want to send next.")
            return
        text = queued
    if not self._online:
        self._set_error("Ollama isn't connected",
                        "Wynxq needs a running local Ollama server before it can answer.",
                        [{"label": "Retry", "action": "retry"},
                         {"label": "Connection settings", "action": "settings"}])
        return
    self._drafts.pop(self._task_id, None)
    self._draft_text = ""
    self.draftChanged.emit()
    if not self._task_id:
        task = self.store.create_conversation(
            derive_title(text), self._model, self._endpoint)
        self._task_id, self._task_title = task["id"], task["title"]
    attachments = [item for item in self._attachments
                   if item.get("enabled", True) is not False]
    deferred_attachments = [item for item in self._attachments
                            if item.get("enabled", True) is False]
    vision_ready = "vision" in self._model_capabilities
    extra = ctx.build_messages(attachments)
    self._history.extend(extra)
    self._history.append({"role": "user", "content": text})
    self._recount_history_tokens()
    self.store.set_messages(
        self._task_id, self._history, self._model, self._endpoint)
    self.messages.append_message(
        "user", text, attachments=ctx.display_attachments(attachments))
    if attachments and not vision_ready and ctx.needs_vision(attachments):
        self.toast.emit(f"{self._model} cannot read images, so pictures were left out.")
    if deferred_attachments:
        self._attachments = deferred_attachments
        self.attachmentsChanged.emit()
        self.changed.emit()
    else:
        self.clearAttachments()
    self._start_run(list(self._history))
    self.scrollToEnd.emit()
