"""The preview controller keeps --ui-preview and --snapshot honest.

It exercises the real controller with fixed data, so a change that breaks the
screenshot pipeline fails here rather than in CI's rendering step.
"""
from PySide6.QtCore import QCoreApplication

from wynxo.demo import CATALOG, SCENES, DemoController

APP = QCoreApplication.instance() or QCoreApplication([])


def test_preview_never_touches_the_user_history(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    bridge = DemoController("conversation")
    try:
        assert str(bridge.store.path).startswith("/tmp") or "wynxo-preview-" in str(bridge.store.path)
        assert not (home / "wynxo").exists()
    finally:
        bridge.shutdown()


def test_conversation_scene_has_everything_a_screenshot_needs():
    bridge = DemoController("conversation")
    try:
        kinds = [item["kind"] for item in bridge.messages.items]
        assert "user" in kinds and "assistant" in kinds and "activity" in kinds
        answer = next(item for item in bridge.messages.items if item["kind"] == "assistant")
        assert any(block["kind"] == "code" for block in answer["blocks"])
        assert answer["thought"] and answer["thinkSeconds"] > 0
        assert bridge.runMetrics["hasData"] is True
        assert len(bridge.taskGroups) >= 3
        assert bridge.online is True
        assert bridge.modelSupportsVision is True
    finally:
        bridge.shutdown()


def test_desktop_scene_shows_a_pending_approval_and_a_timeline():
    bridge = DemoController("desktop")
    try:
        assert bridge.permissionPending is True
        assert bridge.permissionRisk == "sensitive"
        assert bridge.busy is True
        steps = [step for item in bridge.messages.items if item["kind"] == "activity"
                 for step in item["steps"]]
        assert len(steps) == len(bridge.activity) > 4
        assert any(step["state"] == "waiting" for step in steps)
        assert any(step["state"] == "done" for step in steps)
    finally:
        bridge.shutdown()


def test_empty_and_welcome_scenes():
    empty = DemoController("empty")
    try:
        assert empty.hasMessages is False
        assert empty.onboarded is True
        assert empty.taskTitle == "New task"
    finally:
        empty.shutdown()

    welcome = DemoController("welcome")
    try:
        assert welcome.onboarded is False
    finally:
        welcome.shutdown()


def test_preview_refresh_stays_offline():
    bridge = DemoController("empty")
    try:
        bridge.refreshModels()
        assert bridge.online is True
        names = [entry["name"] for entry in bridge.modelCatalog]
        assert set(names) == {entry["name"] for entry in CATALOG}
        # Selected first, then favourites, then everything else.
        assert names[0] == bridge.model
        favourites = {entry["name"] for entry in CATALOG if entry["favorite"]}
        assert set(names[:len(favourites)]) == favourites
    finally:
        bridge.shutdown()


def test_every_declared_scene_can_be_built():
    for name, scene, overlay in SCENES:
        bridge = DemoController(scene)
        try:
            assert bridge.appVersion
            assert bridge.taskMode in {"chat", "work"}, (name, scene, bridge.taskMode)
        finally:
            bridge.shutdown()


def test_preview_history_uses_only_real_task_modes():
    bridge = DemoController("conversation")
    try:
        modes = {item["mode"] for group in bridge.taskGroups for item in group["items"]}
        assert modes <= {"chat", "work"}
        assert modes == {"chat", "work"}
    finally:
        bridge.shutdown()


def test_every_scene_names_a_project_so_the_hierarchy_is_visible():
    """The redesign puts the project above the task list; a screenshot without
    one shows an empty state that never happens after first run."""
    for scene in ("conversation", "desktop", "context", "run"):
        bridge = DemoController(scene)
        try:
            assert bridge.projectName == "wynxq-gui"
            assert bridge.projectParentLabel
            assert len(bridge.recentProjects) >= 2
        finally:
            bridge.shutdown()


def test_the_dock_scenes_point_at_a_real_folder():
    """Files, Changes and Terminal read the filesystem. A screenshot of them
    is only worth taking if the folder behind it actually exists — otherwise
    every panel shows its empty state."""
    from pathlib import Path
    bridge = DemoController("dock-files")
    try:
        assert Path(bridge.projectPath).is_dir()
        assert bridge.workspaceDock.visible
        assert bridge.workspaceDock.tab == "files"
        assert bridge.workspaceDock.fileModel.rowCount() > 0
    finally:
        bridge.shutdown()


def test_the_finished_run_scene_settles_every_step():
    """The activity design ends with a summary line, which only appears when
    nothing is still running or waiting."""
    bridge = DemoController("run")
    try:
        steps = [step for item in bridge.messages.items if item["kind"] == "activity"
                 for step in item["steps"]]
        assert len(steps) > 4
        assert {step["state"] for step in steps} == {"done"}
        assert bridge.messages.items[-1]["kind"] == "assistant"
        # The answer is rendered once: segmented blocks plus the open tail.
        answer = bridge.messages.items[-1]
        assert answer["body"].count("KolourPaint is open") == 1
    finally:
        bridge.shutdown()


def test_the_browser_scene_serves_a_real_page():
    """The Browser screenshot is worth taking only if it shows a rendered
    page. The scene serves one from loopback so the snapshot job needs no
    network and the image is of Qt WebEngine, not of an empty state."""
    import urllib.request
    from wynxo.demo import serve_preview_page

    server, url = serve_preview_page()
    try:
        assert url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "Local browsing" in body
        assert "Qt WebEngine" in body
    finally:
        server.shutdown()
        server.server_close()


def test_the_browser_scene_navigates_to_it():
    bridge = DemoController("dock-browser")
    try:
        assert bridge.workspaceDock.tab == "browser"
        if bridge.workspaceDock.browserAvailable:
            assert bridge.workspaceDock.browserRequest.startswith("http://127.0.0.1:")
    finally:
        bridge.shutdown()
