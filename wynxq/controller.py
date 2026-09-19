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
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QObject, Property, Qt, QThread, Signal, Slot,
)
from PySide6.QtGui import QColor, QGuiApplication

from . import context as ctx
from . import markdown as md
from . import notify
from . import system as system_info
from .desktop import DesktopController, SessionTokens
from .dock import DockController
from .engine import (
    PERMISSION_DETAILS, PERMISSION_LABELS, PERMISSION_MODES, SAFE,
    AgentEngine, OllamaClient, action_summary, normalise_mode,
)
from .memory import Memory
from .storage import Store


def _bounded_int(value, low, high, default):
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


def _bounded_float(value, low, high, default):
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return default


def _blank_metrics() -> dict:
    return {"tokens": 0, "prompt_tokens": 0, "cached_prompt_tokens": 0,
            "load_ms": 0.0, "total_ms": 0.0, "tokens_per_second": 0.0}


def _human_bytes(count) -> str:
    try:
        size = float(count)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if size >= 100 or unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


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


class Job(QThread):
    event = Signal(dict)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.function(self.cancel, self.event.emit))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)


class _StoredTokens(SessionTokens):
    """Keeps the portal's restore token in the same private database as the
    rest of the settings, so screen control stops asking on every launch."""

    def __init__(self, store):
        super().__init__()
        self._store = store

    def load(self) -> str:
        return str(self._store.get_setting("desktop_restore_token", "") or "")

    def save(self, token: str) -> None:
        self._store.set_setting("desktop_restore_token", str(token or ""))


