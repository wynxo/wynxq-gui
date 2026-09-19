"""A project switch must never orphan an unsaved editor buffer."""
from PySide6.QtCore import QCoreApplication

from wynxq.storage import Store
from wynxq.workspace import WorkspaceController

APP = QCoreApplication.instance() or QCoreApplication([])


class IdleDesktop:
    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "Off"}

    def connect(self):
        return self.status()

    def disconnect(self):
        return None

    def active_window(self):
        return {"title": "", "detail": ""}


def test_rejected_dirty_project_switch_is_not_persisted(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    source = first / "main.py"
    source.write_text("print('disk')\n")

    store = Store(tmp_path / "history.sqlite3")
    bridge = WorkspaceController(store=store, desktop=IdleDesktop(), autoconnect=False)
    try:
        assert bridge._set_project(str(first)) is True
        assert bridge.dock.openFile(str(source)) is True
        bridge.dock.setFileBuffer("print('unsaved')\n")
        assert bridge.dock.fileModified is True

        recent_before = list(bridge._recent_projects)
        assert bridge._set_project(str(second)) is False

        assert bridge._working_directory == str(first)
        assert bridge.dock.projectPath == str(first)
        assert store.get_setting("working_directory") == str(first)
        assert bridge._recent_projects == recent_before
        assert str(second) not in bridge._recent_projects
        assert bridge.dock._viewer_buffer == "print('unsaved')\n"

        bridge.dock.revertFileBuffer()
        assert bridge._set_project(str(second)) is True
        assert bridge._working_directory == str(second)
        assert bridge.dock.projectPath == str(second)
        assert store.get_setting("working_directory") == str(second)
        assert bridge._recent_projects[0] == str(second)
    finally:
        bridge.shutdown()
        store.close()
