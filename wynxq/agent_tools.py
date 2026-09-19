"""Tool schemas, permission policy, and validation for agent actions.

Transport and orchestration live in :mod:`wynxq.engine`; this module owns the
declarative tool contract and the policy that decides whether an action needs
approval. The split keeps policy independently testable and avoids coupling it
to Ollama networking.
"""
from __future__ import annotations

import math
import re

from .memory import SCOPES as MEMORY_SCOPES
from .native_core import native_core


def _tool(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or [],
                           "additionalProperties": False}}}


_COORD = {"type": "integer", "minimum": 0, "maximum": 32767}
TOOLS = [
    _tool("run_command", "Run a Bash command locally and return output and exit code. Use for files, coding, system inspection and CLI tasks. Use open_app for GUI applications. No interactive stdin; commands have a time limit.",
          {"command": {"type": "string", "minLength": 1, "maxLength": 12000},
           "cwd": {"type": "string", "maxLength": 4096},
           "timeout": {"type": "integer", "minimum": 1, "maximum": 300}}, ["command"]),
    _tool("screenshot", "Capture the current screen. The returned image uses screen pixel coordinates."),
    _tool("move_pointer", "Move the visible pointer to screen pixel coordinates.", {"x": _COORD, "y": _COORD}, ["x", "y"]),
    _tool("click", "Click an observed control at screen pixel coordinates.",
          {"x": _COORD, "y": _COORD, "button": {"type": "string", "enum": ["left", "middle", "right"]},
           "count": {"type": "integer", "minimum": 1, "maximum": 3}}, ["x", "y"]),
    _tool("hold_button", "Move to an observed point and hold a mouse button for a bounded duration, then always release it.",
          {"x": _COORD, "y": _COORD, "button": {"type": "string", "enum": ["left", "middle", "right"]},
           "seconds": {"type": "number", "minimum": 0.05, "maximum": 5}}, ["x", "y", "seconds"]),
    _tool("drag", "Hold the left button and follow points, for drawing or moving an object.",
          {"points": {"type": "array", "minItems": 2, "maxItems": 256,
                      "items": {"type": "array", "items": _COORD, "minItems": 2, "maxItems": 2}},
           "duration": {"type": "number", "minimum": 0.1, "maximum": 10}}, ["points"]),
    _tool("type_text", "Type literal text into the focused field. Never type commands into a terminal.",
          {"text": {"type": "string", "minLength": 1, "maxLength": 10000}}, ["text"]),
    _tool("press_key", "Press a key or chord, e.g. ['CTRL','S'], ['ENTER'], ['ESC']. Release after pressing.",
          {"keys": {"type": "array", "minItems": 1, "maxItems": 8,
                    "items": {"type": "string", "minLength": 1, "maxLength": 40}}}, ["keys"]),
    _tool("hold_key", "Hold one key or a chord for a bounded duration, then always release every key.",
          {"keys": {"type": "array", "minItems": 1, "maxItems": 8,
                    "items": {"type": "string", "minLength": 1, "maxLength": 40}},
           "seconds": {"type": "number", "minimum": 0.05, "maximum": 5}}, ["keys", "seconds"]),
    _tool("scroll", "Scroll at the pointer; positive dy scrolls downward, negative upward.",
          {"dx": {"type": "integer", "minimum": -20, "maximum": 20},
           "dy": {"type": "integer", "minimum": -20, "maximum": 20}}, ["dx", "dy"]),
    _tool("open_app", "Launch an installed application by its desktop ID or name from list_apps. No shell commands.",
          {"app": {"type": "string", "minLength": 1, "maxLength": 256}}, ["app"]),
    _tool("browser_open",
          "Open an address or search query in Wynxq's built-in Browser panel. Use this whenever "
          "the user says Wynxq browser, built-in browser, your browser, or asks to open a web page "
          "inside Wynxq. Do not use xdg-open or the system browser for those requests.",
          {"target": {"type": "string", "minLength": 1, "maxLength": 4096}}, ["target"]),
    _tool("wait", "Pause briefly to let an application update.",
          {"seconds": {"type": "number", "minimum": 0, "maximum": 5}}, ["seconds"]),
    _tool("list_apps", "List installed applications and desktop IDs that open_app can launch."),
    _tool("remember",
          "Save one durable fact to long-term memory, carried into every later task. "
          "Use it for a stable preference, a decision, or how a project works — never for "
          "something only true in this conversation, and never for a secret.",
          {"note": {"type": "string", "minLength": 1, "maxLength": 500},
           "scope": {"type": "string", "enum": list(MEMORY_SCOPES)}}, ["note"]),
    _tool("forget",
          "Remove every remembered note containing this text. Use it when a memory is "
          "wrong, out of date, or the user asks you to forget something.",
          {"query": {"type": "string", "minLength": 2, "maxLength": 200}}, ["query"]),
]
_SCHEMAS = {tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOLS}
MEMORY_TOOLS = {"remember", "forget"}
BROWSER_TOOLS = {"browser_open"}
# Tools that need no screen. Browser navigation is added dynamically only when
# Qt WebEngine is available; keeping it out of this base set prevents a model
# from seeing a tool the current installation cannot execute.
_NONVISUAL = {"open_app", "list_apps", "wait", "run_command"} | MEMORY_TOOLS
# GUI actions that are followed by a fresh visual observation so the next
# reasoning turn sees what actually happened instead of guessing.
_AUTO_OBSERVE = {"open_app", "wait", "click", "hold_button", "drag",
                 "type_text", "press_key", "hold_key", "scroll"}

