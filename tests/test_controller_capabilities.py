import threading

from PySide6.QtCore import QCoreApplication

from wynxq.controller import Controller


APP = QCoreApplication.instance() or QCoreApplication([])


class FakeStore:
    def __init__(self):
        self.settings = {}

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def list_conversations(self):
        return []

    def close(self):
        pass


class FakeDesktop:
    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "Off"}

    def disconnect(self):
        pass


def controller():
    return Controller(store=FakeStore(), desktop=FakeDesktop(), autoconnect=False)


def test_capability_summary_describes_desktop_readiness():
    bridge = controller()
    bridge._model_capabilities = ["completion", "thinking", "tools", "vision"]
    assert bridge.modelCapabilitySummary == "Chat · Tools · Vision · Thinking"
    assert bridge.modelSupportsTools is True
    assert bridge.modelSupportsVision is True
    assert bridge.modelSupportsThinking is True
    assert "visual desktop control" in bridge.modelCapabilityHint


def test_tools_without_vision_explain_the_limit():
    bridge = controller()
    bridge._model_capabilities = ["completion", "tools"]
    assert bridge.modelCapabilitySummary == "Chat · Tools"
    assert bridge.modelSupportsTools is True
    assert bridge.modelSupportsVision is False
    assert "needs vision" in bridge.modelCapabilityHint


def test_capability_probe_ignores_stale_model_results(monkeypatch):
    bridge = controller()
    bridge._online = True
    bridge._models = ["one", "two"]
    bridge._model = "one"
    queued = []

    def queued_job(fn, result=None, failure=None, event=None):
        queued.append((fn, result, failure))
        return object()

    monkeypatch.setattr(bridge, "_job", queued_job)
    bridge._refresh_model_capabilities()
    bridge._model = "two"
    bridge._refresh_model_capabilities()

    # Complete the newer probe first, then deliver a stale result from the old model.
    queued[1][1]({"capabilities": ["completion", "tools", "vision"], "context_length": 32768})
    queued[0][1]({"capabilities": ["completion"], "context_length": 4096})

    assert bridge.modelCapabilitySummary == "Chat · Tools · Vision"
    assert bridge.modelSupportsTools is True
    assert bridge.modelContextLength == 32768


def test_capability_probe_reuses_session_cache_without_another_job(monkeypatch):
    bridge = controller()
    bridge._online = True
    bridge._models = ["local:test"]
    bridge._model = "local:test"
    bridge._model_capability_cache[(bridge._endpoint, "local:test")] = {
        "capabilities": ["completion", "tools"],
        "context_length": 32768,
    }

    def unexpected_job(*args, **kwargs):
        raise AssertionError("cached capability metadata should not start a job")

    monkeypatch.setattr(bridge, "_job", unexpected_job)
    bridge._refresh_model_capabilities()

    assert bridge.modelCapabilities == ["completion", "tools"]
    assert bridge.modelContextLength == 32768
    assert bridge.modelCapabilitiesLoading is False


def test_capability_probe_reads_selected_model_without_blocking_controller(monkeypatch):
    bridge = controller()
    bridge._online = True
    bridge._models = ["local:test"]
    bridge._model = "local:test"

    class FakeClient:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def describe(self, model):
            assert model == "local:test"
            return {"capabilities": ["completion", "tools", "thinking"], "context_length": 128000}

    def immediate_job(fn, result=None, failure=None, event=None):
        try:
            value = fn(threading.Event(), lambda _: None)
        except Exception as exc:
            if failure:
                failure(str(exc))
        else:
            if result:
                result(value)
        return object()

    monkeypatch.setattr("wynxq.controller.OllamaClient", FakeClient)
    monkeypatch.setattr(bridge, "_job", immediate_job)
    bridge._refresh_model_capabilities()

    assert bridge.modelCapabilitiesLoading is False
    assert bridge.modelCapabilities == ["completion", "thinking", "tools"]
    assert bridge.modelCapabilitySummary == "Chat · Tools · Thinking"
    assert bridge.modelContextLength == 128000
    assert bridge.modelContextLabel == "128K native context"
