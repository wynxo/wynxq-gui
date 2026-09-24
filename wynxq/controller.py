"""Qt bridge. Network and desktop work never block the GUI thread.

The controller owns five separate pieces of state that the UI reads
independently: conversation state (``Messages`` + history), Ollama state
(catalogue, capabilities, connection), desktop state (permission mode, backend,
pending approvals), long-term memory (``memory.md``, read into every run) and
runtime configuration (presets and generation options).
Long operations run on ``Job`` threads and report back through Qt signals.
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
    CaptureVisibility, Job, _RunDesktop, _StoredTokens, _blank_metrics, _bounded_float,
    _bounded_int, _human_bytes,
)
from . import controller_server_ops as _server_ops
from . import controller_task_ops as _task_ops
from . import controller_context_ops as _context_ops
from . import controller_generation_ops as _generation_ops
from . import controller_permission_ops as _permission_ops
from . import controller_event_ops as _event_ops
from . import controller_misc_ops as _misc_ops


__all__ = ["Controller"]


class Controller(QObject):
    # None means use the module-level OllamaClient at call time. Tests and
    # embedders can still replace controller.OllamaClient; product subclasses
    # may inject a different policy-specific client class explicitly.
    OLLAMA_CLIENT = None

    changed = Signal()
    tasksChanged = Signal()
    activityChanged = Signal()
    attachmentsChanged = Signal()
    draftChanged = Signal()
    regionChanged = Signal()
    paletteChanged = Signal()
    catalogChanged = Signal()
    permissionChanged = Signal()
    memoryChanged = Signal()
    toast = Signal(str)
    focusComposer = Signal()
    quickBarRequested = Signal()
    browserNavigateRequested = Signal(str)
    stopRequested = Signal()
    scrollToEnd = Signal()

    THEMES = {
        "Platinum": "#e9e3d6",
        "Ember": "#e8865a",
        "Ion": "#87a9f0",
        "Mint": "#8fd6b0",
        "Violet": "#b6a2f5",
    }
    # Palettes shipped before 1.0 map onto the closest current accent.
    LEGACY_THEMES = {"Obsidian": "Platinum", "Ice": "Ion", "Amber": "Ember", "Rose": "Violet"}

    RUNTIME_PRESETS = {
        "Fast": {"num_ctx": 8192, "temperature": 0.35, "keep_alive": "2m", "max_steps": 12},
        "Balanced": {"num_ctx": 16384, "temperature": 0.7, "keep_alive": "5m", "max_steps": 20},
        "Deep": {"num_ctx": 32768, "temperature": 0.8, "keep_alive": "15m", "max_steps": 40},
    }
    RUNTIME_HINTS = {
        "Fast": "Short context, low variation. Answers start sooner.",
        "Balanced": "The everyday default for chat and desktop work.",
        "Deep": "Long context and a bigger action budget for involved tasks.",
        "Custom": "Your own context, temperature, keep-alive and action budget.",
    }
    DENSITIES = ("Comfortable", "Compact")
    # A permission prompt that is never answered must fail closed.
    PERMISSION_TIMEOUT = 180.0

    def __init__(self, store=None, desktop=None, autoconnect=True, memory=None):
        """Create the controller, wiring store, desktop, memory and the default task list."""
        super().__init__()
        self.store = store or Store()
        self.desktop = desktop or DesktopController(tokens=_StoredTokens(self.store))
        self.messages = Messages(self)
        self.dock = DockController(store=self.store, parent=self)
        self.dock.toast.connect(self.toast)
        self.dock.contextChanged.connect(self.changed)
        setting = self.store.get_setting
        self._default_endpoint = str(setting("endpoint", "http://127.0.0.1:11434") or
                                     "http://127.0.0.1:11434").strip().rstrip("/")
        self._default_model = str(setting("model", "qwen3.8:27b") or "qwen3.8:27b").strip()
        self._endpoint = self._default_endpoint
        self._model = self._default_model
        raw_profiles = setting("ollama_endpoints", []) or []
        self._endpoint_profiles = []
        for raw in raw_profiles if isinstance(raw_profiles, list) else []:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url", "") or "").strip().rstrip("/")
            if not url or any(item["url"] == url for item in self._endpoint_profiles):
                continue
            label = " ".join(str(raw.get("name", "") or "").split())[:32] or self._endpoint_label(url)
            self._endpoint_profiles.append({"name": label, "url": url})
        if not any(item["url"] == self._default_endpoint for item in self._endpoint_profiles):
            self._endpoint_profiles.insert(0, {"name": "Main", "url": self._default_endpoint})
        self.store.set_setting("ollama_endpoints", self._endpoint_profiles)
        self._think = setting("think", False)
        self._reduced_motion = setting("reduced_motion", False)
        self._system_font = bool(setting("system_font", False))
        self._density = setting("density", "Comfortable")
        if self._density not in self.DENSITIES:
            self._density = "Comfortable"
        self._theme = setting("theme", "Platinum")
        self._theme = self.LEGACY_THEMES.get(self._theme, self._theme)
        if self._theme not in self.THEMES:
            self._theme = "Platinum"
        self._accent = self._normalise_accent(setting("accent", self.THEMES[self._theme])) or self.THEMES[self._theme]
        self._solid_background = bool(setting("solid_background", True))
        self._notifications = bool(setting("notifications", True))
        self._tray_enabled = bool(setting("tray", False))
        self._num_ctx = _bounded_int(setting("num_ctx", 16384), 2048, 131072, 16384)
        self._temperature = _bounded_float(setting("temperature", 0.7), 0.0, 2.0, 0.7)
        self._keep_alive = str(setting("keep_alive", "5m")).strip()[:32] or "5m"
        self._max_steps = _bounded_int(setting("max_steps", 20), 1, 100, 20)
        self._runtime_preset = str(setting("runtime_preset", "Balanced"))
        if self._runtime_preset not in self.RUNTIME_PRESETS and self._runtime_preset != "Custom":
            self._runtime_preset = "Custom"
        self._permission_mode = normalise_mode(setting("permission_mode", SAFE))
        # A database written before the ladder existed stored "ask"; rewrite it
        # once so the setting on disk means what the app now shows.
        if setting("permission_mode", SAFE) != self._permission_mode:
            self.store.set_setting("permission_mode", self._permission_mode)
        # Memory belongs beside the history it accompanies, so a store kept in a
        # temporary folder gets a temporary memory file rather than the real one.
        database = getattr(self.store, "path", None)
        self.memory = memory or Memory(Path(database).parent / "memory.md" if database else None)
        self._memory_enabled = bool(setting("memory_enabled", True))
        self._reference_chat_history = bool(setting("reference_chat_history", True))
        self._favorites = [str(m) for m in (setting("favorite_models", []) or []) if str(m)]
        self._recent_models = [str(m) for m in (setting("recent_models", []) or []) if str(m)]
        self._working_directory = str(setting("working_directory", "") or "")
        self._recent_projects = [str(p) for p in (setting("recent_projects", []) or []) if str(p)]
        self._sidebar_width = _bounded_int(setting("sidebar_width", 248), 200, 400, 248)
        self._sidebar_collapsed = bool(setting("sidebar_collapsed", False))
        self._onboarded = bool(setting("onboarded", False))
        self._run_metrics = _blank_metrics()
        self._models: list[str] = []
        self._catalog: list[dict] = []
        self._loaded_models: list[str] = []
        self._model_capabilities: list[str] = []
        self._model_context_length = 0
        self._capability_probe_active = False
        self._capability_probe_generation = 0
        self._capability_error = ""
        self._online = False
        self._busy = False
        self._connecting = False
        self._pulling = False
        self._pull_progress = ""
        self._pull_percent = 0.0
        self._status = "Ready when you are"
        self._error = ""
        self._error_title = ""
        self._error_actions: list[dict] = []
        self._activity: list[dict] = []
        self._attachments: list[dict] = []
        # What you had typed, per task, so moving between them loses nothing.
        self._draft_text = ""
        self._drafts: dict[str, tuple[str, list[dict]]] = {}
        self._history: list[dict] = []
        self._task_id = ""
        self._task_title = "New task"
        self._token_rate = "—"
        self._think_started = 0.0
        self._think_seconds = 0.0
        self._search = ""
        self._tasks = self.store.list_conversations()
        self._desktop_status = self.desktop.status()
        # A global stop shortcut fires on the portal's own thread. Emitting a
        # signal hands it to the GUI thread, which is the only one allowed to
        # touch the run.
        self.stopRequested.connect(self.stop)
        self.browserNavigateRequested.connect(self._navigate_builtin_browser)
        if hasattr(self.desktop, "set_stop_handler"):
            self.desktop.set_stop_handler(self.stopRequested.emit)
        self._jobs: set[Job] = set()
        self._title_generating: set[str] = set()
        self._title_jobs: dict[str, Job] = {}
        self._memory_learning_jobs: dict[str, Job] = {}
        self._model_capability_cache: dict[tuple[str, str], dict] = {}
        self._run_sessions = {}
        self._run_job: Job | None = None
        self._pull_job: Job | None = None
        self._catalog_probe_generation = 0
        self._endpoint_catalog_cache = {}
        self._probe_active = False
        self._turn_had_message = False
        self._run_started = 0.0
        self._window_active = True
        self._pending_permission: dict | None = None
        self._permission_event = threading.Event()
        self._permission_answer = False
        self._session_auto = False
        self._capture_busy = False
        self._overlay_promotion_active = False
        self._overlay_promotion_job = None
        self._overlay_visible = False
        self._capture_visibility = CaptureVisibility(self)
        self._region: dict = {}
        self._code_palette = dict(md.DEFAULT_PALETTE)
        self._html_palette = dict(md.HTML_PALETTE)
        self._history_tokens = 0
        self._resident_models: list[dict] = []
        self.attachmentsChanged.connect(self.dock.refresh_context)
        if self._working_directory:
            self.dock.set_project(self._working_directory)
        if autoconnect:
            self.refreshModels()

    # ---------------------------------------------------------------- jobs
    def _job(self, fn, result=None, failure=None, event=None):
        job = Job(fn, self)
        if result:
            job.result.connect(result)
        job.failed.connect(failure or self._show_error)
        if event:
            job.event.connect(event)
        job.finished.connect(lambda: self._forget_job(job))
        self._jobs.add(job)
        job.start()
        return job

    def _forget_job(self, job):
        self._jobs.discard(job)
        job.deleteLater()

    def _ollama_client(self, endpoint):
        client_type = self.OLLAMA_CLIENT or OllamaClient
        return client_type(endpoint)


    # ------------------------------------------------ behavior slices
    # QML keeps one stable Controller facade; implementation lives in focused
    # modules so model, task, context, run, and presentation concerns evolve
    # independently without growing another god object source file.
    # server/model/runtime operations
    _endpoint_label = _server_ops._endpoint_label
    _remember_endpoint_profile = _server_ops._remember_endpoint_profile
    addEndpointProfile = _server_ops.addEndpointProfile
    removeEndpointProfile = _server_ops.removeEndpointProfile
    setDefaultEndpoint = _server_ops.setDefaultEndpoint
    selectEndpoint = _server_ops.selectEndpoint
    _refresh_tasks = _server_ops._refresh_tasks
    _refresh_model_capabilities = _server_ops._refresh_model_capabilities
    _decorate_catalog = _server_ops._decorate_catalog
    _catalog_entry = _server_ops._catalog_entry
    refreshModels = _server_ops.refreshModels
    setModel = _server_ops.setModel
    toggleFavoriteModel = _server_ops.toggleFavoriteModel
    deleteModel = _server_ops.deleteModel
    _persist_runtime = _server_ops._persist_runtime
    applyRuntimePreset = _server_ops.applyRuntimePreset
    saveRuntimeSettings = _server_ops.saveRuntimeSettings
    _normalise_accent = _server_ops._normalise_accent
    setTheme = _server_ops.setTheme
    setAccent = _server_ops.setAccent
    setDensity = _server_ops.setDensity
    setFlag = _server_ops.setFlag
    setEndpoint = _server_ops.setEndpoint
    completeOnboarding = _server_ops.completeOnboarding
    resetOnboarding = _server_ops.resetOnboarding

    # task/history operations
    _matching_tasks = _task_ops._matching_tasks
    _grouped_tasks = _task_ops._grouped_tasks
    setSearch = _task_ops.setSearch
    openAdjacentTask = _task_ops.openAdjacentTask
    _active_session = _task_ops._active_session
    _sync_active_session = _task_ops._sync_active_session
    _new_message_model = _task_ops._new_message_model
    _load_task_runtime = _task_ops._load_task_runtime
    _reset_run_state = _task_ops._reset_run_state
    setDraft = _task_ops.setDraft
    _save_draft = _task_ops._save_draft
    _restore_draft = _task_ops._restore_draft
    newTask = _task_ops.newTask
    openTask = _task_ops.openTask
    deleteTask = _task_ops.deleteTask
    renameTaskById = _task_ops.renameTaskById
    _maybe_generate_task_title = _task_ops._maybe_generate_task_title
    duplicateTaskById = _task_ops.duplicateTaskById
    duplicateTask = _task_ops.duplicateTask
    clearTask = _task_ops.clearTask
    togglePin = _task_ops.togglePin
    _history_cut = _task_ops._history_cut
    branchFrom = _task_ops.branchFrom
    editMessage = _task_ops.editMessage
    regenerate = _task_ops.regenerate
    regenerateWithPreset = _task_ops.regenerateWithPreset

    # attachments/browser/project operations
    _add_attachment = _context_ops._add_attachment
    removeAttachment = _context_ops.removeAttachment
    setAttachmentEnabled = _context_ops.setAttachmentEnabled
    attach_web_page = _context_ops.attach_web_page
    clearAttachments = _context_ops.clearAttachments
    attachPath = _context_ops.attachPath
    attachFile = _context_ops.attachFile
    attachFolder = _context_ops.attachFolder
    attachClipboard = _context_ops.attachClipboard
    _attach_clipboard_png = _context_ops._attach_clipboard_png
    pasteImage = _context_ops.pasteImage
    _navigate_builtin_browser = _context_ops._navigate_builtin_browser
    _request_builtin_browser = _context_ops._request_builtin_browser
    _request_builtin_browser_for = _context_ops._request_builtin_browser_for
    _capture = _context_ops._capture
    attachScreenshot = _context_ops.attachScreenshot
    attachRegion = _context_ops.attachRegion
    cancelRegion = _context_ops.cancelRegion
    cropRegion = _context_ops.cropRegion
    attachWindow = _context_ops.attachWindow
    activeWindowTitle = _context_ops.activeWindowTitle
    _set_project = _context_ops._set_project
    chooseProject = _context_ops.chooseProject
    openProject = _context_ops.openProject
    clearProject = _context_ops.clearProject
    copyProjectPath = _context_ops.copyProjectPath
    revealPath = _context_ops.revealPath
    openTerminalHere = _context_ops.openTerminalHere

    # generation/permissions/desktop operations
    _cancel_background_inference = _generation_ops._cancel_background_inference
    _schedule_memory_learning = _generation_ops._schedule_memory_learning
    _launch_run = _generation_ops._launch_run
    _start_run = _generation_ops._start_run
    _resume_pending_followup = _generation_ops._resume_pending_followup
    _queued_text = _generation_ops._queued_text
    _send_while_busy = _generation_ops._send_while_busy
    send = _generation_ops.send
    _confirm_action_for = _permission_ops._confirm_action_for
    _confirm_action = _permission_ops._confirm_action
    resolvePermission = _permission_ops.resolvePermission
    allowRestOfTask = _permission_ops.allowRestOfTask
    setPermissionMode = _permission_ops.setPermissionMode
    _memory_for_run = _permission_ops._memory_for_run
    setMemoryEnabled = _permission_ops.setMemoryEnabled
    setReferenceChatHistory = _permission_ops.setReferenceChatHistory
    saveMemory = _permission_ops.saveMemory
    rememberNote = _permission_ops.rememberNote
    clearMemory = _permission_ops.clearMemory
    reloadMemory = _permission_ops.reloadMemory
    revealMemory = _permission_ops.revealMemory
    _on_event = _event_ops._on_event
    _run_done = _event_ops._run_done
    _run_failed = _event_ops._run_failed
    _maybe_notify = _event_ops._maybe_notify
    setWindowActive = _event_ops.setWindowActive
    _desktop_control_released = _event_ops._desktop_control_released
    _release_desktop_control = _event_ops._release_desktop_control
    stop = _event_ops.stop
    promoteComputerControlOverlay = _event_ops.promoteComputerControlOverlay
    setComputerControlOverlayVisible = _event_ops.setComputerControlOverlayVisible
    toggleDesktop = _event_ops.toggleDesktop
    _desktop_done = _event_ops._desktop_done
    _desktop_failed = _event_ops._desktop_failed
    pullModel = _event_ops.pullModel
    cancelPull = _event_ops.cancelPull

    # presentation/export/lifecycle operations
    renderMarkdown = _misc_ops.renderMarkdown
    _palette_hex = _misc_ops._palette_hex
    setHtmlPalette = _misc_ops.setHtmlPalette
    highlight = _misc_ops.highlight
    setCodePalette = _misc_ops.setCodePalette
    copyText = _misc_ops.copyText
    saveCode = _misc_ops.saveCode
    copyAndOpenTerminal = _misc_ops.copyAndOpenTerminal
    exportTask = _misc_ops.exportTask
    clearError = _misc_ops.clearError
    _clear_error = _misc_ops._clear_error
    _set_error = _misc_ops._set_error
    _show_error = _misc_ops._show_error
    _release_all_permission_waits = _misc_ops._release_all_permission_waits
    canClose = _misc_ops.canClose
    shutdown = _misc_ops.shutdown

    # ------------------------------------------------------------ read-only
    @Property(QObject, notify=changed)
    def messageModel(self):
        return self.messages

    @Property(QObject, constant=True)
    def workspaceDock(self):
        return self.dock

    # ------------------------------------------------------- measured state
    # The System panel reports only what this machine can actually answer.
    # A metric that cannot be read is absent, never zero-filled.
    @Property("QVariantMap", notify=changed)
    def systemState(self):
        memory = system_info.system_memory()
        gpu = system_info.gpu_memory()
        process = system_info.process_memory()
        state = {
            "online": self._online,
            "connectionState": self.connectionState,
            "endpoint": self._endpoint,
            "model": self._model,
            "busy": self._busy,
            "agentState": ("Waiting for you" if self._pending_permission is not None
                           else "Working" if self._busy else "Idle"),
            "project": Path(self._working_directory).name if self._working_directory else "",
            "contextUsed": self.contextUsed,
            "contextTotal": self._num_ctx,
            "contextLabel": self.contextSummary,
            "resident": self._resident_models,
            "hasProcessMemory": process > 0,
            "processMemory": system_info.human_bytes(process),
            "hasMemory": bool(memory),
            "memoryUsed": system_info.human_bytes(memory.get("used", 0)) if memory else "",
            "memoryTotal": system_info.human_bytes(memory.get("total", 0)) if memory else "",
            "memoryFraction": (memory.get("used", 0) / memory["total"]) if memory.get("total") else 0.0,
            "hasGpu": bool(gpu),
            "gpuUsed": system_info.human_bytes(gpu.get("used", 0)) if gpu else "",
            "gpuTotal": system_info.human_bytes(gpu.get("total", 0)) if gpu else "",
            "gpuFraction": (gpu.get("used", 0) / gpu["total"]) if gpu.get("total") else 0.0,
        }
        return state

    @Property(str, notify=changed)
    def endpoint(self): return self._endpoint
    @Property(str, notify=changed)
    def defaultEndpoint(self): return self._default_endpoint
    @Property("QVariantList", notify=changed)
    def endpointProfiles(self):
        return [{**item, "selected": item["url"] == self._endpoint,
                 "default": item["url"] == self._default_endpoint}
                for item in self._endpoint_profiles]
    @Property(str, notify=changed)
    def endpointProfileName(self):
        return next((item["name"] for item in self._endpoint_profiles
                     if item["url"] == self._endpoint), self._endpoint_label(self._endpoint))
    @Property(str, notify=changed)
    def model(self): return self._model
    @Property(str, notify=changed)
    def modelShortName(self):
        return self._model.split(":")[0] if self._model else "No model"
    @Property("QStringList", notify=changed)
    def models(self): return self._models
    @Property("QVariantList", notify=catalogChanged)
    def modelCatalog(self): return self._catalog
    @Property("QStringList", notify=changed)
    def modelCapabilities(self): return self._model_capabilities
    @Property(bool, notify=changed)
    def modelCapabilitiesLoading(self): return self._capability_probe_active
    @Property(bool, notify=changed)
    def modelSupportsTools(self): return "tools" in self._model_capabilities
    @Property(bool, notify=changed)
    def modelSupportsVision(self): return "vision" in self._model_capabilities
    @Property(bool, notify=changed)
    def modelSupportsThinking(self): return "thinking" in self._model_capabilities
    @Property(int, notify=changed)
    def modelContextLength(self): return self._model_context_length
    @Property(str, notify=changed)
    def modelContextLabel(self):
        length = self._model_context_length
        if not length:
            return ""
        return f"{length // 1000}K native context" if length >= 1000 else f"{length} native context"

    @Property(str, notify=changed)
    def modelCapabilitySummary(self):
        if self._capability_probe_active:
            return "Checking capabilities…"
        if self._capability_error:
            return "Capabilities unavailable"
        labels = ["Chat"]
        for capability, label in (("tools", "Tools"), ("vision", "Vision"), ("thinking", "Thinking")):
            if capability in self._model_capabilities:
                labels.append(label)
        return " · ".join(labels)

    @Property(str, notify=changed)
    def modelCapabilityHint(self):
        if self._capability_probe_active:
            return f"Checking what {self._model} can do before desktop work starts."
        if self._capability_error:
            return f"Could not read this model's capabilities: {self._capability_error}"
        tools = "tools" in self._model_capabilities
        vision = "vision" in self._model_capabilities
        if tools and vision:
            return "Ready for visual desktop control: this model advertises both tools and vision."
        if tools:
            return "Local commands and app launching are ready. Screen interaction also needs vision."
        return "Chat is available, but this model does not advertise desktop tool calling."

    @Property(str, notify=changed)
    def capabilityWarning(self):
        """A problem the user should see before sending, not after it fails."""
        if not self._online or self._capability_probe_active or self._capability_error:
            return ""
        active_attachments = [item for item in self._attachments
                              if item.get("enabled", True) is not False]
        if ctx.needs_vision(active_attachments) and "vision" not in self._model_capabilities:
            return f"{self._model} cannot read images. Attached pictures will be ignored — pick a vision model to use them."
        if self.contextFraction > 0.92:
            return ("This conversation nearly fills the model's context window. Start a new chat, "
                    "or switch to the Deep runtime preset for more room.")
        if "tools" not in self._model_capabilities:
            return f"{self._model} does not advertise tool calling. Choose a tool-capable model to run commands or open apps."
        if self.desktopEnabled and "vision" not in self._model_capabilities:
            return f"{self._model} has no vision, so it can open apps but cannot click or type based on what is on screen."
        if self._think and "thinking" not in self._model_capabilities:
            return f"{self._model} does not support thinking, so that setting is ignored for this model."
        return ""

    @Property(bool, notify=changed)
    def online(self): return self._online
    @Property(bool, notify=changed)
    def busy(self): return self._busy
    @Property(bool, notify=changed)
    def connecting(self): return self._connecting
    @Property(bool, notify=changed)
    def pulling(self): return self._pulling
    @Property(str, notify=changed)
    def pullProgress(self): return self._pull_progress
    @Property(float, notify=changed)
    def pullPercent(self): return self._pull_percent
    @Property(str, notify=changed)
    def status(self): return self._status
    @Property(str, notify=changed)
    def connectionState(self):
        if self._connecting or self._probe_active:
            return "connecting"
        if self._pulling:
            return "downloading"
        if self._online:
            return "connected"
        return "error" if self._error else "offline"

    @Property(str, notify=changed)
    def error(self): return self._error
    @Property(str, notify=changed)
    def errorTitle(self): return self._error_title
    @Property("QVariantList", notify=changed)
    def errorActions(self): return self._error_actions
    @Property(bool, notify=changed)
    def hasMessages(self): return bool(self.messages.items)
    @Property(bool, notify=changed)
    def desktopEnabled(self): return bool(self._desktop_status.get("connected"))
    @Property(bool, notify=changed)
    def desktopAvailable(self): return bool(self._desktop_status.get("available"))
    @Property(str, notify=changed)
    def desktopBackend(self): return self._desktop_status.get("backend", "Unavailable")
    @Property(str, notify=changed)
    def desktopDetail(self): return self._desktop_status.get("detail", "Desktop access is off")
    @Property(bool, notify=changed)
    def desktopRemembered(self): return bool(self._desktop_status.get("remembered"))
    @Property(str, notify=changed)
    def desktopStopShortcut(self): return self._desktop_status.get("stopShortcut", "")
    @Property(str, notify=changed)
    def desktopStopDetail(self): return self._desktop_status.get("stopDetail", "")
    @Property(QObject, constant=True)
    def captureVisibility(self): return self._capture_visibility
    @Property(bool, notify=changed)
    def computerControlActive(self):
        state = self._run_sessions.get(self._task_id)
        return bool(state and state.get("computer_control_active") and state.get("busy"))
    @Property(str, notify=changed)
    def computerControlStopShortcut(self):
        # Never invent a global key. Wayland may choose another trigger or
        # decline the portal request entirely.
        return str(self._desktop_status.get("stopShortcut") or "")
    @Property(str, notify=changed)
    def computerControlStopDetail(self):
        return str(self._desktop_status.get("stopDetail") or
                   "No global stop shortcut is available; stop from Wynxq.")
    @Property(str, notify=changed)
    def computerControlStatus(self):
        state = self._run_sessions.get(self._task_id)
        return str(state.get("status", "Working…")) if state else "Working…"
    @Property(str, notify=changed)
    def computerControlThought(self):
        state = self._run_sessions.get(self._task_id)
        return str(state.get("overlay_thought", ""))[-1800:] if state else ""
    @Property(str, notify=changed)
    def computerControlReply(self):
        state = self._run_sessions.get(self._task_id)
        return str(state.get("overlay_reply", ""))[-1800:] if state else ""
    @Property(int, notify=changed)
    def computerControlQueuedCount(self):
        state = self._run_sessions.get(self._task_id)
        return len(state.get("queued_messages", [])) if state else 0
    @Property(str, notify=changed)
    def permissionMode(self): return self._permission_mode
    @Property(str, notify=changed)
    def permissionModeLabel(self): return PERMISSION_LABELS[self._permission_mode]
    @Property("QVariantList", constant=True)
    def permissionModes(self):
        return [{"id": mode, "label": PERMISSION_LABELS[mode], "detail": PERMISSION_DETAILS[mode]}
                for mode in PERMISSION_MODES]
    @Property(str, notify=changed)
    def permissionModeDetail(self): return PERMISSION_DETAILS[self._permission_mode]
    @Property(bool, notify=permissionChanged)
    def permissionPending(self): return self._pending_permission is not None
    @Property(str, notify=permissionChanged)
    def permissionSummary(self):
        return (self._pending_permission or {}).get("summary", "")
    @Property(str, notify=permissionChanged)
    def permissionDetail(self):
        return (self._pending_permission or {}).get("detail", "")
    @Property(str, notify=permissionChanged)
    def permissionRisk(self):
        return (self._pending_permission or {}).get("risk", "normal")
    @Property(str, notify=permissionChanged)
    def permissionTool(self):
        return (self._pending_permission or {}).get("tool", "")
    @Property(str, notify=permissionChanged)
    def permissionCommand(self):
        """The exact command line, when the action is one. Otherwise empty."""
        return (self._pending_permission or {}).get("command", "")
    @Property(str, notify=permissionChanged)
    def permissionDirectory(self):
        directory = (self._pending_permission or {}).get("directory", "")
        return ctx.working_directory_label(directory) if directory else ""

    # -------------------------------------------------------------- memory
    @Property(bool, notify=memoryChanged)
    def memoryEnabled(self): return self._memory_enabled
    @Property(bool, notify=memoryChanged)
    def referenceChatHistory(self): return self._reference_chat_history
    @Property(str, notify=memoryChanged)
    def memoryPath(self): return str(self.memory.path)
    @Property(str, notify=memoryChanged)
    def memoryText(self): return self.memory.read()
    @Property(int, notify=memoryChanged)
    def memoryCount(self): return int(self.memory.stats()["notes"])
    @Property(str, notify=memoryChanged)
    def memorySummary(self):
        stats = self.memory.stats()
        if not self._memory_enabled:
            return "Memory is off. Nothing is read from this file or written to it."
        notes = stats["notes"]
        if not notes:
            return "Nothing remembered yet. Tell Wynxq something worth keeping, or write it here."
        return (f"{notes} note{'' if notes == 1 else 's'} across "
                f"{stats['sections']} section{'' if stats['sections'] == 1 else 's'}, "
                f"available across chats.")

    @Property(str, notify=changed)
    def taskTitle(self): return self._task_title
    @Property(str, notify=changed)
    def taskId(self): return self._task_id
    @Property(str, notify=changed)
    def tokenRate(self): return self._token_rate
    @Property(bool, notify=changed)
    def thinking(self): return self._think
    @Property(bool, notify=changed)
    def reducedMotion(self): return self._reduced_motion
    @Property(bool, notify=changed)
    def systemFont(self): return self._system_font
    @Property(str, notify=changed)
    def density(self): return self._density
    @Property(str, notify=changed)
    def theme(self): return self._theme
    @Property(str, notify=changed)
    def accentColor(self): return self._accent
    @Property(bool, notify=changed)
    def solidBackground(self): return self._solid_background
    @Property(bool, notify=changed)
    def notificationsEnabled(self): return self._notifications
    @Property(bool, notify=changed)
    def trayEnabled(self): return self._tray_enabled
    @Property(bool, notify=changed)
    def onboarded(self): return self._onboarded
    @Property("QVariantList", constant=True)
    def themes(self):
        return [{"name": name, "color": color} for name, color in self.THEMES.items()]
    @Property("QVariantList", constant=True)
    def starters(self): return STARTERS

    # ------------------------------------------------------- shell layout
    # The shell remembers how the user left it. Nothing here ever moves on its
    # own: these are read at startup and written only when the user acts.
    @Property(int, notify=changed)
    def sidebarWidth(self): return self._sidebar_width
    @Property(bool, notify=changed)
    def sidebarCollapsed(self): return self._sidebar_collapsed

    @Slot(int)
    def setSidebarWidth(self, width):
        """Persist a sidebar width between 200 and 400 pixels."""
        width = _bounded_int(width, 200, 400, self._sidebar_width)
        if width == self._sidebar_width:
            return
        self._sidebar_width = width
        self.store.set_setting("sidebar_width", width)
        self.changed.emit()

    @Slot(bool)
    def setSidebarCollapsed(self, collapsed):
        """Persist whether the sidebar is collapsed."""
        collapsed = bool(collapsed)
        if collapsed == self._sidebar_collapsed:
            return
        self._sidebar_collapsed = collapsed
        self.store.set_setting("sidebar_collapsed", collapsed)
        self.changed.emit()
    @Property(int, notify=changed)
    def numCtx(self): return self._num_ctx
    @Property(float, notify=changed)
    def temperature(self): return self._temperature
    @Property(str, notify=changed)
    def keepAlive(self): return self._keep_alive
    @Property(int, notify=changed)
    def maxSteps(self): return self._max_steps
    @Property(str, notify=changed)
    def runtimePreset(self): return self._runtime_preset
    @Property(str, notify=changed)
    def runtimeHint(self): return self.RUNTIME_HINTS.get(self._runtime_preset, "")
    @Property(str, notify=changed)
    def runtimeSummary(self):
        return f"{self._num_ctx // 1024}K context · T{self._temperature:g} · {self._max_steps} actions"
    @Property("QVariantMap", notify=changed)
    def runMetrics(self):
        metrics = self._run_metrics
        return {
            "tokens": metrics.get("tokens", 0),
            "promptTokens": metrics.get("prompt_tokens", 0),
            "cachedTokens": metrics.get("cached_prompt_tokens", 0),
            "loadSeconds": round(metrics.get("load_ms", 0.0) / 1000.0, 1),
            "totalSeconds": round(metrics.get("total_ms", 0.0) / 1000.0, 1),
            "rate": round(metrics.get("tokens_per_second", 0.0), 1),
            "hasData": bool(metrics.get("tokens") or metrics.get("prompt_tokens")),
        }

    def _recount_history_tokens(self):
        """Estimate once per history change, not once per streamed token."""
        self._history_tokens = sum(ctx.estimate_tokens(str(m.get("content", "")))
                                   for m in self._history)

    @Property(int, notify=changed)
    def contextUsed(self):
        """Approximate prompt tokens in play, including pending attachments."""
        used = int(self._run_metrics.get("prompt_tokens", 0) or 0) or self._history_tokens
        return used + sum(int(item.get("tokens", 0)) for item in self._attachments
                          if item.get("enabled", True) is not False)
    @Property(float, notify=changed)
    def contextFraction(self):
        return min(1.0, self.contextUsed / float(self._num_ctx)) if self._num_ctx else 0.0
    @Property(str, notify=changed)
    def contextSummary(self):
        return f"{self.contextCompact} context"
    @Property(str, notify=changed)
    def contextCompact(self):
        """The same reading without the trailing word, for a labelled surface."""
        used = self.contextUsed
        total = f"{self._num_ctx // 1024}K"
        return f"{used / 1000:.1f}K / {total}" if used > 999 else f"{used} / {total}"

    def _last_turn_used_tools(self):
        for message in reversed(self._history):
            if message.get("role") == "user":
                return False
            if message.get("tool_calls") or message.get("role") == "tool":
                return True
        return False

    @Property(bool, notify=changed)
    def canRegenerate(self):
        return bool(self._task_id and self._history and not self._busy and self._online and not self.desktopEnabled and not self._last_turn_used_tools())
    @Property(bool, notify=changed)
    def taskPinned(self):
        return any(item.get("id") == self._task_id and bool(item.get("pinned")) for item in self._tasks)
    @Property("QVariantList", notify=tasksChanged)
    def taskGroups(self): return self._grouped_tasks()
    @Property(str, notify=tasksChanged)
    def searchQuery(self): return self._search
    @Property("QVariantList", notify=activityChanged)
    def activity(self): return self._activity
    @Property("QVariantList", notify=attachmentsChanged)
    def attachments(self): return self._attachments
    @Property(int, notify=attachmentsChanged)
    def attachmentCount(self): return len(self._attachments)
    @Property(int, notify=attachmentsChanged)
    def includedAttachmentCount(self):
        return sum(item.get("enabled", True) is not False for item in self._attachments)
    # --------------------------------------------------------- the project
    # The folder Wynxq is working in is the first thing the interface states,
    # so it gets a name, a short path, and a list of places to go back to.
    @Property(str, notify=changed)
    def projectPath(self): return self._working_directory
    @Property(str, notify=changed)
    def projectName(self):
        return Path(self._working_directory).name if self._working_directory else ""
    @Property(str, notify=changed)
    def projectLabel(self):
        return ctx.working_directory_label(self._working_directory)
    @Property(str, notify=changed)
    def projectParentLabel(self):
        """Where the project sits, without repeating its own name."""
        if not self._working_directory:
            return ""
        return ctx.working_directory_label(str(Path(self._working_directory).parent))
    @Property("QVariantList", notify=changed)
    def recentProjects(self):
        return [{"path": path, "name": Path(path).name,
                 "label": ctx.working_directory_label(path)}
                for path in self._recent_projects if path != self._working_directory]

    @Property(str, constant=True)
    def dataLocation(self): return str(getattr(self.store, "path", ""))
    @Property(str, constant=True)
    def appVersion(self):
        from . import __version__
        return __version__

    # ------------------------------------------------------------- sidebar
    # A short query filters what is already loaded; a longer one is worth a
    # round trip that also looks inside the messages themselves.
    DEEP_SEARCH_LENGTH = 3

    # -------------------------------------------------------------- models
    # ------------------------------------------------------------- runtime
    # ----------------------------------------------------------- appearance
    # ------------------------------------------------------------- history
    @Property(str, notify=draftChanged)
    def draftText(self): return self._draft_text

    # --------------------------------------------------------- attachments
    # ------------------------------------------------------ region capture
    @Property(str, notify=regionChanged)
    def regionImage(self): return self._region.get("image", "")
    @Property(int, notify=regionChanged)
    def regionWidth(self): return int(self._region.get("width", 0))
    @Property(int, notify=regionChanged)
    def regionHeight(self): return int(self._region.get("height", 0))
    @Property(bool, notify=regionChanged)
    def regionActive(self): return bool(self._region.get("image"))

    RECENT_PROJECT_LIMIT = 8

    # ---------------------------------------------------------- generation
    # ------------------------------------------------------- permissioning
    # -------------------------------------------------------------- memory
    # --------------------------------------------------------------- events
    # --------------------------------------------------------------- desktop
    # ---------------------------------------------------------------- pulls
    # ----------------------------------------------------------------- misc