# Permission modes: a ladder, from approving every action to approving none.
#
#   manual  every action that changes anything is approved first
#   safe    apps open directly; commands, clicks, drags, typing and key presses
#           are approved before they can change application state
#   auto    everything runs unattended, except a command that could destroy
#           data or reach the wider system, which is still approved
#   full    nothing is ever approved, including destructive commands
#
# Reading the screen, scrolling, and moving the pointer are observation: they
# do not commit an application action, so they never prompt in any mode.
MANUAL, SAFE, AUTO, FULL = "manual", "safe", "auto", "full"
PERMISSION_MODES = (MANUAL, SAFE, AUTO, FULL)
PERMISSION_LABELS = {MANUAL: "Manual", SAFE: "Auto-approve",
                     AUTO: "Auto", FULL: "Full access"}
PERMISSION_DETAILS = {
    MANUAL: "Approve every command and desktop action before it runs.",
    SAFE: "Open apps directly; approve clicks, drags, commands, typing and key presses.",
    AUTO: "Run unattended. A command that could destroy data is still approved.",
    FULL: "Never ask. Destructive commands run too — only for a session you are watching.",
}
# Databases written before the ladder existed stored "ask".
LEGACY_MODES = {"ask": MANUAL, "safe_auto": SAFE}
ASK = MANUAL  # kept so older callers and stored settings keep resolving


def normalise_mode(mode) -> str:
    """Resolve a stored or supplied mode, falling back to the safe default."""
    if native_core.available:
        try:
            return native_core.normalize_permission_mode(None if mode is None else str(mode))
        except RuntimeError:
            pass
    value = str(mode or "").strip().lower()
    value = LEGACY_MODES.get(value, value)
    return value if value in PERMISSION_MODES else SAFE


LOW_RISK = {"screenshot", "list_apps", "wait", "move_pointer", "scroll", "remember"}
# Typing, key chords, clicks and drags can save, send, delete, submit, or move
# data in whichever application is focused. Safe mode therefore keeps all of
# them behind approval; Auto and Full deliberately opt into unattended input.
SENSITIVE = {"type_text", "press_key", "hold_key", "run_command",
             "click", "hold_button", "drag"}

