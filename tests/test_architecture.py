"""Architecture boundaries that public callers rely on.

The coordinator modules intentionally re-export a few names for backwards
compatibility. These checks make the split explicit: implementations live in
focused modules while existing imports remain stable.
"""

from wynxq import (agent_tools, conversation, controller, controller_support, desktop,
                   desktop_backends, desktop_common, dock, dock_models, engine)


def test_controller_reexports_conversation_model_and_helpers():
    assert controller.Messages is conversation.Messages
    assert controller.derive_title is conversation.derive_title
    assert controller.group_for is conversation.group_for
    assert controller.GROUP_ORDER is conversation.GROUP_ORDER
    assert controller.STARTERS is conversation.STARTERS


def test_controller_reexports_runtime_helpers():
    assert controller.Job is controller_support.Job
    assert controller._RunDesktop is controller_support._RunDesktop
    assert controller._StoredTokens is controller_support._StoredTokens


def test_dock_reexports_models_without_owning_their_implementation():
    assert dock.FileTree is dock_models.FileTree
    assert dock.TerminalLines is dock_models.TerminalLines
    assert dock._Worker is dock_models._Worker
    assert dock._ORPHANED is dock_models._ORPHANED


def test_engine_reexports_agent_tool_contract():
    assert engine.TOOLS is agent_tools.TOOLS
    assert engine.MEMORY_TOOLS is agent_tools.MEMORY_TOOLS
    assert engine.BROWSER_TOOLS is agent_tools.BROWSER_TOOLS
    assert engine.normalise_mode is agent_tools.normalise_mode
    assert engine.command_risk is agent_tools.command_risk
    assert engine.action_risk is agent_tools.action_risk
    assert engine.needs_confirmation is agent_tools.needs_confirmation
    assert engine.validate_tool_call is agent_tools.validate_tool_call


def test_engine_reexports_stream_helpers_without_owning_implementation():
    from wynxq import engine_support

    assert engine._ThinkingTextRouter is engine_support._ThinkingTextRouter
    assert engine._normalise_assistant_channels is engine_support._normalise_assistant_channels


def test_desktop_facade_reexports_shared_types_and_backends():
    assert desktop.SessionTokens is desktop_common.SessionTokens
    assert desktop.DesktopError is desktop_common.DesktopError
    assert desktop.DesktopCancelled is desktop_common.DesktopCancelled
    assert desktop._X11Backend is desktop_backends._X11Backend
    assert desktop._PortalBackend is desktop_backends._PortalBackend
    assert desktop.X11GlobalStop is desktop_backends.X11GlobalStop
    assert desktop.GlobalStop is desktop_backends.GlobalStop


def test_desktop_backend_facade_reexports_focused_platform_modules():
    from wynxq import desktop_portal, desktop_stop, desktop_x11

    assert desktop_backends._X11Backend is desktop_x11._X11Backend
    assert desktop_backends._PortalBackend is desktop_portal._PortalBackend
    assert desktop_backends.X11GlobalStop is desktop_stop.X11GlobalStop
    assert desktop_backends.GlobalStop is desktop_stop.GlobalStop


def test_workspace_facade_binds_focused_behavior_modules():
    from wynxq import (
        workspace, workspace_run_ops, workspace_session_ops,
        workspace_task_ops, workspace_usage_ops,
    )

    assert workspace.WorkspaceController._restore_workspace_session is workspace_session_ops._restore_workspace_session
    assert workspace.WorkspaceController._set_project is workspace_usage_ops._set_project
    assert workspace.WorkspaceController.send is workspace_task_ops.send
    assert workspace.WorkspaceController._start_run is workspace_run_ops._start_run
    assert workspace.WorkspaceController._run_done is workspace_run_ops._run_done

def test_controller_facade_binds_focused_behavior_modules():
    from wynxq import (
        controller_context_ops, controller_event_ops, controller_generation_ops,
        controller_misc_ops, controller_permission_ops, controller_server_ops,
        controller_task_ops,
    )

    assert controller.Controller.refreshModels is controller_server_ops.refreshModels
    assert controller.Controller.newTask is controller_task_ops.newTask
    assert controller.Controller.attachScreenshot is controller_context_ops.attachScreenshot
    assert controller.Controller.send is controller_generation_ops.send
    assert controller.Controller.resolvePermission is controller_permission_ops.resolvePermission
    assert controller.Controller._run_done is controller_event_ops._run_done
    assert controller.Controller.exportTask is controller_misc_ops.exportTask


