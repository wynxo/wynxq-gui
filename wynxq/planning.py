"""Planning-aware agent engine used by Work mode.

The generic agent engine remains reusable: plan-tool registration, context
compaction, project context, and project instructions live in this product layer.
"""
from __future__ import annotations

import copy

from . import context_budget
from . import engine as engine_module
from . import project_context
from . import project_instructions
from .engine import AgentEngine

PLAN_STATES = {"pending", "in_progress", "completed", "failed", "skipped"}
_PLAN_PROMPT_MARKER = "Use update_plan for genuine multi-step work"

def _install_plan_tool() -> None:
    """Add a UI-only planning tool to the existing local agent loop once.

    Keeping it in the workspace layer means the generic engine stays reusable.
    The engine still validates the schema and returns a normal tool result; the
    WorkspaceController consumes the corresponding events instead of showing
    them as desktop activity.
    """
    if "update_plan" not in engine_module._SCHEMAS:
        step = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 48},
                "title": {"type": "string", "minLength": 1, "maxLength": 180},
                "status": {"type": "string", "enum": sorted(PLAN_STATES)},
            },
            "required": ["id", "title", "status"],
            "additionalProperties": False,
        }
        tool = engine_module._tool(
            "update_plan",
            "Publish or update the concise execution plan shown in Wynxq GUI's Plan panel. "
            "Use only for work that needs multiple concrete actions. Reuse stable step IDs "
            "and update statuses as work progresses.",
            {
                "steps": {"type": "array", "minItems": 2, "maxItems": 8, "items": step},
                "explanation": {"type": "string", "maxLength": 240},
            },
            ["steps"],
        )
        engine_module.TOOLS.insert(0, tool)
        engine_module._SCHEMAS["update_plan"] = tool["function"]["parameters"]
        engine_module._NONVISUAL.add("update_plan")
        engine_module.LOW_RISK.add("update_plan")

    if _PLAN_PROMPT_MARKER not in engine_module._SYSTEM:
        engine_module._SYSTEM += (
            "\nUse update_plan for genuine multi-step work that needs two or more concrete actions. "
            "Publish a short plan before the first substantive action, keep the same step IDs, "
            "mark exactly one current step in_progress when possible, and update the plan as steps "
            "complete, fail, or are skipped. Do not create a plan for a simple answer or one-step action."
        )


class PlanningAgentEngine(AgentEngine):
    """AgentEngine with planning, bounded history and project orientation."""

    def run(self, *args, **kwargs):
        # The complete conversation is the archive. Build a temporary recent
        # view for this inference, then append only newly generated messages
        # back onto the untouched archive. This applies to Chat and Work.
        if args:
            full_history = copy.deepcopy(list(args[0]))
        else:
            full_history = copy.deepcopy(list(kwargs.get("messages", [])))
        fit = context_budget.fit_history(full_history, kwargs.get("num_ctx", 16384))
        inference_messages = fit.messages

        emit = args[4] if len(args) > 4 else kwargs.get("emit")
        if fit.compacted and callable(emit):
            emit({"type": "context_compacted", "omitted_turns": fit.omitted_turns,
                  "estimated_tokens": fit.estimated_tokens})

        desktop = self.desktop
        tools_allowed = bool(kwargs.get("tools_allowed", True))
        project = str(kwargs.get("project", "") or "")
        if tools_allowed and desktop is not None and project:
            inference_messages = project_context.inject(inference_messages, project)
            inference_messages = project_instructions.inject(inference_messages, project)

        if args:
            run_args = (inference_messages,) + args[1:]
            run_kwargs = kwargs
        else:
            run_args = args
            run_kwargs = {**kwargs, "messages": inference_messages}

        if desktop is None or not tools_allowed:
            result = super().run(*run_args, **run_kwargs)
        else:
            original_execute = desktop.execute

            def execute(name, arguments, cancel=None):
                if name == "update_plan":
                    return {"ok": True, "steps": len(arguments.get("steps", []))}
                return original_execute(name, arguments, cancel)

            # Each generation receives its own _RunDesktop wrapper, so this
            # temporary adapter is isolated even when multiple chats generate
            # concurrently.
            desktop.execute = execute
            try:
                result = super().run(*run_args, **run_kwargs)
            finally:
                desktop.execute = original_execute

        # Strip generated system context before finding the engine's new tail.
        result = project_instructions.strip(project_context.strip(result))
        fitted = project_instructions.strip(project_context.strip(inference_messages))
        return context_budget.merge_generated(full_history, fitted, result)