# Commands that can take the machine, its disks, its packages or its accounts
# with them. Auto runs everything else unattended; these it still puts in front
# of the user, because "it did what I asked, on the wrong folder" is the whole
# category of damage an unattended agent can do that cannot be undone.
# Keep this tuple semantically identical to native/src/permission_policy.cpp;
# tests/test_permission_parity.py compares both implementations directly.
_DESTRUCTIVE_PATTERNS = (
    r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+",         # rm -rf / rm -f, any flag order
    r"\brmdir\s+/",
    r"\bmkfs(\.[a-z0-9]+)?\b",
    r"\b(fdisk|sfdisk|parted|wipefs|shred|blkdiscard)\b",
    r"\bdd\b[^|;&]*\bof=/dev/",
    r">\s*/dev/(sd|nvme|vd|hd|mmcblk)",
    r"\b(shutdown|reboot|poweroff|halt)\b",
    r"\bsystemctl\s+(poweroff|reboot|halt|isolate)\b",
    r"\b(sudo|doas|pkexec|su)\s",
    r"\b(userdel|usermod|groupdel|chpasswd|visudo)\b",
    r"(^|[;&|]\s*)passwd\b",                 # reading /etc/passwd is not this
    r"\bchmod\s+(-[a-z]+\s+)*(777|-R\s+777)",
    r"\bcho(wn|rp)\s+(-[a-z]+\s+)*[^\s]+\s+/(\s|$)",
    r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b",
    r"\b(apt|apt-get|dnf|yum|pacman|zypper|snap|flatpak|pip3?|npm|cargo)\b"
    r"[^|;&]*\b(remove|purge|uninstall|autoremove|-R|-Rns)\b",
    r"\bgit\s+(push[^|;&]*--force|reset\s+--hard|clean\s+-[a-z]*f)",
    r"\bcrontab\s+-r\b",
    r"\bfind\b[^|;&]*-(delete|exec\s+rm)\b",
    r"\bkill(all)?\s+(-9\s+)?-1\b",
    r"\bdocker\s+(system\s+prune|volume\s+rm|rm\s+-f)\b",
    r"\btruncate\b[^|;&]*-s\s*0\b",
    r":\(\)\s*\{[^}]*\|[^}]*&[^}]*\}",       # the fork bomb
    r"\b(init\s+0|telinit\s+[06])\b",
)
_DESTRUCTIVE = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _DESTRUCTIVE_PATTERNS)


def command_risk(command) -> str:
    """Read a shell command: is it one that can take something away for good?"""
    text = str(command or "")
    if native_core.available:
        try:
            return "destructive" if native_core.command_is_destructive(text) else "normal"
        except RuntimeError:
            pass
    return "destructive" if any(pattern.search(text) for pattern in _DESTRUCTIVE) else "normal"


def action_risk(name: str, args: dict | None = None) -> str:
    """How much a single action can cost, given what it was asked to do.

    Without ``args`` this is the tool's baseline. With them, a command is read:
    ``ls`` and ``rm -rf ~`` are the same tool and not remotely the same risk.
    """
    if name == "run_command" and isinstance(args, dict) and command_risk(args.get("command")) == "destructive":
        return "destructive"
    if name in LOW_RISK:
        return "low"
    return "sensitive" if name in SENSITIVE else "normal"


def needs_confirmation(name: str, mode: str, args: dict | None = None) -> bool:
    """Whether ``mode`` requires the user to approve ``name`` before it runs."""
    if native_core.available:
        try:
            command = str(args.get("command", "")) if name == "run_command" and isinstance(args, dict) else None
            return native_core.needs_confirmation(name, mode, command)
        except RuntimeError:
            pass
    mode = normalise_mode(mode)
    risk = action_risk(name, args)
    if mode == FULL or risk == "low":
        return False
    if mode == AUTO:
        return risk == "destructive"
    return True if mode == MANUAL else risk in {"sensitive", "destructive"}


