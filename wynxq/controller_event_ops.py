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

def _on_event(self, event, task_id=None):
    task_id = str(task_id or self._task_id or "")
    state = self._run_sessions.get(task_id)
    legacy = state is None
    if legacy:
        state = {
            "task_id": task_id, "messages": self.messages, "history": self._history,
            "busy": self._busy, "job": self._run_job, "status": self._status,
            "token_rate": self._token_rate, "metrics": dict(self._run_metrics),
            "activity": list(self._activity), "think_started": self._think_started,
            "think_seconds": self._think_seconds,
            "turn_had_message": self._turn_had_message,
            "error": self._error, "error_title": self._error_title,
            "error_actions": list(self._error_actions),
            "permission": self._pending_permission,
            "permission_event": self._permission_event,
            "permission_answer": self._permission_answer,
            "session_auto": self._session_auto,
        }
    messages = state["messages"]
    kind = event.get("type")
    if kind in ("token", "thinking"):
        if not state.get("turn_had_message"):
            messages.append_message("assistant", streaming=True)
            state["turn_had_message"] = True
            state["overlay_thought"] = ""
            state["overlay_reply"] = ""
        streamed = str(event.get("text", "") or "")
        if kind == "thinking":
            if not state.get("think_started"):
                state["think_started"] = time.monotonic()
            messages.stream("thought", streamed)
            state["overlay_thought"] = (str(state.get("overlay_thought", "")) + streamed)[-4000:]
            state["status"] = "Thinking"
        else:
            if state.get("think_started") and not state.get("think_seconds"):
                state["think_seconds"] = time.monotonic() - state["think_started"]
            messages.stream("body", streamed)
            state["overlay_reply"] = (str(state.get("overlay_reply", "")) + streamed)[-4000:]
            state["status"] = "Writing"
    elif kind == "message_end":
        final_message = event.get("message")
        if isinstance(final_message, dict):
            state["overlay_thought"] = str(final_message.get("thinking") or "")[-4000:]
            state["overlay_reply"] = str(final_message.get("content") or "")[-4000:]
        messages.finish_stream(float(state.get("think_seconds", 0.0) or 0.0),
                               event.get("message"))
        state["turn_had_message"] = False
        state["think_started"] = 0.0
        state["think_seconds"] = 0.0
    elif kind == "memory_changed":
        self.memoryChanged.emit()
    elif kind == "memory_warning":
        self.toast.emit(str(event.get("text", "Automatic memory is unavailable this turn.")))
    elif kind == "status":
        state["status"] = event.get("text", "Working")
    elif kind == "session":
        state["status"] = "Screen control ready"
    elif kind == "control_active":
        state["computer_control_active"] = True
        state["status"] = "Controlling your computer"
        self._desktop_status = self.desktop.status()
    elif kind == "screen_observed":
        state["status"] = "Observed the updated screen"
        self._desktop_status = self.desktop.status()
    elif kind == "tool_start":
        name = event.get("name", "action")
        icon, label = TOOL_PRESENTATION.get(name, ("bolt", name.replace("_", " ").capitalize()))
        summary = event.get("summary") or ""
        step = {"name": name, "icon": icon, "label": label, "summary": summary,
                "detail": json.dumps(event.get("args", {}), ensure_ascii=False)[:200],
                "state": "waiting" if event.get("confirming") else "running",
                "risk": event.get("risk", "normal"), "ms": 0, "output": ""}
        messages.append_activity(step)
        state["activity"] = (list(state.get("activity") or []) + [step])[-60:]
        state["status"] = summary or label
        if task_id == self._task_id:
            self.dock.record(step)
            if name == "run_command":
                self.dock.suggest("terminal")
            elif name == "browser_open":
                self.dock.suggest("browser", open_dock=True)
            self.activityChanged.emit()
            self.scrollToEnd.emit()
    elif kind == "tool_end":
        result = event.get("result", {})
        failed = bool(result.get("error")) or result.get("ok") is False
        step_state = "declined" if event.get("declined") else ("failed" if failed else "done")
        output = str(result.get("error") or "")
        if result.get("output"):
            output = str(result["output"]) + ("\n" + output if output else "")
        if not output and result.get("apps"):
            output = f"{len(result['apps'])} applications found"
        elif not output and result.get("width"):
            output = f"Captured {result['width']} × {result['height']} pixels"
        elif not output and event.get("name") == "remember":
            output = ("Remembered: " if result.get("stored") else "Already known: ") + str(result.get("note", ""))
        elif not output and event.get("name") == "forget":
            output = f"Forgot {result.get('forgotten', 0)} note(s)"
        patch = {"state": step_state, "ms": int(event.get("ms", 0) or 0),
                 "output": output[:32000]}
        messages.update_last_step(**patch)
        activity = list(state.get("activity") or [])
        if activity:
            activity[-1] = {**activity[-1], **patch}
            state["activity"] = activity
        if task_id == self._task_id:
            self.dock.record_update(**patch)
            self.activityChanged.emit()
            if event.get("name") in ("run_command", "write_file", "edit_file"):
                self.dock.refreshChanges()
        if event.get("name") in ("remember", "forget"):
            self.memoryChanged.emit()
    elif kind == "metrics":
        rate = event.get("tokens_per_second", 0)
        previous = state.get("metrics") or _blank_metrics()
        state["metrics"] = {
            "tokens": previous.get("tokens", 0) + int(event.get("tokens", 0) or 0),
            "prompt_tokens": int(event.get("prompt_tokens", 0) or 0),
            "cached_prompt_tokens": int(event.get("cached_prompt_tokens", 0) or 0),
            "load_ms": previous.get("load_ms", 0.0) + float(event.get("load_ms", 0.0) or 0.0),
            "total_ms": previous.get("total_ms", 0.0) + float(event.get("total_ms", 0.0) or 0.0),
            "tokens_per_second": float(rate) if isinstance(rate, (int, float)) else 0.0,
        }
        state["token_rate"] = f"{rate:.1f} tok/s" if isinstance(rate, (int, float)) else "—"
    elif kind == "error":
        state["error_title"] = "The model run did not finish"
        state["error"] = str(event.get("text", "Something went wrong"))
        state["error_actions"] = [{"label": "Try again", "action": "regenerate"}]
    elif kind == "cancelled":
        state["status"] = "Stopped"

    if legacy or task_id == self._task_id:
        self._sync_active_session(state)
        self.changed.emit()


