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
        self.OLLAMA_CLIENT(state["endpoint"]), run_desktop, self._memory_for_run(),
        browser_open=browser_open,
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


def _start_run(self, history):
    self._launch_run(history, AgentEngine)


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


def _confirm_action_for(self, task_id: str, name: str, args: dict, risk: str) -> bool:
    """Block only the run asking for permission; other chats stay usable."""
    state = self._run_sessions.get(str(task_id or ""))
    if not state:
        # Preserve the direct/foreground permission path used by small
        # controller hosts and tests that do not create a run session.
        if self._session_auto and risk != "destructive":
            return True
        self._permission_event.clear()
        self._permission_answer = False
        self._pending_permission = {
            "tool": name, "risk": risk, "summary": action_summary(name, args),
            "detail": json.dumps(args, ensure_ascii=False) if args else "",
            "command": str(args.get("command", "")) if name == "run_command" else "",
            "directory": (str(args.get("cwd") or self._working_directory or Path.home())
                          if name == "run_command" else ""),
        }
        self.permissionChanged.emit()
        self.changed.emit()
        allowed = self._permission_event.wait(self.PERMISSION_TIMEOUT)
        answer = bool(allowed and self._permission_answer)
        self._pending_permission = None
        self.permissionChanged.emit()
        self.changed.emit()
        return answer
    if state.get("session_auto") and risk != "destructive":
        return True
    event = state["permission_event"]
    event.clear()
    state["permission_answer"] = False
    state["permission"] = {
        "tool": name, "risk": risk, "summary": action_summary(name, args),
        "detail": json.dumps(args, ensure_ascii=False) if args else "",
        "command": str(args.get("command", "")) if name == "run_command" else "",
        "directory": (str(args.get("cwd") or state.get("project") or Path.home())
                      if name == "run_command" else ""),
    }
    if task_id == self._task_id:
        self._pending_permission = state["permission"]
        self.permissionChanged.emit()
        self.changed.emit()
    allowed = event.wait(self.PERMISSION_TIMEOUT)
    answer = bool(allowed and state.get("permission_answer"))
    state["permission"] = None
    if task_id == self._task_id:
        self._pending_permission = None
        self.permissionChanged.emit()
        self.changed.emit()
    return answer


def _confirm_action(self, name: str, args: dict, risk: str) -> bool:
    return self._confirm_action_for(self._task_id, name, args, risk)


@Slot(bool)
def resolvePermission(self, allowed):
    state = self._active_session()
    if state and state.get("permission") is not None:
        state["permission_answer"] = bool(allowed)
        self._permission_answer = bool(allowed)
        state["permission_event"].set()
        return
    if self._pending_permission is not None:
        self._permission_answer = bool(allowed)
        self._permission_event.set()


@Slot()
def allowRestOfTask(self):
    state = self._active_session()
    if state and state.get("permission") is not None:
        state["session_auto"] = True
        state["permission_answer"] = True
        self._session_auto = True
        state["permission_event"].set()
        self.toast.emit("Approving the rest of this task, except anything that cannot be undone")
        return
    if self._pending_permission is not None:
        self._session_auto = True
        self._permission_answer = True
        self._permission_event.set()
        self.toast.emit("Approving the rest of this task, except anything that cannot be undone")


@Slot(str)
def setPermissionMode(self, mode):
    mode = str(mode)
    if mode not in PERMISSION_MODES or mode == self._permission_mode:
        return
    self._permission_mode = mode
    self.store.set_setting("permission_mode", mode)
    for state in self._run_sessions.values():
        if state.get("busy"):
            state["session_auto"] = False
    self._session_auto = False
    self.changed.emit()
    self.toast.emit(f"Permission set to {PERMISSION_LABELS[mode]}")


def _memory_for_run(self):
    """The memory a run may read and write, or None while memory is off."""
    return self.memory if self._memory_enabled else None


