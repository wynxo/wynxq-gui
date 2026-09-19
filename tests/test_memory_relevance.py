"""Long memory should spend context on the facts most useful to this turn."""
import threading

import wynxq.memory as memory_module
from wynxq.engine import AgentEngine
from wynxq.memory import PROJECT, Memory


def test_small_memory_keeps_everything_even_without_a_query(tmp_path):
    memory = Memory(tmp_path / "memory.md")
    memory.remember("User prefers compact replies.")
    memory.remember("User uses KDE Plasma.")

    prompt = memory.prompt(query="unrelated question")

    assert "User prefers compact replies." in prompt
    assert "User uses KDE Plasma." in prompt


def test_identity_survives_a_tight_prompt_budget(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.md")
    memory.remember("User prefers to be called wynxq.")
    for index in range(20):
        memory.remember(f"Unrelated historical note number {index} with extra filler words.")
    monkeypatch.setattr(memory_module, "PROMPT_BUDGET", 150)

    prompt = memory.prompt(query="explain networking")

    assert "User prefers to be called wynxq." in prompt


def test_relevant_global_note_beats_unrelated_notes_when_budget_is_tight(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.md")
    memory.remember("User builds CMake projects with Ninja.")
    for index in range(25):
        memory.remember(f"User likes unrelated topic {index} and some filler text.")
    monkeypatch.setattr(memory_module, "PROMPT_BUDGET", 190)

    prompt = memory.prompt(query="Why is my CMake Ninja build failing?")

    assert "User builds CMake projects with Ninja." in prompt


def test_current_project_memory_outranks_unrelated_global_history(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.md")
    project = tmp_path / "app"
    project.mkdir()
    for index in range(20):
        memory.remember(f"Global unrelated note {index} with enough filler to consume context.")
    memory.remember("This project uses pytest and Python 3.13.", PROJECT, str(project))
    monkeypatch.setattr(memory_module, "PROMPT_BUDGET", 180)

    prompt = memory.prompt(str(project), query="run the tests")

    assert "This project uses pytest and Python 3.13." in prompt


def test_other_projects_never_enter_relevance_ranking(tmp_path, monkeypatch):
    memory = Memory(tmp_path / "memory.md")
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    project_a.mkdir(); project_b.mkdir()
    memory.remember("This project uses secret-project-a-tooling.", PROJECT, str(project_a))
    memory.remember("This project uses project-b-tooling.", PROJECT, str(project_b))
    monkeypatch.setattr(memory_module, "PROMPT_BUDGET", 500)

    prompt = memory.prompt(str(project_b), query="secret-project-a-tooling")

    assert "project-b-tooling" in prompt
    assert "secret-project-a-tooling" not in prompt


def test_engine_uses_the_latest_user_request_as_the_memory_relevance_query():
    class Client:
        def capabilities(self, model):
            return ["completion"]

        def stream_chat(self, payload, cancel):
            yield {"message": {"content": "done"}, "done": True}

    class SpyMemory:
        def __init__(self):
            self.seen = None

        def prompt(self, project, query=""):
            self.seen = (project, query)
            return ""

    memory = SpyMemory()
    AgentEngine(Client(), None, memory).run(
        [
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "Why is my CMake Ninja build failing?"},
        ],
        "local:test", False, threading.Event(), lambda event: None,
        tools_allowed=False,
    )

    assert memory.seen == ("", "Why is my CMake Ninja build failing?")
