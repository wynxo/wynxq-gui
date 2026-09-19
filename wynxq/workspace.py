"""Task-scoped Chat / Work mode state and live agent plans.

The base Controller intentionally stays focused on conversation, Ollama and
runtime state. WorkspaceController adds the product-level behavior used by the
shell: a new task starts unlocked, choosing Chat or Work locks that task's mode,
and Work combines coding and desktop tools. Modes and plans are kept in
the existing private settings table so old databases need no migration.

Wynxq GUI is also the desktop product's network-policy layer. The engine historically
accepted loopback-only Ollama URLs, which made a perfectly normal homelab setup
impossible. The desktop app now accepts explicit HTTP(S) Ollama origins on the
LAN or elsewhere while still rejecting credentials, paths, query strings and
redirects. This keeps the endpoint predictable without pretending every model
has to live on the same machine as the GUI.
"""
from __future__ import annotations

import copy
from pathlib import Path
import time

from PySide6.QtCore import Property, QTimer, Signal, Slot

from . import context as ctx
from . import project_instructions
from .controller import Controller, _blank_metrics
from .memory_learning import learnable_memories
from .usage import TokenUsageTracker
from .endpoint_policy import (
    WorkspaceOllamaClient, endpoint_scope, validate_workspace_endpoint,
)
from .planning import PLAN_STATES, PlanningAgentEngine, _install_plan_tool
from .workspace_checkpoint import (
    _checkpoint_delta, _restore_workspace_checkpoint, _snapshot_git_workspace,
)


