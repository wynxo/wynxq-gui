"""Execution boundary for one agent run.

The engine decides which tools are exposed. ToolExecutor validates and
executes one allowed call, owns approval checks, and emits evidence events.
It is pure Python and intentionally independent of Qt.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from .commands import run_command
from .agent_tools import (
    MEMORY_TOOLS, _AUTO_OBSERVE, _NONVISUAL,
    action_risk, action_summary, needs_confirmation, validate_tool_call,
)
from .memory import GLOBAL as MEMORY_GLOBAL
from .ollama import Cancelled, _stopped


LOG = logging.getLogger(__name__)


class ToolExecutor:
    """Execute validated tool calls for a single bounded agent run."""

    def __init__(self, *, desktop, memory, browser_open, project: str, cancel,
                 emit: Callable[[dict], None],
                 permission_mode: Callable[[], str],
                 confirm: Callable[[str, dict, str], bool] | None,
                 visual: bool, append_screen: Callable[[dict], None]):
        self.desktop = desktop
        self.memory = memory
        self.browser_open = browser_open
        self.project = project
        self.cancel = cancel
        self.emit = emit
        self.permission_mode = permission_mode
        self.confirm = confirm
        self.visual = visual
        self.append_screen = append_screen

    def _event(self, kind: str, **fields) -> None:
        self.emit({"type": kind, **fields})

    def execute(self, name: str, args: dict, allowed: set[str]) -> dict:
        risk = action_risk(name, args)
        action_mode = self.permission_mode()
        confirming = needs_confirmation(name, action_mode, args) and name in allowed
        started = time.monotonic()
        self._event("tool_start", name=name, args=args, risk=risk,
                    summary=action_summary(name, args), confirming=confirming)

        def finish(result: dict, **extra) -> dict:
            # Pixel payloads go only into vision input, never into logs/cards.
            self._event(
                "tool_end",
                name=name,
                ms=round((time.monotonic() - started) * 1000),
                result={key: value for key, value in result.items() if key != "image"},
                **extra,
            )
            return result

        try:
            if _stopped(self.cancel):
                raise Cancelled("Stopped")
            if name not in allowed:
                raise ValueError(
                    f"Tool {name!r} is not enabled for this model and desktop session"
                )
            validate_tool_call(name, args)
            status = self.desktop.status() if self.desktop else {}
            if name not in _NONVISUAL and not status.get("connected"):
                raise RuntimeError("Desktop permission was disconnected")

            if self.confirm is not None and confirming:
                if not self.confirm(name, args, risk):
                    if _stopped(self.cancel):
                        raise Cancelled("Stopped")
                    return finish({
                        "ok": False,
                        "declined": True,
                        "error": (
                            "The user declined this action. Do not retry it; "
                            "explain what you wanted to do and ask how to continue."
                        ),
                    }, declined=True)
                if _stopped(self.cancel):
                    raise Cancelled("Stopped")
                # Permission can be revoked while the prompt is on screen.
                if name not in _NONVISUAL and not self.desktop.status().get("connected"):
                    raise RuntimeError("Desktop permission was disconnected")

            if name in MEMORY_TOOLS:
                if self.memory is None:
                    raise RuntimeError("Memory is turned off")
                if name == "remember":
                    result = self.memory.remember(
                        args.get("note", ""), args.get("scope", MEMORY_GLOBAL), self.project
                    )
                else:
                    result = self.memory.forget(args.get("query", ""))
            elif name == "browser_open":
                if self.browser_open is None:
                    raise RuntimeError("Wynxq's built-in browser is unavailable")
                result = self.browser_open(str(args.get("target", "")))
            elif name == "run_command":
                base = Path(self.project).expanduser().resolve() if self.project else Path.home()
                requested = Path(args.get("cwd") or base).expanduser()
                if not requested.is_absolute():
                    requested = base / requested
                result = run_command(
                    args["command"], str(requested), args.get("timeout", 60), self.cancel
                )
            else:
                if name not in _NONVISUAL:
                    self._event("control_active", action=name)
                result = self.desktop.execute(name, args, self.cancel)

            if not isinstance(result, dict):
                raise RuntimeError("Desktop tool returned an invalid result")

            if (self.visual and result.get("ok", True) and name in _AUTO_OBSERVE
                    and not _stopped(self.cancel)):
                try:
                    self._event("control_active", action="screenshot")
                    # Let the compositor paint the input result before capturing it.
                    delay = 0.6 if name == "open_app" else 0.2
                    if self.cancel.wait(delay):
                        raise Cancelled("Stopped")
                    observed = self.desktop.execute("screenshot", {}, self.cancel)
                    if not observed.get("ok", True) or not observed.get("image"):
                        raise RuntimeError(observed.get("error") or "Screenshot returned no image")
                    self.append_screen(observed)
                    result = {
                        **result,
                        "screen_observed": {
                            "width": observed.get("width"),
                            "height": observed.get("height"),
                        },
                    }
                    self._event(
                        "screen_observed",
                        action=name,
                        width=observed.get("width"),
                        height=observed.get("height"),
                    )
                except Cancelled:
                    raise
                except Exception as exc:
                    # The primary input may have succeeded even if observing
                    # its result did not; report both truths to the model.
                    result = {**result, "screen_observation_error": str(exc)}
        except Cancelled:
            finish({"ok": False, "error": "Stopped; the action may be partial"})
            raise
        except Exception as exc:
            if _stopped(self.cancel):
                finish({"ok": False, "error": "Stopped; the action may be partial"})
                raise Cancelled("Stopped") from exc
            LOG.warning("Desktop tool %s failed: %s", name, exc)
            result = {"ok": False, "error": str(exc)}
        return finish(result)