def _run_done(self, history, task_id=None):
    task_id = str(task_id or self._task_id or "")
    state = self._run_sessions.get(task_id)
    if state is not None:
        stopped_by_user = bool(state.get("stop_requested"))
        if not stopped_by_user and self._resume_pending_followup(
                task_id, history, finishing=True):
            return
    if state is None:
        # Compatibility for direct unit calls that predate task sessions.
        self._history = history
        self._recount_history_tokens()
        if self._task_id:
            self.store.set_messages(self._task_id, history, self._model, self._endpoint)
        self._busy = False
        self._run_job = None
        self.messages.mark_idle()
        self.changed.emit()
        return

    state["history"] = list(history)
    job = state.get("job")
    stopped = bool(job and job.cancel.is_set())
    elapsed = time.monotonic() - float(state.get("run_started", 0.0) or 0.0)
    preserve_desktop = bool(state.pop("_preserve_desktop_for_followup", False))
    state["busy"] = False
    state["job"] = None
    state["session_auto"] = False
    state["computer_control_active"] = False
    if not preserve_desktop:
        self._release_desktop_control(task_id)
    state["permission"] = None
    state["messages"].mark_idle()
    pending_followup = bool(
        not state.get("stop_requested")
        and (state.get("steering_messages") or state.get("queued_messages"))
    )
    state["status"] = (
        "Reopen to continue steering"
        if pending_followup and state.get("steering_messages")
        else "Queued · reopen to continue"
        if pending_followup
        else "Stopped" if stopped
        else "Needs attention" if state.get("error")
        else "Ready when you are"
    )
    try:
        self.store.set_messages(
            task_id, state["history"], state["model"], state["endpoint"])
    except KeyError:
        # The only supported delete-during-run path cancels first, but be
        # defensive against an externally modified history database.
        pass

    if task_id == self._task_id:
        self._sync_active_session(state)
        self._recount_history_tokens()
        self.dock.settle_turn(
            "cancelled" if stopped else ("failed" if state.get("error") else "done"))
        if self._working_directory:
            self.dock.refreshChanges()
        self.permissionChanged.emit()
        self.changed.emit()
        if not stopped and not state.get("error"):
            self._maybe_notify(elapsed)
    if not stopped and not state.get("error"):
        self._schedule_memory_learning(task_id, state["history"], state)
    self._refresh_tasks()


def _run_failed(self, message, task_id=None):
    task_id = str(task_id or self._task_id or "")
    state = self._run_sessions.get(task_id)
    if state is None:
        self._busy = False
        self._run_job = None
        self.messages.mark_idle()
        self._status = "Needs attention"
        self._set_error("The model run did not finish", message,
                        [{"label": "Try again", "action": "regenerate"},
                         {"label": "Connection settings", "action": "settings"}])
        return
    state["busy"] = False
    state["job"] = None
    state["session_auto"] = False
    state["computer_control_active"] = False
    self._release_desktop_control(task_id)
    state["permission"] = None
    state["messages"].mark_idle()
    state["status"] = "Needs attention"
    state["error_title"] = "The model run did not finish"
    state["error"] = str(message)
    state["error_actions"] = [
        {"label": "Try again", "action": "regenerate"},
        {"label": "Connection settings", "action": "settings"},
    ]
    if task_id == self._task_id:
        self._sync_active_session(state)
        self.dock.settle_turn("failed")
        self.permissionChanged.emit()
        self.changed.emit()
    self._refresh_tasks()


