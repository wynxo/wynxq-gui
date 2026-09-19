"""Shared desktop-control types, validation, and data conversion helpers.

This module is backend-agnostic. X11/portal implementations and the public
DesktopController both depend on it, which keeps validation rules in one place
without creating backend-to-controller import cycles.
"""
from __future__ import annotations

import base64
import configparser
import io
import math
import os
from pathlib import Path
import shutil
import threading
import time


class SessionTokens:
    """Where the portal's restore token is kept between runs.

    The token is single-use: the portal issues a fresh one every time a
    session starts, so it is always overwritten rather than appended to.
    The default keeps it in memory, which is what tests and one-off uses
    want; the app hands in a store-backed one so screen control stops
    asking permission on every launch.
    """

    def __init__(self):
        self._token = ""

    def load(self) -> str:
        return self._token

    def save(self, token: str) -> None:
        self._token = str(token or "")

    def clear(self) -> None:
        self.save("")


class DesktopError(RuntimeError):
    """An unsupported, unapproved, or failed desktop action."""


class DesktopCancelled(DesktopError):
    """The user stopped the current action."""


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise DesktopCancelled("Desktop action stopped.")


def _pause(seconds: float, cancel: threading.Event | None) -> None:
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise DesktopCancelled("Desktop action stopped.")


def _number(value, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DesktopError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise DesktopError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return value


def _integer(value, name: str, minimum: int, maximum: int) -> int:
    number = _number(value, name, minimum, maximum)
    if not number.is_integer():
        raise DesktopError(f"{name} must be an integer.")
    return int(number)


def _png_result(picture, backend: str) -> dict:
    output = io.BytesIO()
    picture.convert("RGB").save(output, format="PNG")
    return {"ok": True, "image": base64.b64encode(output.getvalue()).decode("ascii"),
            "width": picture.width, "height": picture.height, "mime_type": "image/png",
            "backend": backend, "coordinate_space": "screenshot pixels"}


_KEYSYMS = {
    "ctrl": 0xFFE3, "control": 0xFFE3, "alt": 0xFFE9,
    "shift": 0xFFE1, "super": 0xFFEB, "meta": 0xFFEB, "win": 0xFFEB,
    "enter": 0xFF0D, "return": 0xFF0D, "escape": 0xFF1B, "esc": 0xFF1B,
    "tab": 0xFF09, "backspace": 0xFF08, "delete": 0xFFFF, "del": 0xFFFF,
    "insert": 0xFF63, "home": 0xFF50, "end": 0xFF57,
    "pageup": 0xFF55, "pagedown": 0xFF56,
    "left": 0xFF51, "up": 0xFF52, "right": 0xFF53, "down": 0xFF54,
    "space": 0x20, "capslock": 0xFFE5,
    **{f"f{i}": 0xFFBD + i for i in range(1, 25)},
}


def _keysym(key: str) -> int:
    if not isinstance(key, str) or not key:
        raise DesktopError("Each key must be a key name or a single character.")
    if key.lower() in _KEYSYMS:
        return _KEYSYMS[key.lower()]
    if len(key) == 1:
        if key in "\n\r\t":
            return {"\n": 0xFF0D, "\r": 0xFF0D, "\t": 0xFF09}[key]
        if not key.isprintable():
            raise DesktopError("Unsupported control character.")
        return ord(key) if ord(key) < 256 else 0x01000000 | ord(key)
    raise DesktopError(f"Unknown key: {key[:40]}")


def _qt_monitor_layout() -> list[dict]:
    # Called once from the GUI thread, never from the portal event loop.
    try:
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance():
            return [{"x": s.geometry().x(), "y": s.geometry().y(),
                     "width": s.geometry().width(), "height": s.geometry().height()}
                    for s in QGuiApplication.screens()]
    except ImportError:
        pass
    return []


def _application_inventory() -> list[dict]:
    roots = [Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))]
    roots += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    seen, result = set(), []
    for root in roots:
        directory = root / "applications"
        for path in sorted(directory.glob("**/*.desktop")):
            app_id = str(path.relative_to(directory)).replace("/", "-")
            if app_id in seen:
                continue
            seen.add(app_id)  # Hidden user overrides also mask system entries.
            config = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                config.read(path, encoding="utf-8")
                section = config["Desktop Entry"]
                if section.get("Type") != "Application" or section.getboolean("Hidden", False):
                    continue
                if section.getboolean("NoDisplay", False) or not section.get("Name"):
                    continue
                desktops = set(os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"))
                only = set(filter(None, section.get("OnlyShowIn", "").split(";")))
                excluded = set(filter(None, section.get("NotShowIn", "").split(";")))
                if (only and not only.intersection(desktops)) or excluded.intersection(desktops):
                    continue
                if section.get("TryExec") and not shutil.which(section["TryExec"]):
                    continue
                if not section.get("Exec") and not section.getboolean("DBusActivatable", False):
                    continue
                result.append({"id": app_id, "name": section["Name"],
                               "description": section.get("Comment", "")[:200], "path": str(path)})
            except (OSError, KeyError, ValueError, configparser.Error):
                continue
    return sorted(result, key=lambda app: app["name"].casefold())


__all__ = [
    "DesktopCancelled", "DesktopError", "SessionTokens", "_KEYSYMS",
    "_application_inventory", "_check", "_integer", "_keysym", "_number",
    "_pause", "_png_result", "_qt_monitor_layout",
]
