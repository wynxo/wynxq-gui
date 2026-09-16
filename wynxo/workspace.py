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
import ipaddress
import time
from urllib.parse import urlsplit

from PySide6.QtCore import Property, QTimer, Signal, Slot

from . import context as ctx
from . import context_budget
from . import engine as engine_module
from . import project_context
from . import project_instructions
from .controller import Controller, AgentEngine, OllamaClient, _blank_metrics
from .memory_learning import learnable_memories
from .usage import TokenUsageTracker


PLAN_STATES = {"pending", "in_progress", "completed", "failed", "skipped"}
_PLAN_PROMPT_MARKER = "Use update_plan for genuine multi-step work"


def _install_plan_tool() -> None:
    """Add a UI-only planning tool to the existing local agent loop once.

    Keeping it in the workspace layer means the generic engine stays reusable.
    The engine still validates the schema and returns a normal tool result; the
    WorkspaceController consumes the corresponding events instead of showing
    them as desktop activity.
    """
    if "update_plan" not in engine_module._SCHEMAS:
        step = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 48},
                "title": {"type": "string", "minLength": 1, "maxLength": 180},
                "status": {"type": "string", "enum": sorted(PLAN_STATES)},
            },
            "required": ["id", "title", "status"],
            "additionalProperties": False,
        }
        tool = engine_module._tool(
            "update_plan",
            "Publish or update the concise execution plan shown in Wynxq GUI's Plan panel. "
            "Use only for work that needs multiple concrete actions. Reuse stable step IDs "
            "and update statuses as work progresses.",
            {
                "steps": {"type": "array", "minItems": 2, "maxItems": 8, "items": step},
                "explanation": {"type": "string", "maxLength": 240},
            },
            ["steps"],
        )
        engine_module.TOOLS.insert(0, tool)
        engine_module._SCHEMAS["update_plan"] = tool["function"]["parameters"]
        engine_module._NONVISUAL.add("update_plan")
        engine_module.LOW_RISK.add("update_plan")

    if _PLAN_PROMPT_MARKER not in engine_module._SYSTEM:
        engine_module._SYSTEM += (
            "\nUse update_plan for genuine multi-step work that needs two or more concrete actions. "
            "Publish a short plan before the first substantive action, keep the same step IDs, "
            "mark exactly one current step in_progress when possible, and update the plan as steps "
            "complete, fail, or are skipped. Do not create a plan for a simple answer or one-step action."
        )


class PlanningAgentEngine(AgentEngine):
    """AgentEngine with planning, bounded history and project orientation."""

    def run(self, *args, **kwargs):
        # The complete conversation is the archive. Build a temporary recent
        # view for this inference, then append only newly generated messages
        # back onto the untouched archive. This applies to Chat and Work.
        if args:
            full_history = copy.deepcopy(list(args[0]))
        else:
            full_history = copy.deepcopy(list(kwargs.get("messages", [])))
        fit = context_budget.fit_history(full_history, kwargs.get("num_ctx", 16384))
        inference_messages = fit.messages

        emit = args[4] if len(args) > 4 else kwargs.get("emit")
        if fit.compacted and callable(emit):
            emit({"type": "context_compacted", "omitted_turns": fit.omitted_turns,
                  "estimated_tokens": fit.estimated_tokens})

        desktop = self.desktop
        tools_allowed = bool(kwargs.get("tools_allowed", True))
        project = str(kwargs.get("project", "") or "")
        if tools_allowed and desktop is not None and project:
            inference_messages = project_context.inject(inference_messages, project)
            inference_messages = project_instructions.inject(inference_messages, project)

        if args:
            run_args = (inference_messages,) + args[1:]
            run_kwargs = kwargs
        else:
            run_args = args
            run_kwargs = {**kwargs, "messages": inference_messages}

        if desktop is None or not tools_allowed:
            result = super().run(*run_args, **run_kwargs)
        else:
            original_execute = desktop.execute

            def execute(name, arguments, cancel=None):
                if name == "update_plan":
                    return {"ok": True, "steps": len(arguments.get("steps", []))}
                return original_execute(name, arguments, cancel)

            # Runs are serialized by Controller; this temporary adapter exists
            # only on the worker thread for the lifetime of this generation.
            desktop.execute = execute
            try:
                result = super().run(*run_args, **run_kwargs)
            finally:
                desktop.execute = original_execute

        # Strip generated system context before finding the engine's new tail.
        result = project_instructions.strip(project_context.strip(result))
        fitted = project_instructions.strip(project_context.strip(inference_messages))
        return context_budget.merge_generated(full_history, fitted, result)


