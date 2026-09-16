"""Product-level Chat / Work switching and autonomy behavior."""
from PySide6.QtCore import QCoreApplication

from wynxo.product import ProductController
from wynxo.storage import Store

APP = QCoreApplication.instance() or QCoreApplication([])


class IdleDesktop:
    def __init__(self):
        self.connected = False

    def status(self):
        return {"connected": self.connected, "available": True,
                "backend": "test", "detail": "Off"}

    def connect(self):
        self.connected = True
        return self.status()

    def disconnect(self):
        self.connected = False

    def active_window(self):
        return {"title": "", "detail": "test"}


def controller(tmp_path):
    return ProductController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=IdleDesktop(), autoconnect=False,
    )


def test_existing_task_can_switch_between_chat_and_work_without_losing_history(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("Existing task", "qwen3:8b")
    messages = [
        {"role": "user", "content": "Explain this parser"},
        {"role": "assistant", "content": "It parses tokens."},
    ]
    bridge.store.set_messages(task["id"], messages, "qwen3:8b")
    bridge.openTask(task["id"])

    assert bridge.taskMode == "chat"
    assert bridge.taskModeLocked is False
    assert bridge.setTaskMode("work") is True
    assert bridge.taskMode == "work"
    assert bridge.store.get_setting(f"task_mode:{task['id']}") == "work"
    assert bridge.store.get_messages(task["id"]) == messages

    assert bridge.setTaskMode("chat") is True
    assert bridge.taskMode == "chat"
    assert bridge.store.get_setting(f"task_mode:{task['id']}") == "chat"
    assert bridge.store.get_messages(task["id"]) == messages
    bridge.shutdown()


def test_mode_switch_is_disabled_only_while_a_run_or_connection_is_active(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.taskModeLocked is False

    bridge._busy = True
    assert bridge.taskModeLocked is True
    assert bridge.setTaskMode("work") is False
    assert bridge.taskMode == "chat"

    bridge._busy = False
    bridge._connecting = True
    assert bridge.taskModeLocked is True
    assert bridge.setTaskMode("work") is False

    bridge._connecting = False
    assert bridge.taskModeLocked is False
    assert bridge.setTaskMode("work") is True
    bridge.shutdown()


def test_changing_autonomy_revokes_allow_rest_of_task(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.permissionMode == "safe"
    bridge._session_auto = True

    bridge.setPermissionMode("auto")

    assert bridge.permissionMode == "auto"
    assert bridge._session_auto is False
    bridge.shutdown()


def test_runtime_entrypoint_uses_the_live_product_controller():
    from pathlib import Path
    entrypoint = Path(__file__).resolve().parents[1] / "wynxo" / "__main__.py"
    text = entrypoint.read_text(encoding="utf-8")
    assert "from .product import ProductController" in text
    assert "controller = ProductController(" in text
