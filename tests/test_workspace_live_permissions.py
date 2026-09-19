"""The workspace must not freeze permissions when a task starts."""
import threading

from PySide6.QtCore import QCoreApplication

from wynxq.storage import Store
from wynxq.workspace import WorkspaceController

APP = QCoreApplication.instance() or QCoreApplication([])


class ConnectedDesktop:
    def status(self):
        return {"connected": True, "available": True, "backend": "test", "detail": "on"}

    def disconnect(self):
        return None

    def active_window(self):
        return {"title": "Test", "detail": "test"}


def test_workspace_passes_a_live_permission_provider_to_the_engine(tmp_path, monkeypatch):
    bridge = WorkspaceController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=ConnectedDesktop(),
        autoconnect=False,
    )
    bridge._online = True
    bridge._model_capabilities = ["completion", "tools", "vision"]
    bridge.newTaskMode("work")
    captured = {}

    class SpyEngine:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            captured.update(kwargs)
            return []

    def synchronous_job(fn, result=None, failure=None, event=None):
        fn(threading.Event(), lambda payload: None)
        return None

    monkeypatch.setattr("wynxq.workspace.PlanningAgentEngine", SpyEngine)
    monkeypatch.setattr("wynxq.workspace.OllamaClient", lambda endpoint: None)
    monkeypatch.setattr(bridge, "_job", synchronous_job)

    bridge.send("do a task")

    provider = captured["permission_mode"]
    assert callable(provider)
    assert provider() == "safe"

    # "Allow all in this task" is only valid while the permission setting stays
    # where it was. Tightening/changing the mode later must revoke that shortcut
    # before the next action is evaluated.
    bridge._session_auto = True
    bridge.setPermissionMode("manual")
    assert provider() == "manual"
    assert bridge._session_auto is False

    bridge._session_auto = True
    bridge.setPermissionMode("full")
    assert provider() == "full"
    assert bridge._session_auto is False

    bridge._busy = False
    bridge.shutdown()
