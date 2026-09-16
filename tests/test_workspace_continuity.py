"""Workspace continuity should survive restarts without replaying agent actions."""
from PySide6.QtCore import QCoreApplication

from wynxo.storage import Store
from wynxo.workspace import WorkspaceController

APP = QCoreApplication.instance() or QCoreApplication([])


class IdleDesktop:
    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "Off"}

    def disconnect(self):
        return {"connected": False}


def make_controller(path):
    return WorkspaceController(store=Store(path), desktop=IdleDesktop(), autoconnect=False)


def close_controller(controller):
    controller.shutdown()
    controller.store.close()


def test_blank_task_draft_survives_restart(tmp_path):
    database = tmp_path / "history.sqlite3"
    first = make_controller(database)
    first.setDraft("half-finished question")
    first._persist_current_draft()
    close_controller(first)

    second = make_controller(database)
    assert second.taskId == ""
    assert second.draftText == "half-finished question"
    assert second.busy is False
    assert second._run_job is None
    close_controller(second)


def test_last_open_task_mode_plan_and_draft_restore_without_resuming(tmp_path):
    database = tmp_path / "history.sqlite3"
    first = make_controller(database)
    task = first.store.create_conversation("Fix renderer", "test-model")
    first.store.set_messages(task["id"], [{"role": "user", "content": "Fix the renderer"}], "test-model")
    first.store.set_setting(first._mode_key(task["id"]), "codex")
    first.store.set_setting(first._plan_key(task["id"]), [
        {"id": "inspect", "title": "Inspect renderer", "status": "completed"},
        {"id": "patch", "title": "Patch renderer", "status": "in_progress"},
    ])
    first.openTask(task["id"])
    first.setDraft("also check the fallback path")
    first._persist_current_draft()
    close_controller(first)

    second = make_controller(database)
    assert second.taskId == task["id"]
    assert second.taskMode == "work"
    assert second.draftText == "also check the fallback path"
    assert [step["status"] for step in second.planSteps] == ["completed", "pending"]
    assert second.store.get_setting(second._plan_key(task["id"]))[1]["status"] == "pending"
    assert second.busy is False
    assert second._run_job is None
    assert second.permissionPending is False
    close_controller(second)


def test_normal_plan_reads_preserve_live_in_progress_state(tmp_path):
    database = tmp_path / "history.sqlite3"
    bridge = make_controller(database)
    task = bridge.store.create_conversation("Live plan", "test-model")
    plan = [
        {"id": "inspect", "title": "Inspect", "status": "completed"},
        {"id": "edit", "title": "Edit", "status": "in_progress"},
    ]
    bridge.store.set_setting(bridge._plan_key(task["id"]), plan)

    assert bridge._saved_plan(task["id"]) == plan
    assert bridge.store.get_setting(bridge._plan_key(task["id"])) == plan
    close_controller(bridge)


def test_shutdown_is_idempotent_even_after_store_is_closed(tmp_path):
    bridge = make_controller(tmp_path / "history.sqlite3")
    bridge.setDraft("keep me")

    bridge.shutdown()
    bridge.store.close()

    # Snapshot/demo teardown and defensive host cleanup may call shutdown again.
    # The second call must not try to write to the closed SQLite connection.
    bridge.shutdown()


def test_sending_clears_persisted_draft_and_tracks_new_task(tmp_path, monkeypatch):
    database = tmp_path / "history.sqlite3"
    bridge = make_controller(database)
    bridge._online = True
    bridge._model_capabilities = ["completion"]
    monkeypatch.setattr(bridge, "_start_run", lambda history: None)
    bridge.setDraft("Explain pointers")
    bridge._persist_current_draft()

    bridge.send("Explain pointers")

    assert bridge.taskId
    assert bridge.store.get_setting(bridge._draft_key(""), "missing") == ""
    assert bridge.store.get_setting(bridge._draft_key(bridge.taskId), "missing") == ""
    assert bridge.store.get_setting(bridge.LAST_TASK_KEY) == bridge.taskId
    close_controller(bridge)


def test_pending_attachments_are_deliberately_not_restored(tmp_path):
    database = tmp_path / "history.sqlite3"
    first = make_controller(database)
    first._attachments = [{"id": "one-turn", "kind": "clipboard", "title": "Clipboard", "text": "private context"}]
    first.setDraft("use my attachment")
    first._persist_current_draft()
    close_controller(first)

    second = make_controller(database)
    assert second.draftText == "use my attachment"
    assert second.attachments == []
    close_controller(second)


def test_missing_last_task_falls_back_to_new_task_draft(tmp_path):
    database = tmp_path / "history.sqlite3"
    store = Store(database)
    store.set_setting(WorkspaceController.LAST_TASK_KEY, "does-not-exist")
    store.set_setting(WorkspaceController._draft_key(""), "fresh draft")
    store.close()

    bridge = make_controller(database)
    assert bridge.taskId == ""
    assert bridge.draftText == "fresh draft"
    assert bridge.store.get_setting(bridge.LAST_TASK_KEY) == ""
    close_controller(bridge)
