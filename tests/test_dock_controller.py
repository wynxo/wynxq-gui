"""The dock controller, driven the way the UI drives it.

Needs a Qt application object but no window, so it runs anywhere the rest of
the Qt tests do.
"""
import shutil
import subprocess
import time

import pytest

pytest.importorskip("PySide6.QtCore")

from wynxo.dock import DockController, TABS          # noqa: E402
from wynxo.storage import Store                       # noqa: E402


@pytest.fixture(scope="module")
def application():
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "dock.sqlite3")
    yield store
    store.close()


@pytest.fixture
def dock(application, store):
    controller = DockController(store=store)
    yield controller
    controller.shutdown()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('x')\n")
    (root / "README.md").write_text("# Hi\n")
    return root


def settle(application, predicate, seconds=5.0):
    """Spin the event loop the way the GUI does until async work lands."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------ the tab rules
def test_the_dock_starts_closed_and_toggles(dock):
    assert dock.visible is False
    dock.toggle()
    assert dock.visible is True
    dock.toggle()
    assert dock.visible is False


def test_a_suggestion_is_honoured_before_the_user_has_chosen(dock):
    dock.setVisible(True)
    dock.suggest("terminal")
    assert dock.tab == "terminal"


def test_a_suggestion_is_ignored_once_the_user_has_chosen_a_tab(dock):
    """The rule the whole dock hangs on: nothing moves the panel you picked."""
    dock.setVisible(True)
    dock.setTab("changes")
    dock.suggest("terminal")
    dock.suggest("files")
    assert dock.tab == "changes"


def test_opening_a_tab_that_is_already_showing_closes_the_panel(dock):
    dock.openTab("files")
    assert dock.visible is True and dock.tab == "files"
    dock.openTab("files")
    assert dock.visible is False


def test_an_unknown_tab_is_refused(dock):
    dock.setTab("files")
    dock.setTab("nonsense")
    assert dock.tab == "files"
    assert {entry["id"] for entry in dock.tabs} == set(TABS)


def test_every_tab_names_a_label_an_icon_and_a_shortcut(dock):
    for entry in dock.tabs:
        assert entry["label"] and entry["icon"] and entry["shortcut"]


def test_workspace_tools_can_be_reordered_hidden_and_restored(dock):
    original = [entry["id"] for entry in dock.tabs]
    dock.moveTab("terminal", -1)
    moved = [entry["id"] for entry in dock.tabs]
    assert moved.index("terminal") == max(0, original.index("terminal") - 1)

    dock.setTabHidden("browser", True)
    assert "browser" not in {entry["id"] for entry in dock.tabs}

    dock.openTab("browser")
    assert "browser" in {entry["id"] for entry in dock.tabs}

    dock.resetTabLayout()
    assert [entry["id"] for entry in dock.tabs] == list(TABS)


def test_workspace_tool_layout_persists(application, tmp_path):
    path = tmp_path / "dock-layout.sqlite3"
    store = Store(path)
    first = DockController(store=store)
    first.moveTab("preview", -1)
    first.setTabHidden("memory", True)
    expected = [entry["id"] for entry in first.tabs]
    first.shutdown()
    store.close()

    store = Store(path)
    second = DockController(store=store)
    try:
        assert [entry["id"] for entry in second.tabs] == expected
    finally:
        second.shutdown()
        store.close()


def test_the_width_is_clamped_to_something_usable(dock):
    dock.setWidth(10)
    assert dock.width == dock.minimumWidth
    dock.setWidth(100000)
    assert dock.width == dock.maximumWidth
    dock.setWidth(420)
    assert dock.width == 420


def test_the_dock_remembers_where_it_was_left(application, tmp_path):
    path = tmp_path / "remember.sqlite3"
    store = Store(path)
    first = DockController(store=store)
    first.setVisible(True)
    first.setWidth(455)
    first.setTab("terminal")
    first.shutdown()
    store.close()

    store = Store(path)
    second = DockController(store=store)
    try:
        assert second.visible is True
        assert second.width == 455
        assert second.tab == "terminal"
        # A remembered choice is still the user's, so it still wins.
        second.suggest("files")
        assert second.tab == "terminal"
    finally:
        second.shutdown()
        store.close()


# ---------------------------------------------------------------- the files
def test_opening_a_project_fills_the_tree(dock, project):
    assert dock.set_project(str(project)) is True
    assert dock.projectName == "proj"
    assert dock.fileModel.rowCount() == 2          # src, README.md


def test_expanding_a_folder_splices_its_children_in(dock, project):
    dock.set_project(str(project))
    dock.toggleFolder(str(project / "src"))
    assert dock.fileModel.rowCount() == 3
    dock.toggleFolder(str(project / "src"))
    assert dock.fileModel.rowCount() == 2


def test_opening_a_file_loads_it_and_selects_it(dock, project):
    dock.set_project(str(project))
    assert dock.openFile(str(project / "README.md")) is True
    assert dock.filePath.endswith("README.md")
    assert dock.file["text"] == "# Hi\n"
    assert dock.fileModified is False


def test_editing_marks_the_buffer_dirty_and_saving_clears_it(dock, project):
    dock.set_project(str(project))
    target = project / "README.md"
    dock.openFile(str(target))
    dock.setFileBuffer("# Changed\n")
    assert dock.fileModified is True
    assert target.read_text() == "# Hi\n"          # nothing on disk yet
    assert dock.saveFile() is True
    assert target.read_text() == "# Changed\n"
    assert dock.fileModified is False


def test_external_change_blocks_save_and_keeps_the_dirty_buffer(dock, project):
    target = project / "README.md"
    dock.set_project(str(project))
    assert dock.openFile(str(target)) is True
    dock.setFileBuffer("# Mine\n")
    assert dock.fileModified is True

    target.write_text("# Them\n")
    assert dock.saveFile() is False

    assert target.read_text() == "# Them\n"
    assert dock._viewer_buffer == "# Mine\n"
    assert dock.fileModified is True


def test_discarding_an_edit_restores_the_loaded_text(dock, project):
    dock.set_project(str(project))
    dock.openFile(str(project / "README.md"))
    dock.setFileBuffer("nonsense")
    dock.revertFileBuffer()
    assert dock.fileModified is False
    assert (project / "README.md").read_text() == "# Hi\n"


def test_dirty_buffer_blocks_programmatic_destructive_transitions(dock, project, tmp_path):
    """The Python boundary protects edits even when a caller bypasses QML."""
    other = tmp_path / "other"
    other.mkdir()
    target = project / "README.md"
    replacement = project / "src" / "app.py"

    assert dock.set_project(str(project)) is True
    assert dock.openFile(str(target)) is True
    dock.setFileBuffer("# unsaved in memory\n")
    assert dock.fileModified is True

    # Reopening the same file is a no-op, never a reload from disk.
    assert dock.openFile(str(target)) is True
    assert dock._viewer_buffer == "# unsaved in memory\n"
    assert dock.fileModified is True

    assert dock.openFile(str(replacement)) is False
    assert dock.filePath == str(target)
    assert dock._viewer_buffer == "# unsaved in memory\n"
    assert dock.closeFile() is False
    assert dock.filePath == str(target)
    assert dock.set_project(str(other)) is False
    assert dock.projectPath == str(project)
    assert dock._viewer_buffer == "# unsaved in memory\n"

    # An explicit discard is the permission to make those transitions.
    dock.revertFileBuffer()
    assert dock.openFile(str(replacement)) is True
    assert dock.closeFile() is True
    assert dock.set_project(str(other)) is True
    assert dock.projectPath == str(other)


def test_a_file_outside_the_project_is_refused_by_the_viewer(dock, project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("not yours")
    dock.set_project(str(project))
    dock.openFile(str(outside))
    assert dock.file.get("error")
    assert dock.file.get("text") == ""


def test_filtering_finds_files_by_name(application, dock, project):
    dock.set_project(str(project))
    dock.setFileFilter("app")
    assert settle(application, lambda: any(
        match["name"] == "app.py" for match in dock.fileMatches))
    dock.setFileFilter("")
    assert dock.fileMatches == []


def test_stale_file_search_results_never_replace_a_newer_query(
        application, dock, project, monkeypatch):
    started = []
    finished = []

    def fake_search(root, needle, *, limit, show_hidden):
        started.append(needle)
        time.sleep(0.30 if needle == "slow" else 0.01)
        finished.append(needle)
        return [{"name": f"{needle}.py", "path": str(project / f"{needle}.py")}]

    monkeypatch.setattr("wynxo.dock.files._search_tree_impl", fake_search)
    dock.set_project(str(project))
    dock.setFileFilter("slow")
    assert settle(application, lambda: "slow" in started)

    dock.setFileFilter("fast")
    assert settle(application, lambda: set(finished) == {"slow", "fast"})
    assert settle(application, lambda: bool(dock.fileMatches))
    assert [match["name"] for match in dock.fileMatches] == ["fast.py"]


def test_show_hidden_restarts_an_active_file_search(
        application, dock, project, monkeypatch):
    calls = []

    def fake_search(root, needle, *, limit, show_hidden):
        calls.append(show_hidden)
        name = "hidden.py" if show_hidden else "visible.py"
        return [{"name": name, "path": str(project / name)}]

    monkeypatch.setattr("wynxo.dock.files._search_tree_impl", fake_search)
    dock.set_project(str(project))
    dock.setFileFilter("file")
    assert settle(application, lambda: [
        match["name"] for match in dock.fileMatches] == ["visible.py"])

    dock.setShowHidden(True)
    assert dock.fileMatches == []
    assert settle(application, lambda: [
        match["name"] for match in dock.fileMatches] == ["hidden.py"])
    assert calls[-1] is True


def test_changing_project_clears_the_previous_one(dock, project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    dock.set_project(str(project))
    dock.openFile(str(project / "README.md"))
    assert dock.set_project(str(other)) is True
    assert dock.filePath == ""
    assert dock.fileModel.rowCount() == 0


# ------------------------------------------------------------- the context
def test_the_context_panel_mirrors_the_real_state(dock, project):
    dock.set_project(str(project))
    dock.openFile(str(project / "README.md"))
    titles = {group["title"] for group in dock.contextItems}
    assert "Workspace" in titles and "Open file" in titles

    dock.removeContext("file")
    assert "Open file" not in {group["title"] for group in dock.contextItems}


# ------------------------------------------------------------- the activity
def test_the_activity_timeline_records_a_run(dock):
    dock.begin_turn("A task")
    dock.record({"kind": "step", "name": "run_command", "label": "Run", "state": "running"})
    dock.record_update(state="done", ms=120, output="ok")
    dock.settle_turn("done")
    assert dock.activityRunning is False
    assert "1 step" in dock.activitySummary
    dock.clearActivity()
    assert dock.activityRows == []


# -------------------------------------------------------------- the browser
def test_navigation_refuses_what_it_cannot_open(dock):
    assert dock.navigate("example.com") is True
    assert dock.browserRequest == "https://example.com"
    assert dock.navigate("javascript:alert(1)") is False
    assert dock.browserError


def test_the_blank_page_is_not_reported_as_somewhere_you_have_been(dock):
    dock.browserStateChanged("about:blank", "")
    assert dock.browserUrl == ""
    assert dock.browserTrust == ""
    dock.browserStateChanged("https://example.com/x", "Example")
    assert dock.browserTrust == "secure"
    assert dock.browserTitle == "Example"


# -------------------------------------------------------------- the changes
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_changes_are_read_from_git_and_a_diff_opens(application, store, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for arguments in (["init", "-q", "-b", "main"],
                      ["config", "user.email", "t@example.invalid"],
                      ["config", "user.name", "T"]):
        subprocess.run(["git", *arguments], cwd=root, check=True,
                       capture_output=True, stdin=subprocess.DEVNULL)
    (root / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "first"], cwd=root, check=True,
                   capture_output=True)
    (root / "a.txt").write_text("two\n")

    dock = DockController(store=store)
    try:
        dock.set_project(str(root))
        assert settle(application, lambda: not dock.changesBusy and bool(dock.changes), 15.0)
        assert dock.isRepository is True
        assert dock.branch == "main"
        assert [entry["path"] for entry in dock.changes] == ["a.txt"]

        dock.openDiff("a.txt")
        assert settle(application, lambda: bool(dock.diffRows), 15.0)
        assert any(row["type"] == "add" for row in dock.diffRows)
        dock.closeDiff()
        assert dock.diffRows == []
    finally:
        dock.shutdown()


def test_running_a_command_in_the_terminal_opens_that_panel(dock, project):
    """A menu the user opened is a decision, not a hint: `suggest` would be
    refused once they had chosen a tab, and a click must not be."""
    dock.set_project(str(project))
    dock.setTab("changes")                     # the user has now chosen
    dock.runInTerminal("echo hello")
    try:
        assert dock.tab == "terminal"
        assert dock.visible is True
    finally:
        dock.restartTerminal()
