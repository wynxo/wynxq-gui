"""Task-scoped Chat / Work behavior."""
import threading

from PySide6.QtCore import QCoreApplication

from wynxq.memory import Memory
from wynxq.storage import Store
from wynxq.workspace import WorkspaceController

APP = QCoreApplication.instance() or QCoreApplication([])


class IdleDesktop:
    def __init__(self, connected=False):
        self.connected = connected

    def status(self):
        return {"connected": self.connected, "available": True,
                "backend": "test", "detail": "Off"}

    def connect(self):
        self.connected = True
        return self.status()

    def disconnect(self):
        self.connected = False

    def active_window(self):
        return {"title": "Terminal", "detail": "test"}


def controller(tmp_path, connected=False):
    return WorkspaceController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=IdleDesktop(connected), autoconnect=False,
    )


def test_new_task_starts_unlocked_and_chat_choice_locks(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.taskMode == "chat"
    assert bridge.taskModeLocked is False
    assert bridge.productName == "Wynxq GUI"

    assert bridge.setTaskMode("chat") is True
    assert bridge.taskMode == "chat"
    assert bridge.taskModeLocked is True
    assert bridge.setTaskMode("codex") is False
    bridge.shutdown()


def test_work_starts_as_locked_tool_task(tmp_path):
    bridge = controller(tmp_path)
    bridge.newTaskMode("work")
    assert bridge.taskMode == "work"
    assert bridge.taskModeLocked is True
    assert bridge.productName == "Wynxq GUI"
    bridge.shutdown()


def test_first_send_persists_chat_mode_and_reopen_restores_it(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._model_capabilities = ["completion", "tools"]
    monkeypatch.setattr(bridge, "_start_run", lambda history: None)

    bridge.send("hello from a permanent chat")
    task_id = bridge.taskId
    assert task_id
    assert bridge.taskModeLocked is True
    assert bridge.store.get_setting(f"task_mode:{task_id}") == "chat"

    bridge.newTaskMode("work")
    assert bridge.taskMode == "work"
    bridge.openTask(task_id)
    assert bridge.taskMode == "chat"
    assert bridge.taskModeLocked is True
    assert bridge.productName == "Wynxq GUI"
    bridge.shutdown()


def test_restart_recovers_all_journaled_background_plans(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    first = store.create_conversation("Foreground work", "qwen3:8b")
    second = store.create_conversation("Background work", "qwen3:8b")
    for task in (first, second):
        store.set_setting(
            f"task_plan:{task['id']}",
            [
                {"id": "inspect", "title": "Inspect", "status": "completed"},
                {"id": "edit", "title": "Edit files", "status": "in_progress"},
            ],
        )
        store.set_setting(f"task_mode:{task['id']}", "work")
    store.set_setting("workspace:last_task", first["id"])
    store.set_setting(
        "workspace:active_runs",
        [first["id"], second["id"], second["id"], "missing-task"],
    )

    bridge = WorkspaceController(store=store, desktop=IdleDesktop(), autoconnect=False)
    try:
        assert bridge.store.get_setting("workspace:active_runs") == []
        for task in (first, second):
            plan = bridge.store.get_setting(f"task_plan:{task['id']}")
            assert [step["status"] for step in plan] == ["completed", "pending"]
        assert bridge.taskId == first["id"]
    finally:
        bridge.shutdown()


def test_active_run_journal_tracks_multiple_tasks_without_duplicates(tmp_path):
    bridge = controller(tmp_path)
    first = bridge.store.create_conversation("One", "qwen3:8b")
    second = bridge.store.create_conversation("Two", "qwen3:8b")

    bridge._journal_active_run(first["id"], True)
    bridge._journal_active_run(second["id"], True)
    bridge._journal_active_run(first["id"], True)
    assert bridge.store.get_setting(bridge.ACTIVE_RUNS_KEY) == [first["id"], second["id"]]

    bridge._journal_active_run(first["id"], False)
    assert bridge.store.get_setting(bridge.ACTIVE_RUNS_KEY) == [second["id"]]
    bridge.shutdown()


def test_reopening_legacy_coding_task_migrates_to_work(tmp_path):
    bridge = controller(tmp_path)
    task = bridge.store.create_conversation("Fix the parser", "qwen3:8b")
    bridge.store.set_messages(task["id"], [{"role": "user", "content": "Fix parser"}])
    bridge.store.set_setting(f"task_mode:{task['id']}", "codex")

    bridge.openTask(task["id"])
    assert bridge.store.get_setting(f"task_mode:{task['id']}") == "work"
    assert bridge.taskMode == "work"
    assert bridge.taskModeLocked is True
    assert bridge.productName == "Wynxq GUI"
    bridge.shutdown()


def test_work_mode_is_task_scoped(tmp_path):
    bridge = controller(tmp_path, connected=True)
    assert bridge.setTaskMode("work") is True
    assert bridge.taskMode == "work"
    assert bridge.taskModeLocked is True

    # A fresh Wynxq task never inherits Work merely because screen control
    # happens to remain connected; Work and screen access are separate state.
    bridge.newTask()
    assert bridge.taskMode == "chat"
    assert bridge.taskModeLocked is False
    bridge.shutdown()


def test_choosing_work_does_not_enable_screen_control(tmp_path):
    bridge = controller(tmp_path, connected=False)
    assert bridge.desktopEnabled is False
    assert bridge.setTaskMode("work") is True
    assert bridge.taskMode == "work"
    assert bridge.desktopEnabled is False
    assert bridge.desktop.connected is False
    bridge.shutdown()


def test_reopening_work_does_not_enable_screen_control(tmp_path):
    bridge = controller(tmp_path, connected=False)
    task = bridge.store.create_conversation("Work task", "qwen3:8b")
    bridge.store.set_messages(task["id"], [{"role": "user", "content": "run tests"}])
    bridge.store.set_setting(f"task_mode:{task['id']}", "work")
    bridge.openTask(task["id"])
    assert bridge.store.get_setting(f"task_mode:{task['id']}") == "work"
    assert bridge.taskMode == "work"
    assert bridge.desktopEnabled is False
    assert bridge.desktop.connected is False
    bridge.shutdown()


# ------------------------------------------------------- chat is only chat
# A Chat task is not a Work task with the tools declined: the tools are never
# offered to the model, so there is nothing for it to try and nothing to approve.

class ToolDesktop(IdleDesktop):
    def __init__(self):
        super().__init__(connected=True)
        self.calls = []

    def execute(self, name, args, cancel):
        self.calls.append(name)
        return {"ok": True, "action": name}


class Recorder:
    def __init__(self, script=(), capabilities=("completion", "tools", "vision")):
        self.script = list(script)
        self.requests = []
        self._capabilities = list(capabilities)

    def capabilities(self, model):
        return self._capabilities

    def stream_chat(self, payload, cancel):
        self.requests.append(payload)
        chunk = self.script.pop(0) if self.script else {"message": {"content": "ok"}, "done": True}
        for part in (chunk if isinstance(chunk, list) else [chunk]):
            yield part


def engine_run(bridge, mode, script=(), memory=None):
    """Run one turn the way the controller does, capturing the request."""
    from wynxq.workspace import PlanningAgentEngine
    client = Recorder(script)
    desktop = ToolDesktop()
    events = []
    PlanningAgentEngine(client, desktop, memory).run(
        [{"role": "user", "content": "go"}], "local:test", mode == "work",
        threading.Event(), events.append, permission_mode="full",
        confirm=lambda *a: True, tools_allowed=mode != "chat")
    return client, desktop, events


def test_a_chat_task_is_offered_no_tools_at_all(tmp_path):
    client, desktop, _ = engine_run(controller(tmp_path), "chat")
    assert client.requests[0].get("tools") is None
    assert desktop.calls == []


def test_a_work_task_is_offered_the_local_tools(tmp_path):
    client, _, _ = engine_run(controller(tmp_path), "work")
    offered = {tool["function"]["name"] for tool in client.requests[0]["tools"]}
    assert "run_command" in offered
    assert "open_app" in offered


def test_a_chat_task_cannot_run_a_command_even_if_the_model_asks(tmp_path):
    client, desktop, events = engine_run(
        controller(tmp_path), "chat",
        [{"message": {"tool_calls": [{"function": {"name": "run_command",
                                                   "arguments": {"command": "rm -rf ~"}}}]}, "done": True},
         {"message": {"content": "I cannot do that here."}, "done": True}])
    assert desktop.calls == []
    assert len(client.requests) == 1
    assert not any(event["type"] in {"tool_start", "tool_end"} for event in events)
    assert any(event["type"] == "error" and "tools are disabled" in event["text"]
               for event in events)


def test_a_chat_task_is_told_plainly_what_it_cannot_do(tmp_path):
    client, _, events = engine_run(controller(tmp_path), "chat")
    system = client.requests[0]["messages"][0]["content"]
    assert "This is a Chat task" in system
    assert "cannot" in system
    assert "run commands" in system
    # The desktop prompt's instructions to act must not survive into it.
    assert "For command-line work use run_command" not in system
    assert any(event.get("type") == "status" and "Chat task" in event.get("text", "")
               for event in events)


def test_a_chat_task_has_no_plan_tool_either(tmp_path):
    client, _, _ = engine_run(controller(tmp_path), "chat")
    assert client.requests[0].get("tools") is None
    work, _, _ = engine_run(controller(tmp_path), "work")
    assert "update_plan" in {tool["function"]["name"] for tool in work.requests[0]["tools"]}


def test_chat_recalls_existing_memory_but_never_offers_or_runs_memory_tools(tmp_path):
    memory = Memory(tmp_path / "memory.md")
    memory.remember("Answers in Portuguese")
    before = memory.read()
    client, desktop, events = engine_run(
        controller(tmp_path), "chat",
        [{"message": {"tool_calls": [{"function": {"name": "remember",
                                                   "arguments": {"note": "Learned in a chat"}}}]}, "done": True}],
        memory=memory)
    assert "tools" not in client.requests[0]
    assert "Answers in Portuguese" in client.requests[0]["messages"][0]["content"]
    assert memory.read() == before
    assert desktop.calls == []
    assert not any(event["type"] in {"tool_start", "tool_end"} for event in events)


def test_legacy_mode_cannot_be_used_for_new_tasks(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.setTaskMode("codex") is False
    bridge.newTaskMode("codex")
    assert bridge.taskMode == "chat"
    assert bridge.taskModeLocked is False
    bridge.shutdown()


def test_the_controller_puts_a_chat_task_into_chat_only_mode(tmp_path, monkeypatch):
    bridge = controller(tmp_path, connected=True)
    bridge._online = True
    bridge._model_capabilities = ["completion", "tools"]
    captured = {}

    class Spy:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, *args, **kwargs):
            captured.update(kwargs)
            return []

    def job(fn, result=None, failure=None, event=None):
        fn(threading.Event(), lambda payload: None)
        return None

    monkeypatch.setattr("wynxq.workspace.PlanningAgentEngine", Spy)
    monkeypatch.setattr("wynxq.workspace.OllamaClient", lambda endpoint: None)
    monkeypatch.setattr(bridge, "_job", job)

    bridge.send("just talk to me")
    assert bridge.taskMode == "chat"
    assert captured["tools_allowed"] is False

    bridge._busy = False
    bridge.newTaskMode("work")
    bridge.send("now do something")
    assert bridge.taskMode == "work"
    assert captured["tools_allowed"] is True
    bridge.shutdown()
