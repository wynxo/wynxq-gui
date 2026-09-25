"""Mode copy and starter actions must match the capabilities the task really has."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "wynxq" / "ui"
WYNXQ_UI = UI / "Wynxq"
STARTERS = WYNXQ_UI / "TaskStarters.qml"
COMPOSER = WYNXQ_UI / "Composer.qml"
TASK_START = WYNXQ_UI / "TaskStart.qml"
HEADER = WYNXQ_UI / "TaskHeader.qml"
SIDEBAR = WYNXQ_UI / "WorkspaceSidebar.qml"
TASK_ROW = WYNXQ_UI / "TaskRow.qml"
QUICK_BAR = WYNXQ_UI / "QuickBarContent.qml"
ONBOARDING = WYNXQ_UI / "Onboarding.qml"
PALETTE = WYNXQ_UI / "CommandPalette.qml"
MAIN = UI / "Main.qml"
DEMO = ROOT / "wynxq" / "demo.py"
README = ROOT / "README.md"
RETIRED_WYNXI_SCREENSHOT = ROOT / "docs" / "screenshots" / "16-wynxi-home.png"


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
    # Browser is intentionally not permanent home chrome; it remains available
    # from the Work dock and universal quick-open.
    assert 'command: "browser", needs: "work"' not in text
    palette = PALETTE.read_text(encoding="utf-8")
    browser_line = next(line for line in palette.splitlines() if 'id: "browser"' in line)
    assert "workOnly: true" in browser_line
    assert 'needs: "codex"' not in text


def test_chat_copy_does_not_promise_tools_it_cannot_run():
    composer = COMPOSER.read_text(encoding="utf-8")
    start = TASK_START.read_text(encoding="utf-8")
    assert '"Ask a question, explain, or brainstorm…"' in composer
    assert '"Conversation only — no shell, workspace tools, or desktop control."' in start
    assert '"Conversation only — no commands, files, or desktop actions."' not in start


def test_visible_shell_uses_only_chat_and_work_modes():
    for path in (MAIN, HEADER, SIDEBAR, TASK_ROW, QUICK_BAR, COMPOSER, TASK_START, STARTERS):
        text = path.read_text(encoding="utf-8")
        assert 'taskMode === "codex"' not in text, path
        assert 'newTaskMode("codex")' not in text, path
        assert 'needs: "codex"' not in text, path
        assert 'row.mode === "codex"' not in text, path
        assert "Wynxi" not in text, path


def test_task_rows_describe_only_supported_modes():
    text = TASK_ROW.read_text(encoding="utf-8")
    assert 'row.mode === "work" ? ", Work task" : ", Chat task"' in text
    assert 'visible: row.mode === "work"' in text


def test_quick_bar_makes_the_current_task_mode_explicit():
    text = QUICK_BAR.read_text(encoding="utf-8")
    assert 'readonly property bool workMode: root.mode === "work"' in text
    assert '"Give the current Work task an instruction…"' in text
    assert '"Ask the current Chat task…"' in text
    assert 'text: root.workMode ? "Work" : "Chat"' in text


def test_onboarding_uses_the_gui_product_name():
    text = ONBOARDING.read_text(encoding="utf-8")
    assert 'Accessible.name: "Welcome to Wynxq"' in text
    assert '"Start using Wynxq"' in text


def test_command_palette_starts_work_not_a_retired_coding_product():
    text = PALETTE.read_text(encoding="utf-8")
    assert 'id: "newwork"' in text
    assert 'label: "New Work task"' in text
    assert 'id: "newcode"' not in text
    assert "Wynxi" not in text


def test_chat_palette_hides_workspace_commands_that_cannot_open():
    text = PALETTE.read_text(encoding="utf-8")
    assert 'readonly property bool workMode: !!(bridge && bridge.taskMode === "work")' in text
    for command in ("files", "terminal-panel", "changes", "context", "memory",
                    "activity", "browser", "preview", "dock"):
        line = next(line for line in text.splitlines() if f'id: "{command}"' in line)
        assert "workOnly: true" in line, command
    assert "if (item.workOnly && !palette.workMode)" in text


def test_preview_scenes_use_the_same_chat_and_work_modes_as_the_app():
    text = DEMO.read_text(encoding="utf-8")
    assert '"codex"' not in text
    assert "Wynxi" not in text
    assert 'self.scene == "work-run"' in text
    assert '("26-code-run", "work-run", "")' in text
    assert not RETIRED_WYNXI_SCREENSHOT.exists()


def test_readme_describes_the_current_modes_repo_and_preview_names():
    text = README.read_text(encoding="utf-8")
    assert "Wynxi" not in text
    assert "wynxq-gui-ai-agent" not in text
    assert "--ui-preview codex-run" not in text
    assert "git clone https://github.com/wynxo/wynxq-gui.git" in text
    assert "--ui-preview work-run" in text
