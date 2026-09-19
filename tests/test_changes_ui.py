"""The Changes panel should hand files to the rest of the workspace cleanly."""
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "wynxq" / "ui" / "Wynxq"


def test_changed_files_offer_the_same_workspace_handoffs_as_the_file_tree():
    qml = (MODULE / "ChangesPanel.qml").read_text(encoding="utf-8")
    for feature in (
        'label: "Copy relative path"',
        'label: "Reveal in file manager"',
        'label: "Terminal in containing folder"',
        'label: "Attach to conversation"',
        "root.dock.runInTerminal(",
        "bridge.revealPath(absolute)",
        "bridge.attachPath(absolute)",
    ):
        assert feature in qml


def test_deleted_files_do_not_offer_actions_that_require_a_live_file():
    qml = (MODULE / "ChangesPanel.qml").read_text(encoding="utf-8")
    assert 'readonly property bool existsInWorktree: modelData.status !== "D"' in qml
    # Open, reveal and attach all explicitly share the worktree-exists guard.
    assert qml.count("disabled: !change.existsInWorktree") >= 3


def test_destructive_discard_remains_separated_from_navigation_actions():
    qml = (MODULE / "ChangesPanel.qml").read_text(encoding="utf-8")
    discard = qml.index('{ id: "revert", label: "Discard changes"')
    assert discard > qml.index('{ separator: true }')
    assert 'danger: true' in qml[discard:discard + 120]