def action_summary(name: str, args: dict | None = None) -> str:
    """A short human sentence for a permission prompt or activity row."""
    args = args if isinstance(args, dict) else {}
    if name == "click":
        button = args.get("button", "left")
        count = args.get("count", 1)
        clicks = {2: "Double-click", 3: "Triple-click"}.get(count, "Click")
        where = f" at {args.get('x')}, {args.get('y')}" if "x" in args else ""
        return f"{clicks} the {button} button{where}"
    if name == "hold_button":
        return (f"Hold the {args.get('button', 'left')} button at "
                f"{args.get('x')}, {args.get('y')} for {args.get('seconds', 0.25)}s")
    if name == "type_text":
        text = str(args.get("text", ""))
        preview = text if len(text) <= 60 else text[:57] + "…"
        return f"Type “{preview}”"
    if name in ("press_key", "hold_key"):
        keys = args.get("keys")
        combo = " + ".join(str(k).upper() for k in keys) if isinstance(keys, list) else "a key"
        return (f"Hold {combo} for {args.get('seconds', 0.25)}s"
                if name == "hold_key" else f"Press {combo}")
    if name == "run_command":
        return "Run " + str(args.get("command", "a command"))[:120]
    if name == "open_app":
        return f"Open {args.get('app', 'an application')}"
    if name == "browser_open":
        return f"Open {args.get('target', 'a page')} in Wynxq Browser"
    if name == "drag":
        points = args.get("points")
        count = len(points) if isinstance(points, list) else 0
        return f"Drag through {count} points" if count else "Drag the pointer"
    if name == "move_pointer":
        return f"Move the pointer to {args.get('x')}, {args.get('y')}"
    if name == "scroll":
        return f"Scroll {args.get('dy', 0):+d} vertically" if args.get("dy") else "Scroll"
    if name == "wait":
        return f"Wait {args.get('seconds', 1)}s"
    if name == "screenshot":
        return "Capture the screen"
    if name == "list_apps":
        return "List installed applications"
    if name == "remember":
        note = str(args.get("note", ""))
        return "Remember “" + (note if len(note) <= 60 else note[:57] + "…") + "”"
    if name == "forget":
        return f"Forget notes about “{args.get('query', '')}”"
    return name.replace("_", " ").capitalize()


def _validate(value, schema: dict, location: str = "arguments") -> None:
    kind = schema.get("type")
    matches = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
               "string": lambda: isinstance(value, str),
               "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
               "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)}
    if kind in matches and not matches[kind]():
        raise ValueError(f"{location} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location} must be one of {schema['enum']}")
    if kind == "object":
        required = set(schema.get("required", []))
        if required - value.keys():
            raise ValueError(f"{location} missing {', '.join(sorted(required - value.keys()))}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ValueError(f"Unexpected {location}: {', '.join(sorted(value.keys() - properties.keys()))}")
        for key, child in value.items():
            if key in properties:
                _validate(child, properties[key], f"{location}.{key}")
    if kind in {"array", "string"}:
        lower, upper = ("minItems", "maxItems") if kind == "array" else ("minLength", "maxLength")
        if len(value) < schema.get(lower, 0) or len(value) > schema.get(upper, float("inf")):
            raise ValueError(f"{location} has an invalid length")
        if kind == "array":
            for item in value:
                _validate(item, schema.get("items", {}), f"{location}[]")
    if kind in {"integer", "number"} and not schema.get("minimum", -float("inf")) <= value <= schema.get("maximum", float("inf")):
        raise ValueError(f"{location} is out of range")


def validate_tool_call(name: str, arguments: dict) -> None:
    if name not in _SCHEMAS:
        raise ValueError(f"Unknown desktop tool: {name}")
    _validate(arguments, _SCHEMAS[name])


__all__ = [
    "ASK", "AUTO", "BROWSER_TOOLS", "FULL", "LEGACY_MODES", "LOW_RISK",
    "MANUAL", "MEMORY_TOOLS", "PERMISSION_DETAILS", "PERMISSION_LABELS",
    "PERMISSION_MODES", "SAFE", "SENSITIVE", "TOOLS", "_AUTO_OBSERVE",
    "_NONVISUAL", "_SCHEMAS", "action_risk", "action_summary", "command_risk",
    "needs_confirmation", "normalise_mode", "validate_tool_call",
]