def validate_workspace_endpoint(endpoint: str) -> str:
    """Validate an explicit Ollama origin without forcing it to loopback."""
    value = str(endpoint or "").strip()
    if not value or any(ord(c) < 33 for c in value):
        raise ValueError("Enter an Ollama URL such as http://192.168.1.50:11434")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid Ollama URL") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Ollama URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("Ollama URL needs a host name or IP address")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Put credentials in a reverse proxy, not in the Ollama URL")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Use the Ollama server origin only, with no path, query, or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Ollama port must be between 1 and 65535")

    host = parsed.hostname
    try:
        address = ipaddress.ip_address(host)
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    except ValueError:
        host = host.rstrip(".").lower()
        if not host or len(host) > 253 or any(len(label) > 63 for label in host.split(".")):
            raise ValueError("Invalid Ollama host name")
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-._")
        if any(ch not in allowed for ch in host):
            raise ValueError("Invalid Ollama host name")
    return f"{parsed.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def endpoint_scope(endpoint: str) -> str:
    """Human-facing scope for the endpoint status shown by the UI."""
    try:
        parsed = urlsplit(validate_workspace_endpoint(endpoint))
        host = parsed.hostname or ""
        if host == "localhost":
            return "local"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            lowered = host.lower()
            if lowered.endswith((".local", ".lan", ".home", ".home.arpa", ".internal")):
                return "lan"
            return "remote"
        if address.is_loopback:
            return "local"
        if address.is_private or address.is_link_local:
            return "lan"
        return "remote"
    except Exception:
        return "invalid"