def _maybe_notify(self, seconds: float):
    if not notify.should_notify(seconds, self._window_active, self._notifications):
        return
    title = self._task_title if self._task_title != "New task" else "Wynxq"
    self._job(lambda cancel, emit: notify.send("Wynxq finished your task", title))


@Slot(bool)
def setWindowActive(self, active):
    self._window_active = bool(active)


def _desktop_control_released(self, status):
    self._desktop_status = dict(status or self.desktop.status())
    self.changed.emit()


def _release_desktop_control(self, task_id: str) -> None:
    if not task_id or not hasattr(self.desktop, "end_control"):
        return
    self._job(
        lambda cancel, emit: self.desktop.end_control(task_id),
        self._desktop_control_released,
        lambda message: None,
    )


@Slot()
def stop(self):
    state = self._active_session()
    if not state:
        if self._pending_permission is not None:
            self._permission_answer = False
            self._permission_event.set()
        if self._run_job:
            self._run_job.cancel.set()
            self._status = "Stopping…"
            self.changed.emit()
        return
    if state.get("permission") is not None:
        state["permission_answer"] = False
        state["permission_event"].set()
    job = state.get("job")
    if job:
        state["stop_requested"] = True
        state["steering_messages"] = []
        state["queued_messages"] = []
        job.cancel.set()
        state["computer_control_active"] = False
        self._release_desktop_control(str(state.get("task_id") or self._task_id))
        state["status"] = "Stopping…"
        self._sync_active_session(state)
        self.changed.emit()


@Slot()
def promoteComputerControlOverlay(self):
    """Best-effort Plasma/Wayland promotion for independent HUD windows."""
    if self._overlay_promotion_active:
        return
    self._overlay_promotion_active = True

    def settled(_result=None):
        cancelled = bool(self._overlay_promotion_job and self._overlay_promotion_job.cancel.is_set())
        self._overlay_promotion_active = False
        self._overlay_promotion_job = None
        if cancelled and self._overlay_visible:
            self.promoteComputerControlOverlay()

    self._overlay_promotion_job = self._job(
        lambda cancel, emit: kwin.promote_control_windows(cancel),
        settled, lambda _message: settled())


@Slot(bool)
def setComputerControlOverlayVisible(self, visible):
    self._overlay_visible = bool(visible)
    if visible:
        self.promoteComputerControlOverlay()
    elif self._overlay_promotion_job:
        self._overlay_promotion_job.cancel.set()


@Slot()
def toggleDesktop(self):
    if self._connecting:
        return
    if self.desktopEnabled:
        self.stop()
        # Revoke input immediately at the desktop backend, independent of generation.
        self._job(lambda cancel, emit: self.desktop.disconnect(), self._desktop_done)
    else:
        if self._busy:
            self.toast.emit("Turn on screen control before starting your task.")
            return
        self._connecting = True
        self.changed.emit()
        self._job(lambda cancel, emit: self.desktop.connect(), self._desktop_done, self._desktop_failed)


def _desktop_done(self, result):
    self._connecting = False
    self._desktop_status = self.desktop.status()
    if not self.desktopEnabled and result and not result.get("connected"):
        self._set_error("Screen control was not granted",
                        result.get("detail", "Desktop connection was not granted"),
                        [{"label": "Try again", "action": "desktop"}])
    self.changed.emit()


def _desktop_failed(self, message):
    self._connecting = False
    self._desktop_status = self.desktop.status()
    self._set_error("Screen control could not start", message,
                    [{"label": "Try again", "action": "desktop"}])


@Slot(str)
def pullModel(self, model):
    model = str(model).strip()
    if self._pulling or self._busy or not model:
        return
    self._pulling = True
    self._pull_progress = "Preparing download…"
    self._pull_percent = 0.0
    self.changed.emit()
    endpoint = self._endpoint

    def pull(cancel, emit):
        for progress in self._ollama_client(endpoint).pull(model, cancel):
            emit(progress)

    def progress(data):
        total, completed = data.get("total", 0), data.get("completed", 0)
        fraction = (completed / total) if total else 0.0
        self._pull_percent = max(0.0, min(1.0, fraction))
        percent = f" · {100 * fraction:.0f}%" if total else ""
        self._pull_progress = data.get("status", "Downloading") + percent
        self.changed.emit()

    def done(_):
        stopped = self._pull_job is not None and self._pull_job.cancel.is_set()
        self._pulling = False
        self._pull_job = None
        self._pull_percent = 0.0
        self._pull_progress = "Download stopped" if stopped else "Download complete"
        if not stopped:
            self.setModel(model)
            self.toast.emit(f"{model} is ready")
        self.changed.emit()
        self.refreshModels()

    def failed(message):
        self._pulling = False
        self._pull_job = None
        self._pull_percent = 0.0
        self._pull_progress = "Download failed"
        self._set_error("That model could not be downloaded", message,
                        [{"label": "Try again", "action": "models"}])

    self._pull_job = self._job(pull, done, failed, progress)


@Slot()
def cancelPull(self):
    if self._pull_job:
        self._pull_job.cancel.set()
