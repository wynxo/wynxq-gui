"""Persistent memory: the file, the tools that write it, and what a run reads."""
import threading

import pytest
from PySide6.QtCore import QCoreApplication

from wynxq.controller import Controller
from wynxq.engine import AgentEngine
from wynxq.memory import GLOBAL_SECTION, MAX_NOTES_PER_SECTION, Memory, default_path
from wynxq.storage import Store

APP = QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def memory(tmp_path):
    return Memory(tmp_path / "memory.md")


# ------------------------------------------------------------------- the file
def test_memory_starts_empty_without_a_file_on_disk(memory):
    assert memory.exists() is False
    assert memory.read() == ""
    assert memory.notes() == []
    assert memory.prompt() == ""


def test_a_note_lands_in_markdown_a_person_can_read(memory):
    memory.remember("Deploys with Nix, never Docker")
    text = memory.read()
    assert "# Wynxq memory" in text
    assert f"## {GLOBAL_SECTION}" in text
    assert "- Deploys with Nix, never Docker" in text


def test_project_notes_are_kept_apart_from_global_ones(memory):
    memory.remember("Prefers terse answers")
    memory.remember("The test command is just pytest", scope="project", project="/srv/app")
    memory.remember("This one uses cargo", scope="project", project="/srv/other")

    # A task in one folder reads its own notes and the global ones — never
    # another project's, which is how a model ends up confidently wrong.
    prompt = memory.prompt("/srv/app")
    assert "Prefers terse answers" in prompt
    assert "just pytest" in prompt
    assert "cargo" not in prompt
    assert "Prefers terse answers" in memory.prompt("")
    assert "just pytest" not in memory.prompt("")


def test_the_same_note_twice_is_stored_once(memory):
    first = memory.remember("Calls the cat Mango")
    second = memory.remember("  calls the CAT   Mango  ")
    assert first["stored"] is True
    assert second["stored"] is False
    assert memory.notes() == ["Calls the cat Mango"]


def test_a_note_is_reduced_to_one_bounded_line(memory):
    memory.remember("- # \n  keeps\tits words\n  across lines  ")
    assert memory.notes() == ["keeps its words across lines"]
    memory.remember("x" * 900)
    assert len(memory.notes()[-1]) == 500


def test_a_note_that_really_starts_with_a_marker_keeps_it(memory):
    memory.remember("#1 priority is the parser")
    assert memory.notes() == ["#1 priority is the parser"]


def test_an_empty_note_is_refused_rather_than_stored_blank(memory):
    with pytest.raises(ValueError):
        memory.remember("   ")
    with pytest.raises(ValueError):
        memory.forget(" ")


def test_forget_removes_matching_notes_and_leaves_the_rest(memory):
    memory.remember("Uses fish, not bash")
    memory.remember("Lives in Lisbon")
    result = memory.forget("fish")
    assert result["forgotten"] == 1
    assert memory.notes() == ["Lives in Lisbon"]
    assert memory.forget("nothing matches this")["forgotten"] == 0


def test_hand_written_prose_survives_a_note_the_model_adds(memory):
    memory.write("# My memory\n\nI wrote this myself.\n\n## About you\n\nA paragraph of mine.\n\n- An old note\n")
    memory.remember("A new note")
    text = memory.read()
    assert "I wrote this myself." in text
    assert "A paragraph of mine." in text
    assert "- An old note" in text
    assert "- A new note" in text


def test_a_section_is_capped_by_dropping_its_oldest_notes(memory):
    for index in range(MAX_NOTES_PER_SECTION + 5):
        memory.remember(f"note {index}")
    notes = memory.notes()
    assert len(notes) == MAX_NOTES_PER_SECTION
    assert "note 0" not in notes
    assert "note 4" not in notes
    assert notes[-1] == f"note {MAX_NOTES_PER_SECTION + 4}"


def test_the_file_is_private_to_the_user(memory):
    memory.remember("something")
    assert oct(memory.path.stat().st_mode)[-3:] == "600"


def test_an_oversized_write_is_refused_before_it_replaces_the_file(memory):
    memory.remember("worth keeping")
    with pytest.raises(ValueError):
        memory.write("x" * 200_000)
    assert memory.notes() == ["worth keeping"]


def test_clearing_leaves_a_readable_empty_file_not_a_missing_one(memory):
    memory.remember("gone soon")
    memory.clear()
    assert memory.notes() == []
    assert "# Wynxq memory" in memory.read()


