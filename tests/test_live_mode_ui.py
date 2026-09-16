"""The shell must expose the real Chat / Work execution state."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "wynxo" / "ui" / "Wynxo"
HEADER = UI / "TaskHeader.qml"
ASSISTANT = UI / "AssistantMessage.qml"
WORKSPACE_MODE = UI / "WorkspaceMode.qml"


def test_header_keeps_chat_and_work_live_after_a_task_exists():
    text = HEADER.read_text(encoding="utf-8")
    assert 'readonly property bool canChooseMode: !!(bridge && !bridge.busy && !bridge.connecting)' in text
    assert '{ id: "chat", label: "Chat"' in text
    assert '{ id: "work", label: "Work"' in text
    assert "taskModeLocked" not in text


def test_work_autonomy_is_visible_and_directly_selectable():
    text = HEADER.read_text(encoding="utf-8")
    assert 'visible: root.resolvedMode === "work"' in text
    for mode, label in (("manual", "Manual"), ("safe", "Safe"),
                        ("auto", "Auto"), ("full", "Full")):
        assert f'id: "{mode}"' in text
        assert label in text
    assert "bridge.setPermissionMode(id)" in text
    assert "Full autopilot" in text


def test_retired_coding_product_cannot_leak_back_into_output_or_mode_state():
    for path in (HEADER, ASSISTANT, WORKSPACE_MODE):
        text = path.read_text(encoding="utf-8")
        assert '"codex"' not in text, path.name
        assert "Wynxi" not in text, path.name
    assert 'if (mode === "work") return "Work";' in WORKSPACE_MODE.read_text(encoding="utf-8")
