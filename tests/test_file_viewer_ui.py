"""The built-in file viewer should behave like an editor, not a text dump."""
from pathlib import Path


QML = Path(__file__).resolve().parents[1] / "wynxq" / "ui" / "Wynxq" / "FileViewer.qml"


def source() -> str:
    return QML.read_text(encoding="utf-8")


def test_find_reports_current_match_and_total():
    qml = source()
    for feature in (
        "property int findCount: 0",
        "property int findOrdinal: 0",
        "function recountFindMatches()",
        "function ordinalFor(haystack, query, target)",
        'root.findCount === 0 ? "No matches"',
        'root.findCount + (root.findCountCapped ? "+" : "")',
    ):
        assert feature in qml


def test_find_counting_is_bounded_for_large_repetitive_files():
    qml = source()
    assert "readonly property int maxFindMatches: 10000" in qml
    assert "if (count >= maxFindMatches)" in qml
    assert "findCountCapped = haystack.indexOf(query, cursor) >= 0" in qml


def test_find_updates_after_editing_and_navigation_wraps():
    qml = source()
    assert "if (root.findOpen && findInput.text.length)" in qml
    assert "if (position < 0) position = haystack.indexOf(query);" in qml
    assert "if (position < 0) position = haystack.lastIndexOf(query);" in qml
    assert "enabled: root.findCount > 0" in qml


def test_go_to_line_validates_moves_and_reveals_the_destination():
    qml = source()
    for feature in (
        'sequences: ["Ctrl+G"]',
        "function positionForLine(value)",
        "function goToLine()",
        "editor.cursorPosition = position",
        "editor.cursorRectangle.y - flick.height * 0.33",
        "flick.contentY = Math.min(maximum, desired)",
        "flick.contentX = 0",
        "validator: IntValidator",
    ):
        assert feature in qml


def test_secondary_file_actions_live_in_one_overflow():
    qml = source()
    assert 'iconName: "moreVertical"' in qml
    for action in (
        'label: "Go to line…"',
        'label: "Copy whole file"',
        'label: "Attach to conversation"',
        'label: "Terminal in containing folder"',
        'label: "Reveal outside Wynxq"',
    ):
        assert action in qml
    assert "bridge.attachPath(root.record.path)" in qml
    assert "dock.runInTerminal(" in qml


def test_find_and_go_to_line_do_not_stack_transient_toolbars():
    qml = source()
    open_find = qml[qml.index("function openFind()"):qml.index("function closeFind()")]
    open_line = qml[qml.index("function openGoLine()"):qml.index("function closeGoLine()")]
    assert "goLineOpen = false" in open_find
    assert "findOpen = false" in open_line