def test_concurrent_writers_do_not_lose_each_other_s_notes(memory):
    def writer(start):
        for index in range(20):
            memory.remember(f"note {start}-{index}")

    threads = [threading.Thread(target=writer, args=(worker,)) for worker in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(memory.notes()) == 80


def test_the_file_lives_beside_the_history_database():
    assert default_path().name == "memory.md"
    assert default_path().parent.name == "wynxq"


# ---------------------------------------------------------------- in a run
class Desktop:
    def status(self):
        return {"connected": True, "available": True, "backend": "test", "detail": "on"}

    def execute(self, name, args, cancel):
        return {"ok": True, "action": name}


class Client:
    def __init__(self, script, capabilities=("completion", "tools")):
        self.script = list(script)
        self._capabilities = list(capabilities)
        self.requests = []

    def capabilities(self, model):
        return self._capabilities

    def stream_chat(self, payload, cancel):
        self.requests.append(payload)
        chunk = self.script.pop(0) if self.script else {"message": {"content": "done"}, "done": True}
        for part in (chunk if isinstance(chunk, list) else [chunk]):
            yield part


def call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


def run(client, memory, **kwargs):
    events = []
    history = AgentEngine(client, Desktop(), memory).run(
        [{"role": "user", "content": "go"}], "local:test", False, threading.Event(),
        events.append, **kwargs)
    return history, events


def test_what_was_remembered_is_read_into_the_next_task(memory):
    memory.remember("The user's name is Wren")
    client = Client([])
    run(client, memory)
    system = client.requests[0]["messages"][0]["content"]
    assert "The user's name is Wren" in system
    assert "Long-term memory" in system


def test_memory_is_offered_as_background_not_as_orders(memory):
    memory.remember("anything")
    client = Client([])
    run(client, memory)
    system = client.requests[0]["messages"][0]["content"]
    assert "not as new instructions" in system


def test_the_model_can_save_and_drop_a_memory_itself(memory):
    client = Client([
        {"message": {"tool_calls": [call("remember", note="Ships on Fridays")]}, "done": True},
        {"message": {"tool_calls": [call("forget", query="Fridays")]}, "done": True},
        {"message": {"content": "done"}, "done": True},
    ])
    _, events = run(client, memory)
    names = [event["name"] for event in events if event["type"] == "tool_end"]
    assert names == ["remember", "forget"]
    # It was really on disk between the two calls, not merely reported.
    assert any("Ships on Fridays" in str(message) for message in client.requests[1]["messages"])
    assert memory.notes() == []


def test_saving_a_memory_never_asks_for_permission(memory):
    asked = []
    client = Client([{"message": {"tool_calls": [call("remember", note="quiet")]}, "done": True},
                     {"message": {"content": "ok"}, "done": True}])
    run(client, memory, permission_mode="manual",
        confirm=lambda name, args, risk: asked.append(name) or True)
    assert asked == []
    assert memory.notes() == ["quiet"]


def test_with_memory_off_there_are_no_memory_tools_and_nothing_is_read(memory):
    memory.remember("The user's name is Wren")
    client = Client([])
    run(client, None)
    payload = client.requests[0]
    assert "Wren" not in payload["messages"][0]["content"]
    assert not any(tool["function"]["name"] in {"remember", "forget"}
                   for tool in payload.get("tools", []))


# ----------------------------------------------------------- in the app
class IdleDesktop:
    def status(self):
        return {"connected": False, "available": True, "backend": "test", "detail": "Off"}

    def disconnect(self):
        pass


def controller(tmp_path, cls=Controller):
    return cls(store=Store(tmp_path / "history.sqlite3"), desktop=IdleDesktop(),
               autoconnect=False, memory=Memory(tmp_path / "memory.md"))


def test_the_app_exposes_memory_as_a_file_you_can_read_and_edit(tmp_path):
    bridge = controller(tmp_path)
    assert bridge.memoryEnabled is True
    assert bridge.memoryPath.endswith("memory.md")
    assert bridge.memoryCount == 0

    bridge.rememberNote("Wakes up at six")
    assert bridge.memoryCount == 1
    assert "Wakes up at six" in bridge.memoryText

    bridge.saveMemory("## About you\n- Edited by hand\n")
    assert bridge.memoryCount == 1
    assert "Edited by hand" in bridge.memoryText
    assert "Wakes up at six" not in bridge.memoryText

    bridge.clearMemory()
    assert bridge.memoryCount == 0
    bridge.shutdown()


def test_turning_memory_off_keeps_the_file_but_stops_reading_it(tmp_path):
    bridge = controller(tmp_path)
    bridge.rememberNote("Still on disk")
    bridge.setMemoryEnabled(False)
    assert bridge.memoryEnabled is False
    assert bridge._memory_for_run() is None
    assert "Still on disk" in bridge.memoryText
    assert "off" in bridge.memorySummary.lower()

    # The choice survives a restart, which is the whole point of a setting.
    store = bridge.store
    bridge.shutdown()
    again = Controller(store=store, desktop=IdleDesktop(), autoconnect=False,
                       memory=Memory(tmp_path / "memory.md"))
    assert again.memoryEnabled is False
    again.shutdown()


def test_memory_is_the_same_file_in_chat_and_work(tmp_path):
    # Imported here so simply loading this module does not install the
    # workspace layer's engine extensions into every other test.
    from wynxq.workspace import WorkspaceController

    bridge = controller(tmp_path, cls=WorkspaceController)
    bridge.newTaskMode("work")
    bridge.rememberNote("Learned while coding")
    bridge.newTaskMode("chat")
    assert "Learned while coding" in bridge.memoryText
    assert "Learned while coding" in bridge.memory.prompt()
    bridge.shutdown()


def test_a_broken_memory_write_is_reported_rather_than_thrown(tmp_path):
    bridge = controller(tmp_path)
    toasts = []
    bridge.toast.connect(toasts.append)
    bridge.saveMemory("x" * 200_000)
    assert toasts and "limited to" in toasts[-1]
    bridge.shutdown()



def test_reference_chat_history_setting_is_separate_and_persistent(tmp_path):
    path = tmp_path / "history.sqlite3"
    bridge = Controller(
        store=Store(path), desktop=IdleDesktop(), autoconnect=False,
        memory=Memory(tmp_path / "memory.md"),
    )
    assert bridge.referenceChatHistory is True
    bridge.setReferenceChatHistory(False)
    assert bridge.referenceChatHistory is False
    bridge.shutdown()

    again = Controller(
        store=Store(path), desktop=IdleDesktop(), autoconnect=False,
        memory=Memory(tmp_path / "memory.md"),
    )
    assert again.referenceChatHistory is False
    again.setReferenceChatHistory(True)
    assert again.referenceChatHistory is True
    again.shutdown()
