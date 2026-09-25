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
from .usage import TokenUsageTracker
from .endpoint_policy import (
    WorkspaceOllamaClient, endpoint_scope, validate_workspace_endpoint,
)

# Compatibility seam: callers historically patched workspace.OllamaClient.
# Keep that name live while the concrete default now comes from endpoint_policy.
OllamaClient = WorkspaceOllamaClient
from .planning import PLAN_STATES, PlanningAgentEngine, _install_plan_tool
from .workspace_checkpoint import (
    _checkpoint_delta, _restore_workspace_checkpoint, _snapshot_git_workspace,
)
from . import workspace_session_ops as _session_ops
from . import workspace_usage_ops as _usage_ops
from . import workspace_task_ops as _task_ops
from . import workspace_run_ops as _run_ops


class WorkspaceController(Controller):
    OLLAMA_CLIENT = None
    PLANNING_ENGINE = None

    def _ollama_client(self, endpoint):
        client_type = self.OLLAMA_CLIENT or OllamaClient
        return client_type(endpoint)

    def _planning_engine_class(self):
        return self.PLANNING_ENGINE or PlanningAgentEngine
    modeChanged = Signal()
    endpointChanged = Signal()
    planChanged = Signal()
    usageChanged = Signal()
    contextStateChanged = Signal()
    checkpointChanged = Signal()
    VALID_TASK_MODES = {"chat", "work"}
    LAST_TASK_KEY = "workspace:last_task"
    ACTIVE_RUNS_KEY = "workspace:active_runs"
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


    # ------------------------------------------------ behavior slices
    # Keep one stable QML facade while implementation is owned by focused modules.
    # workspace session, draft, mode, and plan persistence
    _emit_mode = _session_ops._emit_mode
    _mode_key = _session_ops._mode_key
    _plan_key = _session_ops._plan_key
    _draft_key = _session_ops._draft_key
    _set_last_task = _session_ops._set_last_task
    _persist_current_draft = _session_ops._persist_current_draft
    _restore_workspace_session = _session_ops._restore_workspace_session
    _save_draft = _session_ops._save_draft
    _restore_draft = _session_ops._restore_draft
    setDraft = _session_ops.setDraft
    _saved_mode = _session_ops._saved_mode
    _normalise_plan = _session_ops._normalise_plan
    _saved_plan = _session_ops._saved_plan
    _recover_interrupted_plan = _session_ops._recover_interrupted_plan
    _journal_active_run = _session_ops._journal_active_run
    _recover_interrupted_runs = _session_ops._recover_interrupted_runs
    _persist_task_mode = _session_ops._persist_task_mode
    _persist_plan = _session_ops._persist_plan
    _set_plan = _session_ops._set_plan
    _settle_plan = _session_ops._settle_plan
    _strip_plan_history = _session_ops._strip_plan_history
    _refresh_project_instructions = _session_ops._refresh_project_instructions

    # workspace usage, endpoint, and project operations
    _read_conversation_tokens = _usage_ops._read_conversation_tokens
    _reset_usage_context = _usage_ops._reset_usage_context
    _finalize_usage = _usage_ops._finalize_usage
    refreshTokenUsage = _usage_ops.refreshTokenUsage
    selectEndpoint = _usage_ops.selectEndpoint
    setEndpoint = _usage_ops.setEndpoint
    _set_project = _usage_ops._set_project
    chooseProject = _usage_ops.chooseProject

    # workspace task and memory lifecycle operations
    setTaskMode = _task_ops.setTaskMode
    newTaskMode = _task_ops.newTaskMode
    newTask = _task_ops.newTask
    _grouped_tasks = _task_ops._grouped_tasks
    openTask = _task_ops.openTask
    send = _task_ops.send
    deleteTask = _task_ops.deleteTask
    clearTask = _task_ops.clearTask
    duplicateTask = _task_ops.duplicateTask
    duplicateTaskById = _task_ops.duplicateTaskById
    branchFrom = _task_ops.branchFrom
    shutdown = _task_ops.shutdown

    # workspace checkpoint and run orchestration
    _begin_workspace_checkpoint = _run_ops._begin_workspace_checkpoint
    _finalize_workspace_checkpoint = _run_ops._finalize_workspace_checkpoint
    undoLastRun = _run_ops.undoLastRun
    _finalize_checkpoint_for_run = _run_ops._finalize_checkpoint_for_run
    _settle_plan_for_run = _run_ops._settle_plan_for_run
    _start_run = _run_ops._start_run
    _on_event = _run_ops._on_event
    _run_done = _run_ops._run_done
    _run_failed = _run_ops._run_failed

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

    @Property("QVariantMap", notify=usageChanged)
    def tokenUsageOverview(self):
        return self._usage.overview

    @Property("QVariantList", notify=usageChanged)
    def tokenUsageDays(self):
        return self._usage.daily

    @Property("QVariantList", notify=usageChanged)
    def tokenUsageModels(self):
        return self._usage.models

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


__all__ = ['WorkspaceController']
