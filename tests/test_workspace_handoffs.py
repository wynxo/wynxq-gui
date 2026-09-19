"""Workspace tools should hand context to each other without stale UI state."""
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "wynxq" / "ui" / "Wynxq"


def qml(name: str) -> str:
    return (MODULE / name).read_text(encoding="utf-8")


def function_body(text: str, name: str) -> str:
    """Small source-contract helper: isolate one QML function by brace depth."""
    marker = f"function {name}("
    start = text.index(marker)
    opening = text.index("{", start)
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening:index + 1]
    raise AssertionError(f"unterminated QML function {name}")


def test_terminal_can_reveal_its_real_working_directory_in_files():
    terminal = qml("TerminalPanel.qml")
    workspace = qml("WorkspaceDock.qml")
    reveal = function_body(workspace, "revealDirectoryInFiles")
    assert "signal revealDirectory(string path)" in terminal
    assert 'tooltip: "Show this folder in Files"' in terminal
    assert "root.revealDirectory(root.dock.terminalDirectory)" in terminal
    assert 'dock.setTab("files")' in reveal
    assert "dock.revealFile(path)" in reveal


def test_cross_panel_reveal_clears_a_stale_file_search_first():
    explorer = qml("FileExplorer.qml")
    workspace = qml("WorkspaceDock.qml")
    reveal = function_body(workspace, "revealDirectoryInFiles")
    assert "function clearFilter()" in explorer
    assert 'root.dock.setFileFilter("")' in explorer
    assert "if (filesLoader.item) filesLoader.item.clearFilter();" in reveal
    assert reveal.index("filesLoader.item.clearFilter()") < reveal.index("dock.revealFile(path)")


def test_permanent_workspace_panel_is_solid_not_always_on_glass():
    workspace = qml("WorkspaceDock.qml")
    panel_section = workspace[workspace.index("// -------------------------------------------------------- the panel"):]
    panel_section = panel_section[:panel_section.index("Loader {\n                id: planLoader")]
    assert "Rectangle {" in panel_section
    assert "color: Theme.background" in panel_section
    assert "GlassSurface {" not in panel_section