class WorkspaceController(Controller):
    OLLAMA_CLIENT = WorkspaceOllamaClient
    modeChanged = Signal()
    endpointChanged = Signal()
    planChanged = Signal()
    usageChanged = Signal()
    contextStateChanged = Signal()
    checkpointChanged = Signal()
    VALID_TASK_MODES = {"chat", "work"}
    LAST_TASK_KEY = "workspace:last_task"
    DRAFT_KEY_PREFIX = "workspace:draft:"

    def __init__(self, *args, **kwargs):
        self._task_mode = "chat"
        self._task_mode_locked = False
        self._plan_steps: list[dict] = []
        _install_plan_tool()
        super().__init__(*args, **kwargs)
        self._usage = TokenUsageTracker(self.store)
        self._conversation_tokens = 0
        self._workspace_shutdown = False
        self._project_instructions_summary = project_instructions.summary(self._working_directory)
        self._context_omitted_turns = 0
        self._workspace_checkpoint: dict | None = None
        self._task_checkpoints: dict[str, dict] = {}
        # Draft text is cheap state worth surviving a restart, but attachments are
        # intentionally one-turn context and are never serialized here. Debounce
        # SQLite writes so typing does not become one transaction per keypress.
        self._draft_persist_timer = QTimer(self)
        self._draft_persist_timer.setSingleShot(True)
        self._draft_persist_timer.setInterval(400)
        self._draft_persist_timer.timeout.connect(self._persist_current_draft)
        self._restore_workspace_session()

    def _emit_mode(self) -> None:
        self.modeChanged.emit()
        self.changed.emit()

    @staticmethod
    def _mode_key(task_id: str) -> str:
        return f"task_mode:{task_id}"

    @staticmethod
    def _plan_key(task_id: str) -> str:
        return f"task_plan:{task_id}"

    @classmethod
    def _draft_key(cls, task_id: str) -> str:
        return cls.DRAFT_KEY_PREFIX + (str(task_id or "") or "__new__")

    def _set_last_task(self, task_id: str) -> None:
        self.store.set_setting(self.LAST_TASK_KEY, str(task_id or ""))

    def _persist_current_draft(self) -> None:
        self.store.set_setting(self._draft_key(self._task_id), str(self._draft_text or ""))

    def _restore_workspace_session(self) -> None:
        """Restore passive UI state only; never resume a model/tool run."""
        task_id = str(self.store.get_setting(self.LAST_TASK_KEY, "") or "")
        if task_id and self.store.get_conversation(task_id):
            self._recover_interrupted_plan(task_id)
            self.openTask(task_id)
            return
        if task_id:
            self._set_last_task("")
        # Controller starts on a blank task but does not normally restore a
        # draft until a task switch. Do that once for restart continuity.
        self._restore_draft()

    def _save_draft(self):
        super()._save_draft()
        if hasattr(self, "_draft_persist_timer"):
            self._draft_persist_timer.stop()
        self._persist_current_draft()

    def _restore_draft(self):
        super()._restore_draft()
        if self._draft_text:
            return
        saved = self.store.get_setting(self._draft_key(self._task_id), "")
        if isinstance(saved, str) and saved:
            self._draft_text = saved
            self.draftChanged.emit()

    @Slot(str)
    def setDraft(self, text):
        super().setDraft(text)
        if hasattr(self, "_draft_persist_timer"):
            self._draft_persist_timer.start()

    def _saved_mode(self, task_id: str) -> str:
        mode = str(self.store.get_setting(self._mode_key(task_id), "chat") or "chat")
        # Coding tasks now use the same Work toolset as desktop tasks. Persist
        # this small migration so reopening or duplicating keeps that intent.
        if mode == "codex":
            mode = "work"
            self.store.set_setting(self._mode_key(task_id), mode)
        return mode if mode in self.VALID_TASK_MODES else "chat"

    @staticmethod
    def _normalise_plan(steps) -> list[dict]:
        result, seen = [], set()
        for index, item in enumerate(list(steps or [])[:8]):
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title", "")).split())[:180]
            if not title:
                continue
            identifier = "".join(ch for ch in str(item.get("id", "")).strip()[:48]
                                 if ch.isalnum() or ch in "-_.") or f"step-{index + 1}"
            if identifier in seen:
                identifier = f"{identifier}-{index + 1}"
            seen.add(identifier)
            status = str(item.get("status", "pending"))
            if status not in PLAN_STATES:
                status = "pending"
            result.append({"id": identifier, "title": title, "status": status})
        return result

    def _saved_plan(self, task_id: str) -> list[dict]:
        """Read persisted plan state without pretending a normal read is a restart."""
        return self._normalise_plan(self.store.get_setting(self._plan_key(task_id), []))

    def _recover_interrupted_plan(self, task_id: str) -> None:
        """On process startup only, stale running steps become pending.

        A restart cannot prove an in-progress action completed, but opening,
        duplicating or inspecting a task during the same process must preserve
        its live status exactly as stored.
        """
        plan = self._saved_plan(task_id)
        interrupted = False
        for step in plan:
            if step["status"] == "in_progress":
                step["status"] = "pending"
                interrupted = True
        if interrupted:
            self.store.set_setting(self._plan_key(task_id), plan)

    def _persist_task_mode(self, task_id: str | None = None) -> None:
        target = str(task_id or self._task_id or "")
        if target:
            self.store.set_setting(self._mode_key(target), self._task_mode)

    def _persist_plan(self, task_id: str | None = None) -> None:
        target = str(task_id or self._task_id or "")
        if target:
            self.store.set_setting(self._plan_key(target), self._plan_steps)

    def _set_plan(self, steps, *, persist: bool = True) -> None:
        fresh = self._normalise_plan(steps)
        if fresh == self._plan_steps:
            return
        self._plan_steps = fresh
        if persist:
            self._persist_plan()
        self.planChanged.emit()

    def _settle_plan(self, outcome: str) -> None:
        if not self._plan_steps:
            return
        changed = False
        fresh = []
        for step in self._plan_steps:
            item = dict(step)
            if item["status"] == "in_progress":
                item["status"] = ("failed" if outcome == "failed" else
                                  "pending" if outcome == "cancelled" else "completed")
                changed = True
            fresh.append(item)
        if changed:
            self._set_plan(fresh)

    @staticmethod
    def _strip_plan_history(history) -> list[dict]:
        """The plan is workspace state, not conversation/activity evidence."""
        cleaned = []
        for message in list(history or []):
            if message.get("role") == "tool" and message.get("tool_name") == "update_plan":
                continue
            if message.get("role") == "assistant" and message.get("tool_calls"):
                item = copy.deepcopy(message)
                calls = [call for call in item.get("tool_calls", [])
                         if call.get("function", {}).get("name") != "update_plan"]
                if calls:
                    item["tool_calls"] = calls
                else:
                    item.pop("tool_calls", None)
                if item.get("content") or item.get("thinking") or calls:
                    cleaned.append(item)
                continue
            cleaned.append(copy.deepcopy(message))
        return cleaned

    @Property(str, notify=modeChanged)
    def taskMode(self):
        return self._task_mode

    @Property(bool, notify=modeChanged)
    def taskModeLocked(self):
        return bool(self._task_id or self._task_mode_locked)

    @Property(str, notify=modeChanged)
    def productName(self):
        return "Wynxq GUI"

    @Property("QVariantList", notify=planChanged)
    def planSteps(self):
        return [dict(step) for step in self._plan_steps]

    @Property(str, notify=planChanged)
    def planSummary(self):
        if not self._plan_steps:
            return ""
        completed = sum(step["status"] in {"completed", "skipped"} for step in self._plan_steps)
        return f"{completed} of {len(self._plan_steps)} complete"

    @Property(str, notify=contextStateChanged)
    def projectInstructionsSummary(self):
        return self._project_instructions_summary

    @Property(int, notify=contextStateChanged)
    def contextOmittedTurns(self):
        return int(self._context_omitted_turns)

    @Property(str, notify=contextStateChanged)
    def contextCompactionLabel(self):
        count = int(self._context_omitted_turns)
        if not count:
            return ""
        return (f"{count} older turn{'s' if count != 1 else ''} omitted from this model request; "
                "full history is still saved")

    def _refresh_project_instructions(self) -> None:
        fresh = project_instructions.summary(self._working_directory)
        if fresh != self._project_instructions_summary:
            self._project_instructions_summary = fresh
            self.contextStateChanged.emit()
            self.changed.emit()

    def _read_conversation_tokens(self, task_id: str | None = None) -> int:
        getter = getattr(self.store, "conversation_token_usage", None)
        target = str(self._task_id if task_id is None else task_id or "")
        if not target or not callable(getter):
            return 0
        try:
            return max(0, int((getter(target) or {}).get("tokens", 0) or 0))
        except (TypeError, ValueError):
            return 0

    def _reset_usage_context(self) -> None:
        """Use a fresh tracker so leaving a live chat never resets its counter."""
        self._usage = TokenUsageTracker(self.store)
        self._usage.reset()
        self._conversation_tokens = self._read_conversation_tokens()
        self.usageChanged.emit()

    def _finalize_usage(self) -> bool:
        """Record one run and update the cached current-chat total exactly once."""
        if not self._usage.finalize(self._task_id, self._model):
            return False
        metrics = self._usage.metrics
        self._conversation_tokens += max(0, int(metrics.get("tokens", 0) or 0))
        self._conversation_tokens += max(0, int(metrics.get("prompt_tokens", 0) or 0))
        self.usageChanged.emit()
        return True

    @Property(int, notify=usageChanged)
    def liveOutputTokens(self):
        return int(self._usage.live_output_tokens)

    @Property(float, notify=usageChanged)
    def liveTokenRate(self):
        return round(float(self._usage.live_rate), 1)

    @Property(bool, notify=usageChanged)
    def liveTokenRateExact(self):
        return bool(self._usage.live_rate_exact)

    @Property(int, notify=usageChanged)
    def conversationTokens(self):
        return int(self._conversation_tokens)

    @Property("QVariantMap", notify=usageChanged)
    def tokenUsage(self):
        return self._usage.summary

    @Property("QVariantList", notify=usageChanged)
    def tokenUsageDays(self):
        return self._usage.daily

    @Property("QVariantList", notify=usageChanged)
    def tokenUsageModels(self):
        return self._usage.models

    @Slot()
    def refreshTokenUsage(self):
        if self._usage.refresh():
            self.usageChanged.emit()

    @Property(str, notify=endpointChanged)
    def endpointScope(self):
        return endpoint_scope(self._endpoint)

    @Property(str, notify=endpointChanged)
    def endpointScopeLabel(self):
        return {
            "local": "This computer",
            "lan": "Local network",
            "remote": "Remote server",
            "invalid": "Invalid address",
        }.get(endpoint_scope(self._endpoint), "Server")

    @Property(str, notify=endpointChanged)
    def endpointPrivacyHint(self):
        scope = endpoint_scope(self._endpoint)
        if scope == "local":
            return "Ollama runs on this computer."
        if scope == "lan":
            return "Ollama runs on another device on your local network. Chats, files and screenshots used by the model are sent to that device."
        if scope == "remote":
            return "This Ollama server is outside the local network. Use HTTPS or a trusted private tunnel for sensitive chats, files and screenshots."
        return "Enter a complete Ollama server URL."

    @Slot(str, result=bool)
    def selectEndpoint(self, endpoint):
        previous = self._endpoint
        result = super().selectEndpoint(endpoint)
        if result and self._endpoint != previous:
            self.endpointChanged.emit()
        return result

    @Slot(str, result=bool)
    def setEndpoint(self, endpoint):
        previous = self._endpoint
        result = super().setEndpoint(endpoint)
        if result and self._endpoint != previous:
            self.endpointChanged.emit()
        return result

    def _set_project(self, path: str):
        """Switch folders only after the dock accepts losing its current state.

        A dirty editor buffer is owned by the dock. Let that boundary veto the
        transition before updating settings/recent-project history, otherwise a
        refused switch would leave the controller and dock pointing at different
        projects.
        """
        path = str(path or "")
        if path == self._working_directory:
            return True
        if not self.dock.set_project(path):
            return False
        self._working_directory = path
        self.store.set_setting("working_directory", path)
        fresh_instructions = project_instructions.summary(path)
        if fresh_instructions != self._project_instructions_summary:
            self._project_instructions_summary = fresh_instructions
            self.contextStateChanged.emit()
        if path:
            self._recent_projects = [path] + [p for p in self._recent_projects if p != path]
            del self._recent_projects[self.RECENT_PROJECT_LIMIT:]
            self.store.set_setting("recent_projects", self._recent_projects)
            self.dock.suggest("files")
        self.changed.emit()
        return True

    @Slot()
    def chooseProject(self):
        from PySide6.QtWidgets import QFileDialog
        start = self._working_directory or ctx.default_directory()
        path = QFileDialog.getExistingDirectory(None, "Choose a project folder", start)
        if path and self._set_project(path):
            self.toast.emit(f"Working in {ctx.working_directory_label(path)}")

    @Slot(str, result=bool)
    def setTaskMode(self, mode):
        """Choose the mode for a blank task exactly once."""
        mode = str(mode or "").strip().lower()
        if mode not in self.VALID_TASK_MODES or self._busy or self._connecting:
            return False
        if self._task_id or self._task_mode_locked:
            return mode == self._task_mode
        self._task_mode = mode
        self._task_mode_locked = True
        self._emit_mode()
        return True

    @Slot(str)
    def newTaskMode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in self.VALID_TASK_MODES:
            return
        super().newTask()
        self._reset_usage_context()
        self._set_last_task("")
        self._set_plan([], persist=False)
        if self._task_id or self._busy:
            return
        self._task_mode = "chat"
        self._task_mode_locked = False
        if mode == "chat":
            self._emit_mode()
        else:
            self.setTaskMode(mode)

    @Slot()
    def newTask(self):
        super().newTask()
        self._reset_usage_context()
        self._set_last_task("")
        self._set_plan([], persist=False)
        if not self._task_id:
            self._task_mode = "chat"
            self._task_mode_locked = False
            self._emit_mode()

    def _grouped_tasks(self) -> list[dict]:
        """The sidebar's groups, with each task's product on it."""
        groups = super()._grouped_tasks()
        for group in groups:
            group["items"] = [{**task, "mode": self._saved_mode(str(task.get("id", "")))}
                              for task in group["items"]]
        return groups

    @Slot(str)
    def openTask(self, task_id):
        super().openTask(task_id)
        if self._task_id != task_id:
            return
        self._set_last_task(task_id)
        self._task_mode = self._saved_mode(task_id)
        self._task_mode_locked = True
        state = self._active_session()
        if state and state.get("usage") is not None:
            self._usage = state["usage"]
            self._conversation_tokens = int(state.get(
                "conversation_tokens", self._read_conversation_tokens(task_id)))
            self._context_omitted_turns = int(state.get("context_omitted_turns", 0) or 0)
            self._set_plan(state.get("plan_steps", self._saved_plan(task_id)), persist=False)
        else:
            self._reset_usage_context()
            self._context_omitted_turns = 0
            self._set_plan(self._saved_plan(task_id), persist=False)
        self._workspace_checkpoint = self._task_checkpoints.get(task_id)
        if state and state.get("checkpoint"):
            self._workspace_checkpoint = state.get("checkpoint")
        self.usageChanged.emit()
        self.contextStateChanged.emit()
        self.checkpointChanged.emit()
        self._emit_mode()

    def _learn_user_memory(self, text: str) -> int:
        """Quietly persist high-confidence durable facts from an accepted message.

        This path is deliberately independent of model tool calling. A small or
        tool-less local model should still remember a preferred name or a stable
        repo convention. The Markdown memory file remains the source of truth,
        and its normal dedupe/size/privacy rules still apply.
        """
        if not self._memory_enabled or self._task_mode != "work":
            return 0
        stored = 0
        identity_prefixes = ("User prefers to be called ", "User's preferred name is ")
        for candidate in learnable_memories(text, self._working_directory):
            try:
                note = candidate["note"]
                # A preferred name is a single-valued identity slot, not a list
                # of likes. Replace an older name instead of injecting two
                # contradictory names into every future task.
                if candidate["scope"] == "global" and note.startswith(identity_prefixes):
                    existing = self.memory.notes("global")
                    same = any(item.casefold() == note.casefold() for item in existing)
                    if not same:
                        self.memory.forget("User prefers to be called", "global")
                        self.memory.forget("User's preferred name is", "global")
                result = self.memory.remember(
                    note, candidate["scope"], self._working_directory)
            except (OSError, ValueError):
                continue
            stored += int(bool(result.get("stored")))
        if stored:
            self.memoryChanged.emit()
        return stored

    @Slot(str)
    def send(self, text):
        previous_task = self._task_id
        before_messages = len(self._history)
        # Learn only messages the base controller would actually accept. Never
        # turn an offline draft, an empty submit or a click while busy into
        # durable profile data. Learning happens before the run starts so the
        # same turn can benefit from the freshly updated memory if useful.
        accepted_text = str(text).strip()
        accepted = bool(accepted_text and not self._busy and not self._connecting and self._online)
        if accepted:
            self._learn_user_memory(accepted_text)

        was_new = not self._task_id
        if was_new and not self._task_mode_locked:
            self._task_mode = "chat"
            self._task_mode_locked = True
            self._emit_mode()
        super().send(text)
        sent = len(self._history) > before_messages
        if sent:
            self._draft_persist_timer.stop()
            # A newly created task changes the draft key mid-send, so clear both
            # the source slot and the final task slot. The submitted text now
            # belongs to conversation history, not the composer.
            self.store.set_setting(self._draft_key(previous_task), "")
            self.store.set_setting(self._draft_key(self._task_id), "")
            self._set_last_task(self._task_id)
        if was_new and self._task_id:
            self._persist_task_mode()
            self._persist_plan()
            self.modeChanged.emit()

    @Property(bool, notify=checkpointChanged)
    def canUndoRun(self):
        checkpoint = self._workspace_checkpoint
        return bool(
            checkpoint and checkpoint.get("before") and not self._busy
            and checkpoint.get("root") == str(Path(self._working_directory).resolve())
            and checkpoint.get("task") == self._task_id
        )

    @Property(str, notify=checkpointChanged)
    def undoRunSummary(self):
        checkpoint = self._workspace_checkpoint or {}
        count = len(checkpoint.get("before", {}))
        if not count:
            return ""
        return f"Undo this run · {count} file{'s' if count != 1 else ''}"

    def _begin_workspace_checkpoint(self):
        self._workspace_checkpoint = None
        self.checkpointChanged.emit()
        if self._task_mode != "work" or not self._working_directory:
            return
        before = _snapshot_git_workspace(self._working_directory)
        if before is None:
            return
        self._workspace_checkpoint = {
            "root": str(Path(self._working_directory).resolve()),
            "task": self._task_id,
            "before_all": before,
        }

    def _finalize_workspace_checkpoint(self):
        checkpoint = self._workspace_checkpoint
        if not checkpoint or "before_all" not in checkpoint:
            return
        if checkpoint.get("root") != str(Path(self._working_directory).resolve()):
            self._workspace_checkpoint = None
            self.checkpointChanged.emit()
            self.changed.emit()
            return
        after = _snapshot_git_workspace(checkpoint["root"])
        if after is None:
            self._workspace_checkpoint = None
            self.changed.emit()
            return
        before, after = _checkpoint_delta(checkpoint.pop("before_all"), after)
        if not before:
            self._workspace_checkpoint = None
        else:
            checkpoint["before"] = before
            checkpoint["after"] = after
        self.checkpointChanged.emit()
        self.changed.emit()

    @Slot()
    def undoLastRun(self):
        if self._busy:
            self.toast.emit("Stop the current run before undoing it.")
            return
        if not self.canUndoRun:
            self.toast.emit("There is no safe agent checkpoint to undo.")
            return
        checkpoint = self._workspace_checkpoint
        try:
            count = _restore_workspace_checkpoint(
                checkpoint["root"], checkpoint["before"], checkpoint["after"])
        except (OSError, RuntimeError) as exc:
            self.toast.emit(str(exc))
            return
        viewer_path = self.dock.filePath
        self._workspace_checkpoint = None
        self.checkpointChanged.emit()
        self.dock.refreshFiles()
        self.dock.refreshChanges()
        if viewer_path and not self.dock.fileModified:
            self.dock.openFile(viewer_path)
        self.changed.emit()
        self.toast.emit(f"Undid agent changes in {count} file{'s' if count != 1 else ''}.")

    def _finalize_checkpoint_for_run(self, task_id: str, state: dict) -> None:
        checkpoint = state.get("checkpoint")
        if not checkpoint or "before_all" not in checkpoint:
            return
        after = _snapshot_git_workspace(checkpoint["root"])
        if after is None:
            state["checkpoint"] = None
            return
        before, after = _checkpoint_delta(checkpoint.pop("before_all"), after)
        state["checkpoint"] = None if not before else {
            **checkpoint, "before": before, "after": after,
        }
        if state["checkpoint"]:
            self._task_checkpoints[task_id] = state["checkpoint"]
        else:
            self._task_checkpoints.pop(task_id, None)
        if task_id == self._task_id:
            self._workspace_checkpoint = state["checkpoint"]
            self.checkpointChanged.emit()
            self.changed.emit()

    def _settle_plan_for_run(self, task_id: str, state: dict, outcome: str) -> None:
        plan = self._normalise_plan(state.get("plan_steps", []))
        changed = False
        for item in plan:
            if item["status"] == "in_progress":
                item["status"] = ("failed" if outcome == "failed" else
                                  "pending" if outcome == "cancelled" else "completed")
                changed = True
        if changed:
            state["plan_steps"] = plan
            self.store.set_setting(self._plan_key(task_id), plan)
            if task_id == self._task_id:
                self._set_plan(plan, persist=False)

    def _start_run(self, history):
        self._begin_workspace_checkpoint()
        checkpoint = self._workspace_checkpoint
        self._refresh_project_instructions()
        self._context_omitted_turns = 0
        self.contextStateChanged.emit()

        usage = TokenUsageTracker(self.store)
        usage.reset()
        self._usage = usage
        self.usageChanged.emit()

        mode = self._task_mode
        project = self._working_directory
        state = self._launch_run(
            history, PlanningAgentEngine,
            tools_allowed=mode == "work",
            desktop_enabled=mode == "work" and self.desktopEnabled,
            project=project,
            extras={
                "usage": usage,
                "conversation_tokens": self._read_conversation_tokens(self._task_id),
                "context_omitted_turns": 0,
                "plan_steps": [dict(step) for step in self._plan_steps],
                "checkpoint": checkpoint,
                "task_mode": mode,
            },
        )
        self._workspace_checkpoint = state.get("checkpoint")

    def _on_event(self, event, task_id=None):
        task_id = str(task_id or self._task_id or "")
        state = self._run_sessions.get(task_id)
        kind = event.get("type")

        if state and kind == "context_compacted":
            fresh = max(0, int(event.get("omitted_turns", 0) or 0))
            state["context_omitted_turns"] = fresh
            if task_id == self._task_id:
                self._context_omitted_turns = fresh
                self.contextStateChanged.emit()
                self.changed.emit()
            return

        if kind == "tool_start" and event.get("name") == "update_plan":
            fresh = self._normalise_plan(event.get("args", {}).get("steps", []))
            explanation = str(event.get("args", {}).get("explanation", "")).strip()
            status = explanation[:120] or "Planning"
            if state:
                state["plan_steps"] = fresh
                self.store.set_setting(self._plan_key(task_id), fresh)
                state["status"] = status
                if task_id == self._task_id:
                    self._set_plan(fresh, persist=False)
                    self._status = status
                    self.changed.emit()
            else:
                # Direct foreground events (preview/small hosts/tests) still
                # behave exactly like the pre-concurrency controller.
                self._set_plan(fresh)
                self._status = status
                self.changed.emit()
            return
        if kind == "tool_end" and event.get("name") == "update_plan":
            return

        usage_dirty = False
        usage = state.get("usage") if state else self._usage
        if kind in ("token", "thinking"):
            usage_dirty = usage.stream(event.get("text", ""))
            if state and usage.live_rate > 0:
                state["token_rate"] = f"{usage.live_rate:.1f} tok/s"
        elif kind == "metrics":
            usage_dirty = usage.exact_metrics(event)

        super()._on_event(event, task_id)
        if state and task_id == self._task_id:
            self._usage = usage
            if usage.live_rate > 0:
                self._token_rate = f"{usage.live_rate:.1f} tok/s"
        if usage_dirty and (not state or task_id == self._task_id):
            self.usageChanged.emit()

    def _run_done(self, history, task_id=None):
        task_id = str(task_id or self._task_id or "")
        state = self._run_sessions.get(task_id)
        if state:
            job = state.get("job")
            stopped = bool(job and job.cancel.is_set())
            outcome = "cancelled" if stopped else (
                "failed" if state.get("error") else "completed")
            usage = state.get("usage")
            if usage and usage.finalize(task_id, state.get("model", "")):
                metrics = usage.metrics
                state["conversation_tokens"] = int(state.get("conversation_tokens", 0))
                state["conversation_tokens"] += max(0, int(metrics.get("tokens", 0) or 0))
                state["conversation_tokens"] += max(0, int(metrics.get("prompt_tokens", 0) or 0))
            cleaned = self._strip_plan_history(history)
            super()._run_done(cleaned, task_id)
            self._finalize_checkpoint_for_run(task_id, state)
            self._settle_plan_for_run(task_id, state, outcome)
            if task_id == self._task_id:
                self._usage = usage or self._usage
                self._conversation_tokens = int(state.get(
                    "conversation_tokens", self._read_conversation_tokens(task_id)))
                self.usageChanged.emit()
            return
        super()._run_done(self._strip_plan_history(history), task_id)

    def _run_failed(self, message, task_id=None):
        task_id = str(task_id or self._task_id or "")
        state = self._run_sessions.get(task_id)
        if state:
            usage = state.get("usage")
            if usage:
                usage.finalize(task_id, state.get("model", ""))
            super()._run_failed(message, task_id)
            self._finalize_checkpoint_for_run(task_id, state)
            self._settle_plan_for_run(task_id, state, "failed")
            if task_id == self._task_id:
                self._usage = usage or self._usage
                self._conversation_tokens = self._read_conversation_tokens(task_id)
                self.usageChanged.emit()
            return
        super()._run_failed(message, task_id)

    @Slot(str)
    def deleteTask(self, task_id):
        task_id = str(task_id or "")
        if task_id:
            self.store.set_setting(self._draft_key(task_id), "")
            if str(self.store.get_setting(self.LAST_TASK_KEY, "") or "") == task_id:
                self._set_last_task("")
        super().deleteTask(task_id)

    @Slot()
    def clearTask(self):
        task_id = self._task_id
        super().clearTask()
        if task_id and self._task_id == task_id:
            self._reset_usage_context()
            self._set_plan([])

    @Slot()
    def duplicateTask(self):
        if self._busy or not self._task_id:
            return
        mode = self._task_mode
        plan = [dict(step) for step in self._plan_steps]
        previous = self._task_id
        super().duplicateTask()
        if self._task_id and self._task_id != previous:
            self._task_mode = mode
            self._task_mode_locked = True
            self._set_plan(plan)
            self._persist_task_mode()
            self._emit_mode()

    @Slot(str)
    def duplicateTaskById(self, task_id):
        if self._busy:
            return
        mode = self._saved_mode(task_id)
        plan = self._saved_plan(task_id)
        previous = self._task_id
        super().duplicateTaskById(task_id)
        if self._task_id and self._task_id != previous:
            self._task_mode = mode
            self._task_mode_locked = True
            self._set_plan(plan)
            self._persist_task_mode()
            self._emit_mode()

    @Slot(int)
    def branchFrom(self, row):
        if self._busy or not self._task_id:
            return
        mode = self._task_mode
        plan = [dict(step) for step in self._plan_steps]
        previous = self._task_id
        super().branchFrom(row)
        if self._task_id and self._task_id != previous:
            self._task_mode = mode
            self._task_mode_locked = True
            self._set_plan(plan)
            self._persist_task_mode()
            self._emit_mode()
    def shutdown(self):
        """Stop the workspace exactly once, even when a host calls twice.

        Snapshot/demo controllers are rotated during rendering, so an older
        controller may already have closed its store when process cleanup calls
        shutdown again. Production close paths also benefit from idempotence.
        """
        if getattr(self, "_workspace_shutdown", False):
            return
        if hasattr(self, "_draft_persist_timer"):
            self._draft_persist_timer.stop()
        self._persist_current_draft()
        self._set_last_task(self._task_id)
        self._workspace_shutdown = True
        super().shutdown()

