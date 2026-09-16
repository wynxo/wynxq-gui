"""Mode copy and starter actions must match the capabilities the task really has."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "wynxo" / "ui"
WYNXO_UI = UI / "Wynxo"
STARTERS = WYNXO_UI / "TaskStarters.qml"
COMPOSER = WYNXO_UI / "Composer.qml"
TASK_START = WYNXO_UI / "TaskStart.qml"
HEADER = WYNXO_UI / "TaskHeader.qml"
SIDEBAR = WYNXO_UI / "WorkspaceSidebar.qml"
PALETTE = WYNXO_UI / "CommandPalette.qml"
MAIN = UI / "Main.qml"


def test_locked_chat_starters_are_conversation_only():
    text = STARTERS.read_text(encoding="utf-8")
    assert 'readonly property bool lockedChat: root.mode === "chat" && !root.modeOpen' in text
    block = text.split("if (root.lockedChat) {", 1)[1].split("return list;", 1)[0]
    assert "command:" not in block
    assert "Explain a concept" in block
    assert "Review some code" in block
    assert "Brainstorm" in block


def test_tool_starters_promote_a_fresh_task_to_work():
    text = STARTERS.read_text(encoding="utf-8")
    assert 'command: "files", needs: "work"' in text
    assert 'command: "terminal-panel", needs: "work"' in text
    assert 'label: "Read my screen", icon: "eye", needs: "work"' in text
    assert 'label: "Run a command", icon: "bolt", needs: "work"' in text
    assert 'command: "browser", needs: "work"' in text
    assert 'needs: "codex"' not in text


def test_chat_copy_does_not_promise_tools_it_cannot_run():
    composer = COMPOSER.read_text(encoding="utf-8")
    start = TASK_START.read_text(encoding="utf-8")
    assert '"Ask a question, explain, or brainstorm…"' in composer
    assert '"Conversation only — no shell, workspace tools, or desktop control."' in start
    assert '"Conversation only — no commands, files, or desktop actions."' not in start


def test_visible_shell_uses_only_chat_and_work_modes():
    for path in (MAIN, HEADER, SIDEBAR, COMPOSER, TASK_START, STARTERS):
        text = path.read_text(encoding="utf-8")
        assert 'taskMode === "codex"' not in text, path
        assert 'newTaskMode("codex")' not in text, path
        assert 'needs: "codex"' not in text, path
        assert "Wynxi" not in text, path


def test_command_palette_starts_work_not_a_retired_coding_product():
    text = PALETTE.read_text(encoding="utf-8")
    assert 'id: "newwork"' in text
    assert 'label: "New Work task"' in text
    assert 'id: "newcode"' not in text
    assert "Wynxi" not in text
