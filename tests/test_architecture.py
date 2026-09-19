"""Architecture boundaries that public callers rely on.

The coordinator modules intentionally re-export a few names for backwards
compatibility. These checks make the split explicit: implementations live in
focused modules while existing imports remain stable.
"""

from wynxq import agent_tools, conversation, controller, controller_support, dock, dock_models, engine


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
