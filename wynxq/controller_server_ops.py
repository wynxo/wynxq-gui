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

@staticmethod
def _endpoint_label(endpoint: str) -> str:
    try:
        parsed = urlsplit(str(endpoint or ""))
        host = parsed.hostname or str(endpoint or "")
        port = parsed.port
        return host + ((":" + str(port)) if port else "")
    except (ValueError, TypeError):
        return str(endpoint or "Ollama")


def _remember_endpoint_profile(self, name: str, endpoint: str) -> None:
    endpoint = str(endpoint or "").strip().rstrip("/")
    name = " ".join(str(name or "").split())[:32] or self._endpoint_label(endpoint)
    fresh = [dict(item) for item in self._endpoint_profiles if item["url"] != endpoint]
    fresh.append({"name": name, "url": endpoint})
    self._endpoint_profiles = fresh[:8]
    self.store.set_setting("ollama_endpoints", self._endpoint_profiles)


@Slot(str, str, result=bool)
def addEndpointProfile(self, name, endpoint):
    try:
        value = str(endpoint or "").strip().rstrip("/")
        OllamaClient(value)
    except Exception as exc:
        self._set_error("That Ollama address is not usable", str(exc))
        return False
    self._remember_endpoint_profile(str(name or ""), value)
    self.changed.emit()
    return True


@Slot(str, result=bool)
def removeEndpointProfile(self, endpoint):
    value = str(endpoint or "").strip().rstrip("/")
    if not value or value == self._default_endpoint:
        self.toast.emit("Choose another default server before removing this one.")
        return False
    if value == self._endpoint and self._busy:
        self.toast.emit("This chat is using that server right now.")
        return False
    before = len(self._endpoint_profiles)
    self._endpoint_profiles = [item for item in self._endpoint_profiles if item["url"] != value]
    if len(self._endpoint_profiles) == before:
        return False
    self.store.set_setting("ollama_endpoints", self._endpoint_profiles)
    if value == self._endpoint:
        self.selectEndpoint(self._default_endpoint)
    self.changed.emit()
    return True


@Slot(str, result=bool)
def setDefaultEndpoint(self, endpoint):
    try:
        value = str(endpoint or "").strip().rstrip("/")
        OllamaClient(value)
    except Exception as exc:
        self._set_error("That Ollama address is not usable", str(exc))
        return False
    if not any(item["url"] == value for item in self._endpoint_profiles):
        self._remember_endpoint_profile("Main", value)
    self._default_endpoint = value
    self.store.set_setting("endpoint", value)
    self.changed.emit()
    return True


@Slot(str, result=bool)
def selectEndpoint(self, endpoint):
    if self._busy or self._pulling:
        self.toast.emit("This chat is still using its current model.")
        return False
    try:
        value = str(endpoint or "").strip().rstrip("/")
        OllamaClient(value)
    except Exception as exc:
        self._set_error("That Ollama address is not usable", str(exc))
        return False
    if not any(item["url"] == value for item in self._endpoint_profiles):
        self._remember_endpoint_profile("", value)
    if value == self._endpoint:
        return True
    self._endpoint = value
    if self._task_id:
        self.store.set_conversation_runtime(self._task_id, endpoint=value)
    cached = self._endpoint_catalog_cache.get(value)
    if cached:
        models, resident = cached
        self._models = [m["name"] for m in models]
        self._catalog = [self._catalog_entry(m) for m in models]
        self._resident_models = system_info.resident_models(resident)
        self._loaded_models = [entry["name"] for entry in self._resident_models]
        self._online = True
        if self._model not in self._models and self._models:
            self._model = self._models[0]
            if self._task_id:
                self.store.set_conversation_runtime(self._task_id, model=self._model)
        self._decorate_catalog()
    else:
        self._online = False
        self._models = []
        self._catalog = []
        self._resident_models = []
        self._loaded_models = []
        self.catalogChanged.emit()
    self.changed.emit()
    self.refreshModels()
    return True


def _refresh_tasks(self):
    self._tasks = self.store.list_conversations()
    self.tasksChanged.emit()


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
    # Endpoint switches may race an older catalogue request. Generation
    # tokens make stale replies harmless instead of blocking the new server.
    self._catalog_probe_generation += 1
    generation = self._catalog_probe_generation
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
        if generation != self._catalog_probe_generation or endpoint != self._endpoint:
            return
        models, resident = payload
        self._endpoint_catalog_cache[endpoint] = (list(models), list(resident))
        self._probe_active = False
        self._models = [m["name"] for m in models]
        self._catalog = [self._catalog_entry(m) for m in models]
        self._resident_models = system_info.resident_models(resident)
        self._loaded_models = [entry["name"] for entry in self._resident_models]
        self._online = True
        if self._model not in self._models and self._models:
            preferred = next((m for m in self._favorites if m in self._models), None)
            self._model = preferred or ("qwen3.8:27b" if "qwen3.8:27b" in self._models else self._models[0])
            if self._task_id:
                self.store.set_conversation_runtime(self._task_id, model=self._model)
            else:
                self._default_model = self._model
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
        if generation != self._catalog_probe_generation or endpoint != self._endpoint:
            return
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
    if self._task_id:
        self.store.set_conversation_runtime(self._task_id, model=model, endpoint=self._endpoint)
    elif self._endpoint == self._default_endpoint:
        # Picking a model on the ordinary blank task remains the user's
        # default. A blank task pointed at a non-default server is only a
        # one-chat override and must not poison the global pair.
        self._default_model = model
        self.store.set_setting("model", model)
    self._recent_models = [model] + [m for m in self._recent_models if m != model][:5]
    self.store.set_setting("recent_models", self._recent_models)
    self._decorate_catalog()
    self._refresh_model_capabilities()
    self._refresh_tasks()


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
    """Compatibility action used by Settings: save as default and use here."""
    try:
        value = str(endpoint or "").strip().rstrip("/")
        OllamaClient(value)
    except Exception as exc:
        self._set_error("That Ollama address is not usable", str(exc))
        return False
    if self._busy or self._pulling:
        self.toast.emit("This chat is still using its current model.")
        return False
    self._remember_endpoint_profile(
        next((item["name"] for item in self._endpoint_profiles if item["url"] == value), "Main"),
        value)
    self._default_endpoint = value
    self.store.set_setting("endpoint", value)
    return self.selectEndpoint(value)


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
