from PySide6.QtCore import QCoreApplication

from wynxq import engine
from wynxq.workspace import PLAN_STATES, WorkspaceController


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

    def execute(self, name, args, cancel=None):
        return {"ok": True, "action": name}

    def disconnect(self):
        pass


def controller():
    bridge = WorkspaceController(store=FakeStore(), desktop=FakeDesktop(), autoconnect=False)
    bridge._task_id = "task-1"
    return bridge


def sample_steps():
    return [
        {"id": "inspect", "title": "Inspect the current workspace", "status": "completed"},
        {"id": "edit", "title": "Implement the layout changes", "status": "in_progress"},
        {"id": "verify", "title": "Run the UI verification", "status": "pending"},
    ]


def test_plan_tool_is_registered_as_nonvisual_low_risk_ui_work():
    bridge = controller()
    assert bridge is not None
    assert "update_plan" in engine._SCHEMAS
    assert "update_plan" in engine._NONVISUAL
    assert "update_plan" in engine.LOW_RISK
    assert any(tool["function"]["name"] == "update_plan" for tool in engine.TOOLS)


def test_plan_state_normalises_and_persists_per_task():
    bridge = controller()
    bridge._set_plan(sample_steps())

    assert bridge.planSteps == sample_steps()
    assert bridge.planSummary == "1 of 3 complete"
    assert bridge.store.settings["task_plan:task-1"] == sample_steps()
    assert bridge._saved_plan("task-1") == sample_steps()


def test_plan_normalisation_bounds_content_and_states():
    bridge = controller()
    noisy = [
        {"id": "same", "title": "  First   step  ", "status": "completed"},
        {"id": "same", "title": "Second step", "status": "made-up"},
    ] + [{"id": f"step-{i}", "title": f"Step {i}", "status": "pending"} for i in range(20)]

    bridge._set_plan(noisy)
    rows = bridge.planSteps
    assert len(rows) == 8
    assert rows[0] == {"id": "same", "title": "First step", "status": "completed"}
    assert rows[1]["id"] != rows[0]["id"]
    assert rows[1]["status"] == "pending"
    assert all(row["status"] in PLAN_STATES for row in rows)


def test_update_plan_event_updates_state_without_creating_activity():
    bridge = controller()
    before_messages = list(bridge.messages.items)
    before_activity = list(bridge.activity)

    bridge._on_event({
        "type": "tool_start",
        "name": "update_plan",
        "args": {"steps": sample_steps(), "explanation": "Tightening the workspace UI"},
        "summary": "Update plan",
    })
    bridge._on_event({"type": "tool_end", "name": "update_plan", "result": {"ok": True}})

    assert bridge.planSteps == sample_steps()
    assert bridge.status == "Tightening the workspace UI"
    assert bridge.messages.items == before_messages
    assert bridge.activity == before_activity


def test_plan_tool_messages_are_removed_before_conversation_persistence():
    history = [
        {"role": "user", "content": "Improve this UI"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "update_plan", "arguments": {"steps": sample_steps()}}},
            {"function": {"name": "run_command", "arguments": {"command": "pytest -q"}}},
        ]},
        {"role": "tool", "tool_name": "update_plan", "content": '{"ok": true}'},
        {"role": "tool", "tool_name": "run_command", "content": '{"ok": true}'},
    ]

    cleaned = WorkspaceController._strip_plan_history(history)
    assert all(message.get("tool_name") != "update_plan" for message in cleaned)
    calls = [call for message in cleaned for call in message.get("tool_calls", [])]
    assert [call["function"]["name"] for call in calls] == ["run_command"]
    assert any(message.get("tool_name") == "run_command" for message in cleaned)


def test_settling_plan_resolves_only_the_current_step():
    bridge = controller()
    bridge._set_plan(sample_steps())
    bridge._settle_plan("completed")

    assert [row["status"] for row in bridge.planSteps] == ["completed", "completed", "pending"]
