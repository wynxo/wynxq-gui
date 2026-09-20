"""Automatic memory should learn durable facts without trusting every sentence."""
from PySide6.QtCore import QCoreApplication

from wynxq.memory import Memory
from wynxq.memory_learning import GLOBAL, PROJECT, learnable_memories
from wynxq.storage import Store
from wynxq.workspace import WorkspaceController

APP = QCoreApplication.instance() or QCoreApplication([])


def one(text, project=""):
    items = learnable_memories(text, project)
    assert len(items) == 1, items
    return items[0]


def test_learns_a_preferred_name_and_preference():
    assert one("Call me wynxq") == {
        "note": "User prefers to be called wynxq.", "scope": GLOBAL,
    }
    assert one("I prefer concise answers") == {
        "note": "User prefers concise answers.", "scope": GLOBAL,
    }


def test_learns_common_russian_and_german_phrasings():
    assert one("называй меня wynxq")["note"] == "User prefers to be called wynxq."
    assert one("я предпочитаю короткие ответы")["note"] == "User prefers короткие ответы."
    assert one("nenn mich wynxq")["note"] == "User prefers to be called wynxq."


def test_repo_convention_is_project_scoped():
    item = one("This repo uses pytest", "/srv/wynxq")
    assert item["scope"] == PROJECT
    assert "pytest" in item["note"]


def test_explicit_remember_works_without_model_tool_calling():
    assert one("Remember that I use KDE Plasma")["note"] == "I use KDE Plasma"
    item = one("Remember that this project uses CMake", "/srv/app")
    assert item["scope"] == PROJECT


def test_transient_statements_do_not_become_long_term_memory():
    assert learnable_memories("For now I prefer verbose answers") == []
    assert learnable_memories("Today I use Firefox") == []
    assert learnable_memories("Do this just this once") == []


def test_secrets_and_opt_out_are_never_learned():
    assert learnable_memories("Remember that my password is swordfish") == []
    assert learnable_memories("My API key is sk-abcdefghijklmnopqrstuv") == []
    assert learnable_memories("Don't remember this: I prefer Vim") == []
    assert learnable_memories("не запоминай это: я использую Arch") == []


def test_random_task_requests_are_not_profiled():
    for text in (
        "Run pytest and fix the failures",
        "Can you explain pointers?",
        "Open the settings window",
        "Write a Python script that sorts these files",
        "I need help with this error right now",
    ):
        assert learnable_memories(text, "/srv/app") == [], text


class IdleDesktop:
    connected = False

    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "Off"}

    def disconnect(self):
        self.connected = False


def controller(tmp_path):
    return WorkspaceController(
        store=Store(tmp_path / "history.sqlite3"),
        desktop=IdleDesktop(),
        autoconnect=False,
        memory=Memory(tmp_path / "memory.md"),
    )


def ready(bridge, monkeypatch):
    bridge.newTaskMode("work")
    bridge._online = True
    bridge._model_capabilities = ["completion"]  # deliberately no tool calling
    monkeypatch.setattr(bridge, "_start_run", lambda history: None)


def test_workspace_learns_before_a_model_ever_calls_remember(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    ready(bridge, monkeypatch)

    bridge.send("Call me wynxq")

    assert "User prefers to be called wynxq." in bridge.memory.notes()
    assert "User prefers to be called wynxq." in bridge.memory.prompt()
    bridge.shutdown()


def test_preferred_name_updates_instead_of_becoming_two_conflicting_memories(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    ready(bridge, monkeypatch)

    bridge.send("Call me wynxq")
    bridge._busy = False
    bridge.send("My preferred name is nova")

    names = [note for note in bridge.memory.notes("global")
             if note.startswith(("User prefers to be called ", "User's preferred name is "))]
    assert names == ["User's preferred name is nova."]
    bridge.shutdown()


def test_workspace_auto_learning_respects_memory_off(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    ready(bridge, monkeypatch)
    bridge.setMemoryEnabled(False)

    bridge.send("I prefer concise answers")

    assert bridge.memory.notes() == []
    bridge.shutdown()


def test_workspace_project_memory_does_not_leak_into_another_repo(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    ready(bridge, monkeypatch)
    project = tmp_path / "app"
    project.mkdir()
    assert bridge._set_project(str(project)) is True

    bridge.send("This repo uses pytest")

    assert "pytest" in bridge.memory.prompt(str(project))
    assert "pytest" not in bridge.memory.prompt(str(tmp_path / "other"))
    bridge.shutdown()


def test_chat_automatically_learns_high_confidence_memories(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._model_capabilities = ["completion", "tools"]
    monkeypatch.setattr(bridge, "_start_run", lambda history, **kwargs: None)
    bridge.send("My preferred name is Morgan")
    assert bridge.taskMode == "chat"
    assert bridge.memory.notes() == ["User's preferred name is Morgan."]
    bridge.shutdown()


def test_chat_can_forget_a_normalized_saved_memory_without_tools(tmp_path, monkeypatch):
    bridge = controller(tmp_path)
    bridge._online = True
    bridge._model_capabilities = ["completion"]
    monkeypatch.setattr(bridge, "_start_run", lambda history, **kwargs: None)

    bridge.send("I use Debian")
    assert bridge.memory.notes() == ["User uses Debian."]

    bridge.send("Forget that I use Debian")
    assert bridge.memory.notes() == []
    bridge.shutdown()