def test_dock_facade_binds_focused_behavior_modules():
    from wynxq import (
        dock_browser_ops, dock_change_ops, dock_context_ops, dock_file_ops,
        dock_layout_ops, dock_terminal_ops,
    )

    assert dock.DockController.set_project is dock_layout_ops.set_project
    assert dock.DockController.openFile is dock_file_ops.openFile
    assert dock.DockController.startTerminal is dock_terminal_ops.startTerminal
    assert dock.DockController.refreshChanges is dock_change_ops.refreshChanges
    assert dock.DockController.begin_turn is dock_context_ops.begin_turn
    assert dock.DockController.navigate is dock_browser_ops.navigate


def test_engine_reexports_ollama_transport():
    from wynxq import ollama

    assert engine.OllamaClient is ollama.OllamaClient
    assert engine.OllamaError is ollama.OllamaError
    assert engine.Cancelled is ollama.Cancelled
    assert engine.validate_endpoint is ollama.validate_endpoint


def test_workspace_injects_endpoint_policy_without_engine_monkey_patch():
    from wynxq import endpoint_policy, workspace

    assert workspace.OllamaClient is endpoint_policy.WorkspaceOllamaClient
    assert workspace.WorkspaceController.OLLAMA_CLIENT is None
    assert workspace.WorkspaceController.PLANNING_ENGINE is None
    assert endpoint_policy.WorkspaceOllamaClient.endpoint_validator is endpoint_policy.validate_workspace_endpoint


def test_coordinator_modules_have_hard_size_budgets():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    budgets = {
        "wynxq/controller.py": 900,
        "wynxq/workspace.py": 350,
        "wynxq/engine.py": 400,
        "wynxq/dock.py": 550,
        "wynxq/desktop_backends.py": 40,
    }
    for relative, maximum in budgets.items():
        count = len((root / relative).read_text(encoding="utf-8").splitlines())
        assert count <= maximum, f"{relative} grew to {count} lines (budget {maximum})"


def test_behavior_slices_stay_focused():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    slices = [
        *root.glob("wynxq/controller_*_ops.py"),
        *root.glob("wynxq/dock_*_ops.py"),
        *root.glob("wynxq/workspace_*_ops.py"),
    ]
    assert slices
    for path in slices:
        text = path.read_text(encoding="utf-8")
        count = len(text.splitlines())
        assert count <= 550, f"{path.name} grew to {count} lines; split the concern again"
        if path.name.startswith("controller_"):
            assert "from .controller import" not in text
        if path.name.startswith("dock_"):
            assert "from .dock import" not in text
        if path.name.startswith("workspace_"):
            assert "from .workspace import" not in text


def test_policy_and_transport_layers_are_qt_free():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pure_layers = [
        "wynxq/ollama.py",
        "wynxq/endpoint_policy.py",
        "wynxq/workspace_checkpoint.py",
        "wynxq/planning.py",
        "wynxq/agent_prompt.py",
        "wynxq/engine_support.py",
        "wynxq/tool_execution.py",
    ]
    for relative in pure_layers:
        text = (root / relative).read_text(encoding="utf-8")
        assert "PySide6" not in text, f"{relative} must stay independent of Qt"

def test_engine_layers_have_hard_size_budgets():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    budgets = {
        "wynxq/agent_prompt.py": 180,
        "wynxq/engine_support.py": 200,
        "wynxq/tool_execution.py": 220,
    }
    for relative, maximum in budgets.items():
        count = len((root / relative).read_text(encoding="utf-8").splitlines())
        assert count <= maximum, f"{relative} grew to {count} lines (budget {maximum})"


def test_settings_shell_is_composed_from_focused_pages():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "wynxq" / "ui" / "Wynxq"
    shell = root / "SettingsSheet.qml"
    assert len(shell.read_text(encoding="utf-8").splitlines()) <= 350

    expected = {
        "SettingsGeneralPage.qml",
        "SettingsModelPage.qml",
        "SettingsAgentPage.qml",
        "SettingsWorkspacePage.qml",
        "SettingsUsagePage.qml",
        "SettingsAppearancePage.qml",
        "SettingsAdvancedPage.qml",
    }
    pages = {path.name for path in root.glob("Settings*Page.qml")}
    assert pages == expected
    for name in expected:
        count = len((root / name).read_text(encoding="utf-8").splitlines())
        assert count <= 260, f"{name} grew to {count} lines; split the page further"

def test_platform_backend_modules_have_size_budgets():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    budgets = {
        "wynxq/desktop_x11.py": 260,
        "wynxq/desktop_stop.py": 220,
        "wynxq/desktop_portal.py": 550,
    }
    for relative, maximum in budgets.items():
        count = len((root / relative).read_text(encoding="utf-8").splitlines())
        assert count <= maximum, f"{relative} grew to {count} lines (budget {maximum})"