@Slot(bool)
def setMemoryEnabled(self, enabled):
    enabled = bool(enabled)
    if enabled == self._memory_enabled:
        return
    self._memory_enabled = enabled
    self.store.set_setting("memory_enabled", enabled)
    self.memoryChanged.emit()
    self.changed.emit()
    self.toast.emit("Memory is on. Notes are read into every task."
                    if enabled else "Memory is off. The file is kept, but nothing reads it.")


@Slot(str)
def saveMemory(self, text):
    """Save the memory file as edited in Wynxq, replacing what was there."""
    try:
        self.memory.write(text)
    except (OSError, ValueError) as exc:
        self.toast.emit(str(exc))
        return
    self.memoryChanged.emit()
    self.toast.emit("Memory saved")


@Slot(str)
def rememberNote(self, note):
    """Add one note by hand, the same way the model's remember tool does."""
    try:
        result = self.memory.remember(note, project=self._working_directory)
    except (OSError, ValueError) as exc:
        self.toast.emit(str(exc))
        return
    self.memoryChanged.emit()
    self.toast.emit("Remembered" if result.get("stored") else "Already remembered")


@Slot()
def clearMemory(self):
    try:
        self.memory.clear()
    except OSError as exc:
        self.toast.emit(str(exc))
        return
    self.memoryChanged.emit()
    self.toast.emit("Memory cleared")


@Slot()
def reloadMemory(self):
    """Re-read the file — it is plain Markdown, so anything may have edited it."""
    self.memoryChanged.emit()


@Slot()
def revealMemory(self):
    if not self.memory.exists():
        try:
            self.memory.clear()
        except OSError as exc:
            self.toast.emit(str(exc))
            return
        self.memoryChanged.emit()
    if not notify.open_path(str(self.memory.path)):
        self.copyText(str(self.memory.path))
        self.toast.emit("No application opened it, so the path was copied instead.")


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
        messages.finish_stream(float(state.get("think_seconds", 0.0) or 0.0),
                               event.get("message"))
        state["turn_had_message"] = False
        state["think_started"] = 0.0
        state["think_seconds"] = 0.0
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
        steering = [] if stopped_by_user else list(state.get("steering_messages") or [])
        queued = [] if stopped_by_user else list(state.get("queued_messages") or [])
        if steering and task_id == self._task_id:
            continued = list(history)
            for message in steering:
                continued.append({"role": "user", "content": message})
            self._history = continued
            self.store.set_messages(task_id, continued, state["model"], state["endpoint"])
            # Keep queued follow-ups across the steering restart. Desktop
            # ownership intentionally stays with this task; the resumed run
            # will reuse it and the eventual final run releases it.
            self._launch_run(continued, AgentEngine, extras={"queued_messages": queued})
            self.scrollToEnd.emit()
            return
        if queued and task_id == self._task_id:
            continued = list(history)
            next_message, remaining = queued[0], queued[1:]
            continued.append({"role": "user", "content": next_message})
            state["messages"].append_message("user", next_message)
            self._history = continued
            self.store.set_messages(task_id, continued, state["model"], state["endpoint"])
            self._launch_run(continued, AgentEngine, extras={"queued_messages": remaining})
            self.scrollToEnd.emit()
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
    state["busy"] = False
    state["job"] = None
    state["session_auto"] = False
    state["computer_control_active"] = False
    self._release_desktop_control(task_id)
    state["permission"] = None
    state["messages"].mark_idle()
    state["status"] = "Stopped" if stopped else (
        "Needs attention" if state.get("error") else "Ready when you are")
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
        self._maybe_generate_task_title(task_id, state["history"], state)
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
        self._overlay_promotion_active = False

    self._job(lambda cancel, emit: kwin.promote_control_windows(cancel),
              settled, lambda _message: settled())


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
        for progress in self.OLLAMA_CLIENT(endpoint).pull(model, cancel):
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