class Controller(QObject):
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
        super().__init__()
        self.store = store or Store()
        self.desktop = desktop or DesktopController(tokens=_StoredTokens(self.store))
        self.messages = Messages(self)
        self.dock = DockController(store=self.store, parent=self)
        self.dock.toast.connect(self.toast)
        self.dock.contextChanged.connect(self.changed)
        setting = self.store.get_setting
        self._endpoint = setting("endpoint", "http://127.0.0.1:11434")
        self._model = setting("model", "qwen3.8:27b")
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
        self._run_job: Job | None = None
        self._pull_job: Job | None = None
        self._probe_active = False
        self._turn_had_message = False
        self._run_started = 0.0
        self._window_active = True
        self._pending_permission: dict | None = None
        self._permission_event = threading.Event()
        self._permission_answer = False
        self._session_auto = False
        self._capture_busy = False
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

    # ------------------------------------------------------------ read-only
    @Property(QObject, constant=True)
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
                f"read into every task.")

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
        width = _bounded_int(width, 200, 400, self._sidebar_width)
        if width == self._sidebar_width:
            return
        self._sidebar_width = width
        self.store.set_setting("sidebar_width", width)
        self.changed.emit()

    @Slot(bool)
    def setSidebarCollapsed(self, collapsed):
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
        for task in self._matching_tasks():
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
        """Move to the next or previous chat in the order the sidebar shows."""
        if self._busy:
            return
        order = [item["id"] for group in self._grouped_tasks() for item in group["items"]]
        if not order:
            return
        if self._task_id not in order:
            self.openTask(order[0])
            return
        position = order.index(self._task_id) + int(delta)
        if 0 <= position < len(order):
            self.openTask(order[position])

    def _refresh_tasks(self):
        self._tasks = self.store.list_conversations()
        self.tasksChanged.emit()

    # -------------------------------------------------------------- models
    def _refresh_model_capabilities(self):
        self._capability_probe_generation += 1
        generation = self._capability_probe_generation
        model, endpoint = self._model, self._endpoint
        self._model_capabilities = []
        self._model_context_length = 0
        self._capability_error = ""
        if not self._online or not model or model not in self._models:
            self._capability_probe_active = False
            self.changed.emit()
            return
        self._capability_probe_active = True
        self.changed.emit()

        def done(described):
            if generation != self._capability_probe_generation:
                return
            self._capability_probe_active = False
            self._model_capabilities = sorted({
                str(capability).strip().lower()
                for capability in described.get("capabilities", []) if str(capability).strip()
            })
            self._model_context_length = int(described.get("context_length", 0) or 0)
            self._capability_error = ""
            self._decorate_catalog()
            self.changed.emit()

        def failed(message):
            if generation != self._capability_probe_generation:
                return
            self._capability_probe_active = False
            self._model_capabilities = []
            self._model_context_length = 0
            self._capability_error = message
            self.changed.emit()

        self._job(lambda cancel, emit: OllamaClient(endpoint).describe(model), done, failed)

    def _decorate_catalog(self):
        for entry in self._catalog:
            entry["favorite"] = entry["name"] in self._favorites
            entry["loaded"] = entry["name"] in self._loaded_models
            entry["selected"] = entry["name"] == self._model
            entry["recent"] = entry["name"] in self._recent_models
            if entry["selected"]:
                entry["capabilities"] = list(self._model_capabilities)
            # An embedding-only model cannot hold a conversation, so the quick
            # picker leaves it out; the manager still lists and deletes it.
            capabilities = [str(c).lower() for c in entry.get("capabilities") or []]
            entry["chat"] = not capabilities or capabilities != ["embedding"]
        recent = {name: index for index, name in enumerate(self._recent_models)}
        self._catalog.sort(key=lambda item: (not item["selected"], not item["favorite"],
                                             recent.get(item["name"], len(recent)),
                                             item["name"].lower()))
        self.catalogChanged.emit()

    @staticmethod
    def _catalog_entry(raw: dict) -> dict:
        details = raw.get("details") or {}
        name = raw["name"]
        return {
            "name": name,
            "family": str(details.get("family", "")),
            "parameters": str(details.get("parameter_size", "")),
            "quantization": str(details.get("quantization_level", "")),
            "sizeLabel": _human_bytes(raw.get("size")),
            "sizeBytes": int(raw.get("size") or 0),
            "capabilities": [],
            "favorite": False,
            "loaded": False,
            "recent": False,
            "selected": False,
            "chat": True,
        }

    @Slot()
    def refreshModels(self):
        if self._probe_active:
            return
        self._probe_active = True
        self._capability_probe_generation += 1
        self._capability_probe_active = False
        self._model_capabilities = []
        self._capability_error = ""
        endpoint = self._endpoint
        self.changed.emit()

        def fetch(cancel, emit):
            client = OllamaClient(endpoint)
            models = client.models()
            try:
                resident = client.resident()
            except Exception:
                resident = []  # /api/ps is a nicety; never fail a connection over it.
            return models, resident

        def done(payload):
            models, resident = payload
            self._probe_active = False
            self._models = [m["name"] for m in models]
            self._catalog = [self._catalog_entry(m) for m in models]
            self._resident_models = system_info.resident_models(resident)
            self._loaded_models = [entry["name"] for entry in self._resident_models]
            self._online = True
            if self._model not in self._models and self._models:
                preferred = next((m for m in self._favorites if m in self._models), None)
                self._model = preferred or ("qwen3.8:27b" if "qwen3.8:27b" in self._models else self._models[0])
                self.store.set_setting("model", self._model)
            if self._models:
                self._clear_error()
            else:
                self._set_error("No models installed",
                                "Ollama is running but has no local models yet. Download one to get started.",
                                [{"label": "Open model manager", "action": "models"}])
            self._decorate_catalog()
            self.changed.emit()
            self._refresh_model_capabilities()

        def failed(message):
            self._probe_active = False
            self._online = False
            self._models = []
            self._catalog = []
            self._model_capabilities = []
            self._capability_probe_active = False
            self._capability_error = ""
            self._set_error("Ollama isn't responding",
                            f"Nothing answered at {endpoint}. Start Ollama with “ollama serve”, then reconnect. ({message})",
                            [{"label": "Retry", "action": "retry"},
                             {"label": "Connection settings", "action": "settings"}])
            self.catalogChanged.emit()
            self.changed.emit()

        self._job(fetch, done, failed)

    @Slot(str)
    def setModel(self, model):
        if self._busy or self._pulling or not str(model).strip():
            return
        model = str(model).strip()
        if model == self._model and self._model_capabilities:
            return
        self._model = model
        self.store.set_setting("model", self._model)
        self._recent_models = [model] + [m for m in self._recent_models if m != model][:5]
        self.store.set_setting("recent_models", self._recent_models)
        self._decorate_catalog()
        self._refresh_model_capabilities()

    @Slot(str)
    def toggleFavoriteModel(self, model):
        model = str(model).strip()
        if not model:
            return
        if model in self._favorites:
            self._favorites.remove(model)
        else:
            self._favorites.append(model)
        self.store.set_setting("favorite_models", self._favorites)
        self._decorate_catalog()

    @Slot(str)
    def deleteModel(self, model):
        model = str(model).strip()
        if self._busy or self._pulling or not model:
            return
        endpoint = self._endpoint

        def done(_):
            self.toast.emit(f"{model} removed")
            self.refreshModels()

        self._job(lambda cancel, emit: OllamaClient(endpoint).delete(model), done)

    # ------------------------------------------------------------- runtime
    def _persist_runtime(self):
        for key, value in (("num_ctx", self._num_ctx), ("temperature", self._temperature),
                           ("keep_alive", self._keep_alive), ("max_steps", self._max_steps),
                           ("runtime_preset", self._runtime_preset)):
            self.store.set_setting(key, value)

    @Slot(str)
    def applyRuntimePreset(self, name):
        if self._busy or name not in self.RUNTIME_PRESETS:
            return
        preset = self.RUNTIME_PRESETS[name]
        self._num_ctx = preset["num_ctx"]
        self._temperature = preset["temperature"]
        self._keep_alive = preset["keep_alive"]
        self._max_steps = preset["max_steps"]
        self._runtime_preset = name
        self._persist_runtime()
        self.changed.emit()
        self.toast.emit(f"{name} runtime applied")

    @Slot(str, str, str, str, result=bool)
    def saveRuntimeSettings(self, num_ctx, temperature, keep_alive, max_steps):
        if self._busy:
            self.toast.emit("Stop the current task before changing runtime settings.")
            return False
        try:
            value_ctx = int(str(num_ctx).strip())
            value_temp = float(str(temperature).strip())
            steps = int(str(max_steps).strip())
        except ValueError:
            self._set_error("Runtime values must be numbers",
                            "Context and action budget are whole numbers; temperature can have decimals.")
            return False
        keep = str(keep_alive).strip()
        if not 2048 <= value_ctx <= 131072:
            self._set_error("Context is out of range", "Context size must be between 2048 and 131072 tokens.")
            return False
        if not 0.0 <= value_temp <= 2.0:
            self._set_error("Temperature is out of range", "Temperature must be between 0 and 2.")
            return False
        if not 1 <= steps <= 100:
            self._set_error("Action budget is out of range", "The desktop action budget must be between 1 and 100.")
            return False
        if not keep or len(keep) > 32 or any(ch.isspace() for ch in keep):
            self._set_error("Keep-alive is not valid", "Keep-alive must look like 5m, 30s, 0, or -1.")
            return False
        self._num_ctx, self._temperature = value_ctx, value_temp
        self._keep_alive, self._max_steps = keep, steps
        self._runtime_preset = "Custom"
        self._persist_runtime()
        self._clear_error()
        self.changed.emit()
        self.toast.emit("Runtime settings saved")
        return True

    # ----------------------------------------------------------- appearance
    @staticmethod
    def _normalise_accent(value):
        color = QColor(str(value).strip())
        if not color.isValid() or color.alpha() != 255:
            return None
        return color.name(QColor.HexRgb)

    @Slot(str, result=bool)
    def setTheme(self, theme):
        theme = str(theme)
        if theme not in self.THEMES:
            return False
        self._theme = theme
        self._accent = self.THEMES[theme]
        self.store.set_setting("theme", theme)
        self.store.set_setting("accent", self._accent)
        self.changed.emit()
        return True

    @Slot(str, result=bool)
    def setAccent(self, value):
        accent = self._normalise_accent(value)
        if accent is None:
            self._set_error("That accent colour is not valid",
                            "Enter an opaque hex colour such as #e9e3d6.")
            return False
        self._accent = accent
        self.store.set_setting("accent", accent)
        self.changed.emit()
        return True

    @Slot(str)
    def setDensity(self, value):
        if value in self.DENSITIES and value != self._density:
            self._density = value
            self.store.set_setting("density", value)
            self.changed.emit()

    @Slot(str, bool)
    def setFlag(self, name, value):
        """Toggle a simple boolean preference and persist it."""
        value = bool(value)
        fields = {"think": "_think", "reduced_motion": "_reduced_motion",
                  "solid_background": "_solid_background", "system_font": "_system_font",
                  "notifications": "_notifications", "tray": "_tray_enabled"}
        attribute = fields.get(str(name))
        if not attribute or getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self.store.set_setting(str(name), value)
        self.changed.emit()

    @Slot(str, result=bool)
    def setEndpoint(self, endpoint):
        if self._busy or self._pulling:
            self.toast.emit("Wait for the current task to finish.")
            return False
        try:
            OllamaClient(str(endpoint).strip())
        except Exception as exc:
            self._set_error("That Ollama address is not usable", str(exc))
            return False
        self._endpoint = str(endpoint).strip().rstrip("/")
        self.store.set_setting("endpoint", self._endpoint)
        self.changed.emit()
        self.refreshModels()
        return True

    @Slot()
    def completeOnboarding(self):
        self._onboarded = True
        self.store.set_setting("onboarded", True)
        self.changed.emit()

    @Slot()
    def resetOnboarding(self):
        self._onboarded = False
        self.store.set_setting("onboarded", False)
        self.changed.emit()

    # ------------------------------------------------------------- history
    def _reset_run_state(self):
        self._activity = []
        self._think_seconds = 0.0
        self._token_rate = "—"
        self._run_metrics = _blank_metrics()
        self._status = "Ready when you are"

    @Property(str, notify=draftChanged)
    def draftText(self): return self._draft_text

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
        if self._busy:
            self.toast.emit("Stop the current task before starting another.")
            return
        self._save_draft()
        self._task_id = ""
        self._task_title = "New task"
        self._history = []
        self._history_tokens = 0
        self.messages.replace([])
        self._reset_run_state()
        self._clear_error()
        self.cancelRegion()
        self._restore_draft()
        self.activityChanged.emit()
        self.changed.emit()
        self.focusComposer.emit()

    @Slot(str)
    def openTask(self, task_id):
        if self._busy:
            self.toast.emit("Stop the current task before switching.")
            return
        task = self.store.get_conversation(task_id)
        if not task:
            return
        # Moving to another task must not carry the last one's draft, half-made
        # region capture or error banner with it.
        switching = task_id != self._task_id
        if switching:
            self._save_draft()
            self.cancelRegion()
        self._clear_error()
        self._task_id = task_id
        self._task_title = task["title"]
        if switching:
            self._restore_draft()
        self._history = self.store.get_messages(task_id)
        self.messages.replace(self._history)
        self._recount_history_tokens()
        self._reset_run_state()
        self.activityChanged.emit()
        self.changed.emit()
        self.scrollToEnd.emit()

    @Slot(str)
    def deleteTask(self, task_id):
        if self._busy:
            return
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

    @Slot(str)
    def duplicateTaskById(self, task_id):
        if self._busy:
            return
        source = self.store.get_conversation(task_id)
        if not source:
            return
        copy_task = self.store.create_conversation(f"{source['title']} copy"[:200], source.get("model", ""))
        self.store.set_messages(copy_task["id"], self.store.get_messages(task_id), source.get("model", ""))
        self._refresh_tasks()
        self.openTask(copy_task["id"])
        self.toast.emit("Chat duplicated")

    @Slot()
    def duplicateTask(self):
        if self._busy or not self._task_id:
            return
        task = self.store.create_conversation(f"{self._task_title} copy"[:200], self._model)
        self.store.set_messages(task["id"], list(self._history), self._model)
        self._refresh_tasks()
        self.openTask(task["id"])
        self.toast.emit("Chat duplicated")

    @Slot()
    def clearTask(self):
        if self._busy or not self._task_id:
            return
        self._history = []
        self._history_tokens = 0
        self.store.set_messages(self._task_id, [], self._model)
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
        task = self.store.create_conversation(f"{self._task_title} branch"[:200], self._model)
        self.store.set_messages(task["id"], history, self._model)
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
        self.store.set_messages(self._task_id, history, self._model)
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
        self.store.set_messages(self._task_id, history, self._model)
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

    # --------------------------------------------------------- attachments
    def _add_attachment(self, attachment: dict):
        if len(self._attachments) >= 12:
            self.toast.emit("Twelve attachments is the limit for one message.")
            return
        self._attachments.append(attachment)
        self.attachmentsChanged.emit()
        self.changed.emit()

    @Slot(str)
    def removeAttachment(self, attachment_id):
        before = len(self._attachments)
        self._attachments = [item for item in self._attachments if item["id"] != attachment_id]
        if len(self._attachments) != before:
            self.attachmentsChanged.emit()
            self.changed.emit()

    @Slot(str, bool)
    def setAttachmentEnabled(self, attachment_id, enabled):
        attachment_id = str(attachment_id or "")
        enabled = bool(enabled)
        for index, item in enumerate(self._attachments):
            if str(item.get("id", "")) != attachment_id:
                continue
            if bool(item.get("enabled", True)) == enabled:
                return
            updated = dict(item)
            updated["enabled"] = enabled
            self._attachments[index] = updated
            self.attachmentsChanged.emit()
            self.changed.emit()
            return

    def attach_web_page(self, page: dict) -> None:
        """Attach the page the browser is showing, on the user's request."""
        if not page or not page.get("text"):
            self.toast.emit("There is no readable text on that page yet.")
            return
        self._add_attachment(ctx.from_page(page))
        self.toast.emit(f"Attached {page.get('title') or 'the page'}")

    @Slot()
    def clearAttachments(self):
        if self._attachments:
            self._attachments = []
            self.attachmentsChanged.emit()
            self.changed.emit()

    @Slot(str)
    def attachPath(self, path):
        """Attach a dropped or picked path; folders and images are detected."""
        try:
            self._add_attachment(ctx.load_path(str(path).replace("file://", "")))
        except ctx.ContextError as exc:
            self._set_error("That file could not be attached", str(exc))
        except OSError as exc:
            self._set_error("That file could not be attached", str(exc))

    @Slot()
    def attachFile(self):
        from PySide6.QtWidgets import QFileDialog
        start = self._working_directory or ctx.default_directory()
        paths, _ = QFileDialog.getOpenFileNames(None, "Attach files", start, ctx.TEXT_FILTER)
        for path in paths:
            self.attachPath(path)

    @Slot()
    def attachFolder(self):
        from PySide6.QtWidgets import QFileDialog
        start = self._working_directory or ctx.default_directory()
        path = QFileDialog.getExistingDirectory(None, "Attach a folder", start)
        if path:
            self.attachPath(path)

    @Slot()
    def attachClipboard(self):
        clipboard = QGuiApplication.clipboard()
        image = clipboard.image()
        if not image.isNull():
            self.pasteImage()
            return
        try:
            self._add_attachment(ctx.from_clipboard(clipboard.text()))
        except ctx.ContextError as exc:
            self.toast.emit(str(exc))

    def _attach_clipboard_png(self, image_png: bytes) -> bool:
        """Attach already-encoded clipboard pixels; split out for deterministic tests."""
        if not image_png:
            return False
        try:
            self._add_attachment(ctx.from_clipboard(image_png=bytes(image_png)))
        except ctx.ContextError as exc:
            self.toast.emit(str(exc))
            return False
        return True

    @Slot(result=bool)
    def pasteImage(self):
        from PySide6.QtCore import QBuffer, QByteArray
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            return False
        buffer = QBuffer(QByteArray())
        buffer.open(QBuffer.WriteOnly)
        try:
            if not image.save(buffer, "PNG"):
                return False
            image_png = bytes(buffer.data())
        finally:
            buffer.close()
        return self._attach_clipboard_png(image_png)

    @Slot(str)
    def _navigate_builtin_browser(self, target):
        if not self.dock.browserAvailable:
            return
        self.dock.setTab("browser")
        if not self.dock.visible:
            self.dock.setVisible(True)
        self.dock.navigate(str(target))

    def _request_builtin_browser(self, target: str) -> dict:
        """Worker-safe bridge from an agent tool into the GUI-owned browser."""
        from . import browser as browser_policy
        normalized = browser_policy.normalize(target)
        if not normalized:
            return {"ok": False, "error": "That is not a valid web address or search query"}
        if not self.dock.browserAvailable:
            return {"ok": False, "error": "Wynxq's built-in browser is unavailable"}
        self.browserNavigateRequested.emit(normalized)
        return {"ok": True, "url": normalized, "browser": "Wynxq built-in browser"}

    def _capture(self, kind: str):
        if self._capture_busy:
            return
        self._capture_busy = True
        self.changed.emit()

        def done(result):
            self._capture_busy = False
            try:
                title = "Active window" if kind == "window" else "Screen"
                self._add_attachment(ctx.from_capture(result, ctx.WINDOW if kind == "window" else ctx.SCREENSHOT,
                                                      title=result.get("detail") or title,
                                                      detail=result.get("detail", "")))
            except ctx.ContextError as exc:
                self._set_error("Screen capture failed", str(exc))
            self.changed.emit()

        def failed(message):
            self._capture_busy = False
            self._set_error("Screen capture failed", message,
                            [{"label": "Desktop settings", "action": "desktop"}])

        self._job(lambda cancel, emit: self.desktop.capture(kind, cancel), done, failed)

    @Slot()
    def attachScreenshot(self):
        self._capture("screen")

    # ------------------------------------------------------ region capture
    @Property(str, notify=regionChanged)
    def regionImage(self): return self._region.get("image", "")
    @Property(int, notify=regionChanged)
    def regionWidth(self): return int(self._region.get("width", 0))
    @Property(int, notify=regionChanged)
    def regionHeight(self): return int(self._region.get("height", 0))
    @Property(bool, notify=regionChanged)
    def regionActive(self): return bool(self._region.get("image"))

    @Slot()
    def attachRegion(self):
        """Capture the screen, then let the user pick part of it.

        The crop happens here, on an image Wynxq already holds, so selecting a
        region needs no extra permission and nothing new is captured.
        """
        if self._capture_busy or self._region.get("image"):
            return
        self._capture_busy = True
        self.changed.emit()

        def done(result):
            self._capture_busy = False
            if result.get("ok") and result.get("image"):
                self._region = {"image": result["image"], "width": result.get("width", 0),
                                "height": result.get("height", 0)}
                self.regionChanged.emit()
            else:
                self._set_error("Screen capture failed", result.get("error", "No image was returned."))
            self.changed.emit()

        def failed(message):
            self._capture_busy = False
            self._set_error("Screen capture failed", message,
                            [{"label": "Desktop settings", "action": "desktop"}])

        self._job(lambda cancel, emit: self.desktop.capture("screen", cancel), done, failed)

    @Slot()
    def cancelRegion(self):
        if self._region.get("image"):
            self._region = {}
            self.regionChanged.emit()

    @Slot(int, int, int, int)
    def cropRegion(self, x, y, width, height):
        image = self._region.get("image", "")
        self._region = {}
        self.regionChanged.emit()
        if not image or width < 8 or height < 8:
            return
        try:
            import base64
            import io
            from PIL import Image
            with Image.open(io.BytesIO(base64.b64decode(image))) as picture:
                box = (max(0, x), max(0, y),
                       min(picture.width, x + width), min(picture.height, y + height))
                if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                    return
                cropped = picture.crop(box).convert("RGB")
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception as exc:
            self._set_error("That region could not be cropped", str(exc))
            return
        self._add_attachment(ctx.from_capture(
            {"ok": True, "image": encoded, "width": cropped.width, "height": cropped.height},
            ctx.SCREENSHOT, title="Screen region", detail="Region"))

    @Slot()
    def attachWindow(self):
        self._capture("window")

    @Slot(result=str)
    def activeWindowTitle(self):
        return str(self.desktop.active_window().get("title", ""))

    RECENT_PROJECT_LIMIT = 8

    def _set_project(self, path: str):
        """Move to a folder, remembering where we have been."""
        path = str(path or "")
        self._working_directory = path
        self.store.set_setting("working_directory", path)
        if path:
            self._recent_projects = [path] + [p for p in self._recent_projects if p != path]
            del self._recent_projects[self.RECENT_PROJECT_LIMIT:]
            self.store.set_setting("recent_projects", self._recent_projects)
        self.dock.set_project(path)
        if path:
            # Opening a project is the one moment where Files is obviously the
            # useful panel. It is still only a suggestion: a tab the user has
            # chosen by hand is never replaced.
            self.dock.suggest("files")
        self.changed.emit()

    @Slot()
    def chooseProject(self):
        from PySide6.QtWidgets import QFileDialog
        start = self._working_directory or ctx.default_directory()
        path = QFileDialog.getExistingDirectory(None, "Choose a project folder", start)
        if path:
            self._set_project(path)
            self.toast.emit(f"Working in {ctx.working_directory_label(path)}")

    @Slot(str)
    def openProject(self, path):
        """Return to a folder from the recent list."""
        path = str(path or "")
        if not path or not Path(path).is_dir():
            self._recent_projects = [p for p in self._recent_projects if p != path]
            self.store.set_setting("recent_projects", self._recent_projects)
            self.changed.emit()
            self.toast.emit("That folder is no longer there.")
            return
        self._set_project(path)

    @Slot()
    def clearProject(self):
        self._set_project("")

    @Slot()
    def copyProjectPath(self):
        if self._working_directory:
            self.copyText(self._working_directory)
        else:
            self.toast.emit("No project folder is set.")

    @Slot(str)
    def revealPath(self, path):
        target = str(path) or self._working_directory
        if not target or not notify.open_path(target):
            self.toast.emit("No file manager is available to open that location.")

    @Slot()
    def openTerminalHere(self):
        if not notify.open_terminal(self._working_directory or str(Path.home())):
            self.toast.emit("No terminal emulator was found on this system.")

    # ---------------------------------------------------------- generation
    def _start_run(self, history):
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
        self.dock.begin_turn(self._task_title if self._task_title != "New task" else "Turn")
        self.activityChanged.emit()
        self._refresh_tasks()
        self.changed.emit()
        engine = AgentEngine(
            OllamaClient(self._endpoint), self.desktop, self._memory_for_run(),
            browser_open=self._request_builtin_browser if self.dock.browserAvailable else None,
        )
        model, enabled, think = self._model, self.desktopEnabled, self._think
        num_ctx, temperature = self._num_ctx, self._temperature
        keep_alive, max_steps = self._keep_alive, self._max_steps
        mode, project = self._permission_mode, self._working_directory
        self._run_job = self._job(
            lambda cancel, emit: engine.run(
                list(history), model, enabled, cancel, emit, think=think, max_steps=max_steps,
                num_ctx=num_ctx, temperature=temperature, keep_alive=keep_alive,
                permission_mode=mode, project=project, confirm=self._confirm_action),
            self._run_done, self._run_failed, self._on_event,
        )

    @Slot(str)
    def send(self, text):
        text = str(text).strip()
        if not text or self._busy or self._connecting:
            return
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
            task = self.store.create_conversation(derive_title(text), self._model)
            self._task_id, self._task_title = task["id"], task["title"]
        attachments = [item for item in self._attachments
                       if item.get("enabled", True) is not False]
        deferred_attachments = [item for item in self._attachments
                                if item.get("enabled", True) is False]
        vision_ready = "vision" in self._model_capabilities
        # Keep every attachment in local history so the sent user turn can
        # still show its files/images after reload. AgentEngine removes image
        # context at the Ollama boundary when the selected model lacks vision.
        extra = ctx.build_messages(attachments)
        self._history.extend(extra)
        self._history.append({"role": "user", "content": text})
        self._recount_history_tokens()
        self.store.set_messages(self._task_id, self._history, self._model)
        self.messages.append_message("user", text, attachments=ctx.display_attachments(attachments))
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

    # ------------------------------------------------------- permissioning
    def _confirm_action(self, name: str, args: dict, risk: str) -> bool:
        """Called on the worker thread; blocks it until the user answers."""
        # "Allow the rest of this task" is trust in a task, not a blank cheque:
        # a command that cannot be undone is still put in front of the user.
        if self._session_auto and risk != "destructive":
            return True
        self._permission_event.clear()
        self._permission_answer = False
        self._pending_permission = {
            "tool": name, "risk": risk, "summary": action_summary(name, args),
            "detail": json.dumps(args, ensure_ascii=False) if args else "",
            # A command reads differently depending on where it runs, so the
            # prompt states the directory rather than making you infer it.
            "command": str(args.get("command", "")) if name == "run_command" else "",
            "directory": (str(args.get("cwd") or self._working_directory or Path.home())
                          if name == "run_command" else ""),
        }
        self.permissionChanged.emit()
        allowed = self._permission_event.wait(self.PERMISSION_TIMEOUT)
        answer = bool(allowed and self._permission_answer)
        self._pending_permission = None
        self.permissionChanged.emit()
        return answer

    @Slot(bool)
    def resolvePermission(self, allowed):
        if self._pending_permission is None:
            return
        self._permission_answer = bool(allowed)
        self._permission_event.set()

    @Slot()
    def allowRestOfTask(self):
        """Approve this action and stop prompting for the remainder of the run."""
        if self._pending_permission is None:
            return
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
        self.changed.emit()
        # The mode governs commands as much as the screen, so name it for what
        # it is rather than calling all of it "screen control".
        self.toast.emit(f"Permission set to {PERMISSION_LABELS[mode]}")

    # -------------------------------------------------------------- memory
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

    # --------------------------------------------------------------- events
    def _on_event(self, event):
        kind = event.get("type")
        if kind in ("token", "thinking"):
            if not self._turn_had_message:
                self.messages.append_message("assistant", streaming=True)
                self._turn_had_message = True
            if kind == "thinking":
                if not self._think_started:
                    self._think_started = time.monotonic()
                self.messages.stream("thought", event.get("text", ""))
                self._status = "Thinking"
            else:
                if self._think_started and not self._think_seconds:
                    self._think_seconds = time.monotonic() - self._think_started
                self.messages.stream("body", event.get("text", ""))
                self._status = "Writing"
        elif kind == "message_end":
            self.messages.finish_stream(self._think_seconds, event.get("message"))
            self._turn_had_message = False
            self._think_started = 0.0
            self._think_seconds = 0.0
        elif kind == "status":
            self._status = event.get("text", "Working")
        elif kind == "session":
            self._status = "Screen control ready"
        elif kind == "tool_start":
            name = event.get("name", "action")
            icon, label = TOOL_PRESENTATION.get(name, ("bolt", name.replace("_", " ").capitalize()))
            summary = event.get("summary") or ""
            step = {"name": name, "icon": icon, "label": label, "summary": summary,
                    "detail": json.dumps(event.get("args", {}), ensure_ascii=False)[:200],
                    "state": "waiting" if event.get("confirming") else "running",
                    "risk": event.get("risk", "normal"), "ms": 0, "output": ""}
            self.messages.append_activity(step)
            self._activity = (self._activity + [step])[-60:]
            self._status = summary or label
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
            state = "declined" if event.get("declined") else ("failed" if failed else "done")
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
            patch = {"state": state, "ms": int(event.get("ms", 0) or 0), "output": output[:32000]}
            self.messages.update_last_step(**patch)
            self.dock.record_update(**patch)
            if self._activity:
                self._activity[-1] = {**self._activity[-1], **patch}
                self.activityChanged.emit()
            if event.get("name") in ("run_command", "write_file", "edit_file"):
                self.dock.refreshChanges()
            if event.get("name") in ("remember", "forget"):
                self.memoryChanged.emit()
        elif kind == "metrics":
            rate = event.get("tokens_per_second", 0)
            previous = self._run_metrics
            self._run_metrics = {
                "tokens": previous.get("tokens", 0) + int(event.get("tokens", 0) or 0),
                "prompt_tokens": int(event.get("prompt_tokens", 0) or 0),
                "cached_prompt_tokens": int(event.get("cached_prompt_tokens", 0) or 0),
                "load_ms": previous.get("load_ms", 0.0) + float(event.get("load_ms", 0.0) or 0.0),
                "total_ms": previous.get("total_ms", 0.0) + float(event.get("total_ms", 0.0) or 0.0),
                "tokens_per_second": float(rate) if isinstance(rate, (int, float)) else 0.0,
            }
            self._token_rate = f"{rate:.1f} tok/s" if isinstance(rate, (int, float)) else "—"
        elif kind == "error":
            self._set_error("The model run did not finish", event.get("text", "Something went wrong"),
                            [{"label": "Try again", "action": "regenerate"}])
        elif kind == "cancelled":
            self._status = "Stopped"
        self.changed.emit()

    def _run_done(self, history):
        self._history = history
        self._recount_history_tokens()
        self.store.set_messages(self._task_id, history, self._model)
        stopped = self._run_job is not None and self._run_job.cancel.is_set()
        elapsed = time.monotonic() - self._run_started if self._run_started else 0.0
        self._busy = False
        self._run_job = None
        self._session_auto = False
        self.messages.mark_idle()
        self.dock.settle_turn("cancelled" if stopped else ("failed" if self._error else "done"))
        if self._working_directory:
            self.dock.refreshChanges()
        self._status = "Stopped" if stopped else ("Needs attention" if self._error else "Ready when you are")
        self._refresh_tasks()
        self.changed.emit()
        if not stopped and not self._error:
            self._maybe_notify(elapsed)

    def _run_failed(self, message):
        self._busy = False
        self._run_job = None
        self._session_auto = False
        self.messages.mark_idle()
        self.dock.settle_turn("failed")
        self._status = "Needs attention"
        self._set_error("The model run did not finish", message,
                        [{"label": "Try again", "action": "regenerate"},
                         {"label": "Connection settings", "action": "settings"}])

    def _maybe_notify(self, seconds: float):
        if not notify.should_notify(seconds, self._window_active, self._notifications):
            return
        title = self._task_title if self._task_title != "New task" else "Wynxq"
        self._job(lambda cancel, emit: notify.send("Wynxq finished your task", title))

    @Slot(bool)
    def setWindowActive(self, active):
        self._window_active = bool(active)

    @Slot()
    def stop(self):
        if self._pending_permission is not None:
            self._permission_answer = False
            self._permission_event.set()
        if self._run_job:
            self._run_job.cancel.set()
            self._status = "Stopping…"
            self.changed.emit()

    # --------------------------------------------------------------- desktop
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

    # ---------------------------------------------------------------- pulls
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
            for progress in OllamaClient(endpoint).pull(model, cancel):
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

    # ----------------------------------------------------------------- misc
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

    @Slot(result=bool)
    def canClose(self):
        if self._pending_permission is not None:
            self._permission_answer = False
            self._permission_event.set()
        if self._jobs:
            for job in self._jobs:
                job.cancel.set()
            self._status = "Stopping background work…"
            self.changed.emit()
            return False
        return True

    def shutdown(self):
        self.dock.shutdown()
        if self._pending_permission is not None:
            self._permission_answer = False
            self._permission_event.set()
        for job in list(self._jobs):
            job.cancel.set()
        for job in list(self._jobs):
            job.wait(2000)
        self.desktop.disconnect()
