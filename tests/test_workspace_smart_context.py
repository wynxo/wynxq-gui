"""Integration coverage for smart inference context in WorkspaceController's engine."""
from threading import Event

from wynxq import context_budget, project_context, project_instructions
from wynxq.controller import AgentEngine
from wynxq.workspace import PlanningAgentEngine


class DummyDesktop:
    def execute(self, name, arguments, cancel=None):
        return {"ok": True}

    def status(self):
        return {"connected": False}


def fake_base_run(captured):
    def run(self, messages, model, desktop_enabled, cancel, emit, **kwargs):
        captured[:] = messages
        return list(messages) + [{"role": "assistant", "content": "fresh answer"}]
    return run


def long_history():
    history = []
    for index in range(18):
        history.extend([
            {"role": "user", "content": f"old question {index} " + "q" * 900},
            {"role": "assistant", "content": f"old answer {index} " + "a" * 900},
        ])
    history.append({"role": "user", "content": "latest request"})
    return history


def test_chat_compacts_for_inference_but_returns_complete_archive(monkeypatch):
    captured = []
    events = []
    monkeypatch.setattr(AgentEngine, "run", fake_base_run(captured))
    full = long_history()
    engine = PlanningAgentEngine(client=object(), desktop=DummyDesktop())

    result = engine.run(full, "model", False, Event(), events.append,
                        num_ctx=4096, tools_allowed=False)

    assert len(captured) < len(full)
    assert captured[-1]["content"] == "latest request"
    assert any(event.get("type") == "context_compacted" for event in events)
    assert result[:-1] == full
    assert result[-1]["content"] == "fresh answer"
    assert not any(str(m.get("content", "")).startswith(context_budget.COMPACTION_PREFIX)
                   for m in result)


def test_work_gets_project_metadata_and_rules_but_neither_persists(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(AgentEngine, "run", fake_base_run(captured))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.cpp").write_text("int main() { return 0; }\n")
    (root / "CMakeLists.txt").write_text("project(demo)\n")
    (root / "AGENTS.md").write_text("Run ctest after C++ changes.\n")
    original = [{"role": "user", "content": "fix the build"}]
    engine = PlanningAgentEngine(client=object(), desktop=DummyDesktop())

    result = engine.run(original, "model", False, Event(), lambda event: None,
                        num_ctx=8192, tools_allowed=True, project=str(root))

    system_text = "\n".join(str(m.get("content", "")) for m in captured if m.get("role") == "system")
    assert project_context.PROJECT_CONTEXT_PREFIX in system_text
    assert project_instructions.INSTRUCTIONS_PREFIX in system_text
    assert "Run ctest" in system_text
    assert result == original + [{"role": "assistant", "content": "fresh answer"}]
    assert not any(str(m.get("content", "")).startswith(project_context.PROJECT_CONTEXT_PREFIX) for m in result)
    assert not any(str(m.get("content", "")).startswith(project_instructions.INSTRUCTIONS_PREFIX) for m in result)


def test_chat_mode_does_not_read_project_rules(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(AgentEngine, "run", fake_base_run(captured))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("This should not enter Chat mode.\n")
    engine = PlanningAgentEngine(client=object(), desktop=DummyDesktop())

    engine.run([{"role": "user", "content": "hello"}], "model", False, Event(), lambda event: None,
               num_ctx=8192, tools_allowed=False, project=str(root))

    assert not any("This should not enter Chat mode" in str(m.get("content", "")) for m in captured)


def test_context_panel_and_header_expose_smart_context_state():
    from pathlib import Path
    root = Path(__file__).parents[1] / "wynxq" / "ui" / "Wynxq"
    context_ui = (root / "ContextPanel.qml").read_text()
    header_ui = (root / "TaskHeader.qml").read_text()

    assert "contextOmittedTurns" in context_ui
    assert "contextCompactionLabel" in context_ui
    assert "full history" in context_ui or "contextCompactionLabel" in context_ui
    assert "projectInstructionsSummary" in header_ui
    assert "Project rules" in header_ui
