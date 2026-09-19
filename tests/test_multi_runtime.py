"""Concurrent chats keep their own model, endpoint, stream and worker."""
import threading
import time

from PySide6.QtCore import QCoreApplication

from wynxq.controller import _RunDesktop
from wynxq.product import ProductController
from wynxq.storage import Store
import wynxq.workspace as workspace_module

APP = QCoreApplication.instance() or QCoreApplication([])


class IdleDesktop:
    def __init__(self):
        self.connected = False
        self.calls = []

    def status(self):
        return {"connected": self.connected, "available": True,
                "backend": "test", "detail": "Off"}

    def execute(self, name, arguments, cancel=None):
        self.calls.append((name, dict(arguments)))
        return {"ok": True}

    def disconnect(self):
        self.connected = False

    def active_window(self):
        return {"title": "", "detail": "test"}


class BlockingEngine:
    gates = {}
    started = {}
    seen = []

    def __init__(self, client, desktop, memory=None, browser_open=None):
        self.endpoint = client.endpoint
        self.desktop = desktop

    def run(self, messages, model, desktop_enabled, cancel, emit, **kwargs):
        key = (self.endpoint, model)
        self.seen.append(key)
        self.started.setdefault(key, threading.Event()).set()
        emit({"type": "token", "text": f"streaming {model}"})
        gate = self.gates.setdefault(key, threading.Event())
        while not gate.wait(0.01):
            if cancel.is_set():
                emit({"type": "cancelled"})
                return list(messages)
        message = {"role": "assistant",
                   "content": f"finished {model} on {self.endpoint}"}
        emit({"type": "message_end", "message": message})
        return list(messages) + [message]


def pump_until(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    APP.processEvents()
    return bool(predicate())


def _raw_model(name):
    return {"name": name, "size": 1, "details": {
        "family": "qwen", "parameter_size": "", "quantization_level": ""
    }}


def test_two_chats_generate_concurrently_on_different_servers_and_models(tmp_path, monkeypatch):
    BlockingEngine.gates = {}
    BlockingEngine.started = {}
    BlockingEngine.seen = []
    monkeypatch.setattr(workspace_module, "PlanningAgentEngine", BlockingEngine)

    bridge = ProductController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=IdleDesktop(), autoconnect=False,
    )
    # This test is about chat/session isolation, not a live network catalogue.
    bridge.refreshModels = lambda: None
    bridge._refresh_model_capabilities = lambda: None

    first_endpoint = "http://192.168.178.29:11434"
    second_endpoint = "http://192.168.178.128:11434"
    first_model = "qwen3.8:27b"
    second_model = "qwen3.5:4b"
    bridge._endpoint_catalog_cache[first_endpoint] = ([_raw_model(first_model)], [])
    bridge._endpoint_catalog_cache[second_endpoint] = ([_raw_model(second_model)], [])

    assert bridge.addEndpointProfile("Main", first_endpoint)
    assert bridge.addEndpointProfile("Small box", second_endpoint)
    assert bridge.setDefaultEndpoint(first_endpoint)
    assert bridge.selectEndpoint(first_endpoint)
    bridge.setModel(first_model)
    assert bridge.online

    bridge.send("first chat")
    first_task = bridge.taskId
    first_key = (first_endpoint, first_model)
    assert pump_until(lambda: BlockingEngine.started.get(first_key, threading.Event()).is_set())
    assert bridge.busy

    # The first stream keeps going, but navigation/new-chat is immediately free.
    bridge.newTask()
    assert bridge.taskId == ""
    assert not bridge.busy
    assert bridge.selectEndpoint(second_endpoint)
    bridge.setModel(second_model)
    bridge.send("second chat")
    second_task = bridge.taskId
    second_key = (second_endpoint, second_model)
    assert second_task and second_task != first_task
    assert pump_until(lambda: BlockingEngine.started.get(second_key, threading.Event()).is_set())
    assert sum(bool(state.get("busy")) for state in bridge._run_sessions.values()) == 2

    running = {item["id"]: item for group in bridge.taskGroups for item in group["items"]}
    assert running[first_task]["running"] is True
    assert running[second_task]["running"] is True
    assert running[first_task]["model"] == first_model
    assert running[second_task]["model"] == second_model

    # Switching to A shows A's live model/message state, not B's stream.
    bridge.openTask(first_task)
    assert bridge.busy
    assert bridge.endpoint == first_endpoint
    assert bridge.model == first_model
    assert "streaming " + first_model in bridge.messages.items[-1]["body"]

    bridge.openTask(second_task)
    assert bridge.busy
    assert bridge.endpoint == second_endpoint
    assert bridge.model == second_model
    assert "streaming " + second_model in bridge.messages.items[-1]["body"]

    # Finish in the opposite order. Each result persists to its originating chat.
    BlockingEngine.gates[second_key].set()
    assert pump_until(lambda: not bridge._run_sessions[second_task]["busy"])
    assert bridge.busy is False
    BlockingEngine.gates[first_key].set()
    assert pump_until(lambda: not bridge._run_sessions[first_task]["busy"])

    first_saved = bridge.store.get_messages(first_task)
    second_saved = bridge.store.get_messages(second_task)
    assert first_saved[-1]["content"] == f"finished {first_model} on {first_endpoint}"
    assert second_saved[-1]["content"] == f"finished {second_model} on {second_endpoint}"
    assert bridge.store.get_conversation(first_task)["endpoint"] == first_endpoint
    assert bridge.store.get_conversation(first_task)["model"] == first_model
    assert bridge.store.get_conversation(second_task)["endpoint"] == second_endpoint
    assert bridge.store.get_conversation(second_task)["model"] == second_model

    bridge.shutdown()


def test_background_run_cannot_drive_the_shared_screen(tmp_path):
    bridge = ProductController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=IdleDesktop(), autoconnect=False,
    )
    bridge.desktop.connected = True
    bridge._task_id = "visible"
    background = _RunDesktop(bridge, "other")
    assert background.status()["connected"] is False
    denied = background.execute("click", {"x": 10, "y": 20})
    assert denied["ok"] is False
    assert "foreground-only" in denied["error"]

    foreground = _RunDesktop(bridge, "visible")
    assert foreground.status()["connected"] is True
    assert foreground.execute("click", {"x": 10, "y": 20})["ok"] is True
    bridge.shutdown()


def test_endpoint_profiles_migrate_the_existing_server_as_main(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.set_setting("endpoint", "http://192.168.178.29:11434")
    bridge = ProductController(store=store, desktop=IdleDesktop(), autoconnect=False)
    try:
        profiles = bridge.endpointProfiles
        assert any(item["name"] == "Main"
                   and item["url"] == "http://192.168.178.29:11434"
                   and item["default"] for item in profiles)
        assert bridge.addEndpointProfile(
            "Second", "http://192.168.178.128:11434")
        assert {item["name"] for item in bridge.endpointProfiles} >= {"Main", "Second"}
    finally:
        bridge.shutdown()