class WorkspaceController(Controller):
    modeChanged = Signal()
    endpointChanged = Signal()
    planChanged = Signal()
    usageChanged = Signal()
    contextStateChanged = Signal()
    VALID_TASK_MODES = {"chat", "work"}
    LAST_TASK_KEY = "workspace:last_task"
    DRAFT_KEY_PREFIX = "workspace:draft:"

    def __init__(self, *args, **kwargs):
        self._task_mode = "chat"
        self._task_mode_locked = False
        self._plan_steps: list[dict] = []
        _install_plan_tool()
        # OllamaClient resolves this name at construction time. Swap only the
        # endpoint policy; redirects and environment proxies remain disabled by
        # the transport itself.
        engine_module.validate_endpoint = validate_workspace_endpoint
        super().__init__(*args, **kwargs)
        self._usage = TokenUsageTracker(self.store)
        self._workspace_shutdown = False
        self._project_instructions_summary = project_instructions.summary(self._working_directory)
        self._context_omitted_turns = 0
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

    @Property(int, notify=usageChanged)
    def liveOutputTokens(self):
        return int(self._usage.live_output_tokens)

    @Property(float, notify=usageChanged)
    def liveTokenRate(self):
        return round(float(self._usage.live_rate), 1)

    @Property("QVariantMap", notify=usageChanged)
    def tokenUsage(self):
        return self._usage.summary

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
    def setEndpoint(self, endpoint):
        result = super().setEndpoint(endpoint)
        if result:
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
        if mode not in self.VALID_TASK_MODES or self._busy:
            return
        super().newTask()
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
        if self._busy:
            super().newTask()
            return
        super().newTask()
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
        self._set_plan(self._saved_plan(task_id), persist=False)
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

    def _start_run(self, history):
        self._refresh_project_instructions()
        if self._context_omitted_turns:
            self._context_omitted_turns = 0
            self.contextStateChanged.emit()
        self._busy = True
        self._clear_error()
        self._status = "Thinking"
        self._token_rate = "—"
        self._think_started = 0.0
        self._think_seconds = 0.0
        self._turn_had_message = False
        self._activity = []
        self._session_auto = False
        self._run_started = time.monotonic()
        self._run_metrics = _blank_metrics()
        self._usage.reset()
        self.usageChanged.emit()
        self.dock.begin_turn(self._task_title if self._task_title != "New task" else "Turn")
        self.activityChanged.emit()
        self._refresh_tasks()
        self.changed.emit()
        engine = PlanningAgentEngine(OllamaClient(self._endpoint), self.desktop, self._memory_for_run())
        model = self._model
        enabled = self._task_mode == "work" and self.desktopEnabled
        # Chat is chat. A Chat task never reaches the shell, the desktop or the
        # project — not "asks first", not "only safe commands": the tools are
        # not offered to the model at all, so there is nothing to approve.
        tools_allowed = self._task_mode == "work"
        think = self._think
        num_ctx, temperature = self._num_ctx, self._temperature
        keep_alive, max_steps = self._keep_alive, self._max_steps
        project = self._working_directory
        permission_snapshot = self._permission_mode

        # Permission mode is deliberately live. The user can tighten or relax
        # an active task from the UI; the engine re-reads this provider before
        # every action instead of retaining the mode that happened to be set
        # when generation started. A manual "allow all in this task" decision
        # belongs to the old mode, so changing modes revokes it before the next
        # action is evaluated.
        def permission_mode():
            nonlocal permission_snapshot
            current = self._permission_mode
            if current != permission_snapshot:
                self._session_auto = False
                permission_snapshot = current
            return current

        self._run_job = self._job(
            lambda cancel, emit: engine.run(
                list(history), model, enabled, cancel, emit, think=think,
                max_steps=max_steps, num_ctx=num_ctx, temperature=temperature,
                keep_alive=keep_alive, permission_mode=permission_mode,
                project=project, confirm=self._confirm_action,
                tools_allowed=tools_allowed),
            self._run_done, self._run_failed, self._on_event,
        )

    def _on_event(self, event):
        kind = event.get("type")
        if kind == "context_compacted":
            fresh_omitted = max(0, int(event.get("omitted_turns", 0) or 0))
            if fresh_omitted != self._context_omitted_turns:
                self._context_omitted_turns = fresh_omitted
                self.contextStateChanged.emit()
            self.changed.emit()
            return
        if kind == "tool_start" and event.get("name") == "update_plan":
            self._set_plan(event.get("args", {}).get("steps", []))
            explanation = str(event.get("args", {}).get("explanation", "")).strip()
            self._status = explanation[:120] or "Planning"
            self.changed.emit()
            return
        if kind == "tool_end" and event.get("name") == "update_plan":
            return

        usage_dirty = False
        if kind in ("token", "thinking"):
            usage_dirty = self._usage.stream(event.get("text", ""))
            if self._usage.live_rate > 0:
                self._token_rate = f"{self._usage.live_rate:.1f} tok/s"
        elif kind == "metrics":
            usage_dirty = self._usage.exact_metrics(event)

        super()._on_event(event)
        if usage_dirty:
            self.usageChanged.emit()

    def _run_done(self, history):
        stopped = self._run_job is not None and self._run_job.cancel.is_set()
        outcome = "cancelled" if stopped else ("failed" if self._error else "completed")
        usage_recorded = self._usage.finalize(self._task_id, self._model)
        super()._run_done(self._strip_plan_history(history))
        self._settle_plan(outcome)
        if usage_recorded:
            self.usageChanged.emit()

    def _run_failed(self, message):
        usage_recorded = self._usage.finalize(self._task_id, self._model)
        super()._run_failed(message)
        self._settle_plan("failed")
        if usage_recorded:
            self.usageChanged.emit()

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

