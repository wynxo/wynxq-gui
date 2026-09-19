"""Explicitly enabled desktop control; no shell commands are accepted from models.

X11 uses XTEST and Pillow. Wayland uses a long-lived XDG RemoteDesktop portal
session, with Screenshot portal captures. ScreenCast stream metadata maps
multi-monitor screenshots back to the selected input stream.
Portal interfaces: https://flatpak.github.io/xdg-desktop-portal/docs/
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import configparser
import importlib.util
import io
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.parse import unquote, urlparse
import uuid


from .desktop_common import (
    DesktopCancelled, DesktopError, SessionTokens, _KEYSYMS,
    _application_inventory, _check, _integer, _keysym, _number, _pause,
    _png_result, _qt_monitor_layout,
)
from .desktop_backends import GlobalStop, X11GlobalStop, _PortalBackend, _X11Backend


class DesktopController:
    """Synchronous interface for Qt workers. Construction never grants control.

    Call connect() only after the user enables desktop control. ``execute``
    raises DesktopError; connect() reports any error in its returned status.
    Input and screenshot operations are serialized, with interruptible waits.
    """

    def set_stop_handler(self, handler) -> None:
        """Called before connect(): what a global stop shortcut should do.

        It fires on the portal's own thread, so the handler must be safe to
        call from anywhere — the app posts it onto the GUI thread.
        """
        if self._backend is not None and hasattr(self._backend, "on_stop"):
            self._backend.on_stop = handler

    def __init__(self, *, monitor_layout: list[dict] | None = None, backend=None, tokens=None):
        self._lock = threading.RLock()
        self._enabled = False
        self._detail = "Desktop control is off. Enable it to connect."
        if backend is not None:
            self._backend = backend
        elif os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            self._backend = _PortalBackend(monitor_layout if monitor_layout is not None else _qt_monitor_layout(),
                                           tokens=tokens)
        elif os.environ.get("DISPLAY"):
            self._backend = _X11Backend()
        else:
            self._backend = None
        self._size: tuple[int, int] | None = None
        # Where the pointer was last put, so motion can be drawn from it.
        self._pointer: tuple[float, float] | None = None
        # Desktop permission may stay connected for the whole app session, but
        # the emergency shortcut belongs only to the foreground run that is
        # actually observing/controlling the screen.
        self._control_owner = ""

    def status(self) -> dict:
        backend = self._backend
        available = bool(backend and backend.available)
        connected = bool(self._enabled and backend and backend.connected)
        shortcut = getattr(backend, "stop_shortcut", None) if connected else None
        detail = self._detail
        if backend is None:
            detail = "No graphical Linux session found. Chat is still available."
        elif not available:
            detail = backend.unavailable_reason
        elif self._enabled and not backend.connected:
            detail = "Desktop access ended. Enable control to reconnect."
        return {"backend": backend.name if backend else "unavailable", "available": available,
                "connected": connected, "detail": detail,
                "controlActive": bool(connected and self._control_owner),
                "controlOwner": self._control_owner if connected else "",
                # True once the desktop granted control without asking again.
                "remembered": bool(connected and getattr(backend, "restored", False)),
                # How to stop a run while another window has focus, when the
                # desktop supports binding one.
                "stopShortcut": shortcut.trigger if shortcut else "",
                "stopDetail": shortcut.detail if shortcut else ""}

    def connect(self) -> dict:
        with self._lock:
            if self.status()["connected"]:
                return self.status()
            if not self.status()["available"]:
                return self.status()
            # An unexpectedly closed portal session must never carry an old
            # takeover owner into a freshly authorized connection.
            self._control_owner = ""
            try:
                self._backend.connect()
                self._enabled = True
                self._detail = self._backend.detail
            except Exception as exc:
                self._enabled = False
                self._detail = str(exc) or type(exc).__name__
            return self.status()

    def begin_control(self, owner: str = "") -> dict:
        """Start the visible/emergency-stop layer for one foreground run.

        Authorization and active control are deliberately separate: keeping a
        portal permission does not mean Wynxq is currently driving the desktop.
        """
        requested = str(owner or "active")
        with self._lock:
            self._permission(None)
            if self._control_owner and self._control_owner != requested:
                if hasattr(self._backend, "end_control"):
                    self._backend.end_control()
                self._control_owner = ""
            if not self._control_owner:
                if hasattr(self._backend, "begin_control"):
                    self._backend.begin_control()
                self._control_owner = requested
            return self.status()

    def end_control(self, owner: str = "") -> dict:
        """Release held input and the temporary global stop shortcut."""
        requested = str(owner or "")
        with self._lock:
            if requested and self._control_owner and requested != self._control_owner:
                return self.status()
            try:
                if self._backend and hasattr(self._backend, "end_control"):
                    self._backend.end_control()
            finally:
                self._control_owner = ""
            return self.status()

    def disconnect(self) -> None:
        # Revoke the permission gate immediately, even while an action holds
        # the lock. The worker should also receive its cancellation Event.
        self._enabled = False
        with self._lock:
            try:
                if self._backend and hasattr(self._backend, "end_control"):
                    self._backend.end_control()
            finally:
                self._control_owner = ""
            if self._backend:
                self._backend.disconnect()
            self._size = None
            self._pointer = None
            self._detail = "Desktop control is off."

    def capture(self, kind: str = "screen", cancel: threading.Event | None = None) -> dict:
        """Read-only screen or window capture for chat context.

        This never requires — and never grants — input control, and it
        deliberately does not record a coordinate space: a picture taken for
        context must not become the basis for clicking somewhere later.
        """
        backend = self._backend
        if backend is None:
            raise DesktopError("No graphical Linux session found, so the screen cannot be captured.")
        if not backend.available:
            raise DesktopError(backend.unavailable_reason)
        _check(cancel)
        picture, detail = backend.capture(kind, cancel)
        result = _png_result(picture, backend.name)
        result.pop("coordinate_space", None)
        result["detail"] = detail
        result["capture"] = kind
        return result

    def active_window(self) -> dict:
        """Best-effort title of the focused window, for a context label."""
        backend = self._backend
        if backend is None or not backend.available:
            return {"title": "", "detail": "No graphical session"}
        try:
            return backend.active_window()
        except Exception as exc:
            return {"title": "", "detail": str(exc)[:160]}

    def _permission(self, cancel) -> None:
        _check(cancel)
        if not self.status()["connected"]:
            raise DesktopError("Desktop control is off. Enable it before running desktop actions.")

    # A pointer that jumps cannot be followed, and a user who cannot see where
    # it is going has no chance to stop it. Motion is drawn out just enough to
    # read, and every step re-checks permission and cancellation.
    _GLIDE_SECONDS = 0.16
    _GLIDE_STEPS = 12

    def _glide(self, x: float, y: float, cancel) -> None:
        start = self._pointer
        self._pointer = (x, y)
        distance = 0.0 if start is None else math.hypot(x - start[0], y - start[1])
        if start is None or distance < 8:
            self._backend.move(x, y, cancel)
            return
        steps = max(2, min(self._GLIDE_STEPS, int(distance / 24)))
        for step in range(1, steps + 1):
            self._permission(cancel)
            fraction = step / steps
            # Ease out, so the pointer settles on its target rather than
            # arriving at full speed.
            eased = 1 - (1 - fraction) ** 3
            self._backend.move(start[0] + (x - start[0]) * eased,
                               start[1] + (y - start[1]) * eased, cancel)
            if step < steps:
                _pause(self._GLIDE_SECONDS / steps, cancel)

    def _point(self, args: dict) -> tuple[float, float]:
        if not self._size:
            raise DesktopError("Take a screenshot before using pointer coordinates.")
        return (_number(args.get("x"), "x", 0, self._size[0] - 1),
                _number(args.get("y"), "y", 0, self._size[1] - 1))

    def execute(self, name: str, args: dict, cancel: threading.Event | None = None) -> dict:
        if not isinstance(args, dict):
            raise DesktopError("Tool arguments must be an object.")
        with self._lock:
            _check(cancel)
            if name == "list_apps":
                apps = [{k: v for k, v in a.items() if k != "path"} for a in _application_inventory()]
                return {"ok": True, "apps": apps}
            if name == "open_app":
                self._open_app(args, cancel)
                return {"ok": True, "action": name, "app": args["app"]}
            if name == "wait":
                _pause(_number(args.get("seconds", 1), "seconds", 0, 5), cancel)
                return {"ok": True, "action": name}
            self._permission(cancel)
            if name == "screenshot":
                picture = self._backend.screenshot(cancel)
                self._permission(cancel)
                # A different coordinate space invalidates the remembered
                # pointer; motion must never be drawn from a stale point.
                if self._size != picture.size:
                    self._pointer = None
                self._size = picture.size
                return _png_result(picture, self._backend.name)
            if name == "move_pointer":
                self._glide(*self._point(args), cancel=cancel)
            elif name == "click":
                point = self._point(args)
                button = args.get("button", "left")
                if button not in ("left", "middle", "right"):
                    raise DesktopError("button must be left, middle, or right.")
                count = _integer(args.get("count", 1), "count", 1, 3)
                self._glide(*point, cancel=cancel)
                for _ in range(count):
                    self._permission(cancel)
                    try:
                        self._backend.button(button, True, cancel)
                        _pause(0.045, cancel)
                    finally:
                        self._backend.button(button, False, None)
                    _pause(0.065, cancel)
            elif name == "drag":
                raw = args.get("points")
                if not isinstance(raw, list) or not 2 <= len(raw) <= 500:
                    raise DesktopError("A drag needs 2 to 500 [x, y] points.")
                if any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in raw):
                    raise DesktopError("Each drag point must be [x, y].")
                points = [self._point({"x": p[0], "y": p[1]}) for p in raw]
                duration = _number(args.get("duration", 1), "duration", 0.1, 10)
                self._glide(*points[0], cancel=cancel)
                try:
                    self._backend.button("left", True, cancel)
                    # Interpolate even two-point drags to produce actual strokes.
                    segments = max(len(points) - 1, int(duration * 60))
                    for step in range(1, segments + 1):
                        self._permission(cancel)
                        position = step / segments * (len(points) - 1)
                        index = min(int(position), len(points) - 2)
                        fraction = position - index
                        x = points[index][0] + (points[index + 1][0] - points[index][0]) * fraction
                        y = points[index][1] + (points[index + 1][1] - points[index][1]) * fraction
                        self._backend.move(x, y, cancel)
                        self._pointer = (x, y)
                        _pause(duration / segments, cancel)
                finally:
                    self._backend.button("left", False, None)
            elif name == "hold_button":
                point = self._point(args)
                button = args.get("button", "left")
                if button not in ("left", "middle", "right"):
                    raise DesktopError("button must be left, middle, or right.")
                duration = _number(args.get("seconds", 0.25), "seconds", 0.05, 5)
                self._glide(*point, cancel=cancel)
                try:
                    self._backend.button(button, True, cancel)
                    _pause(duration, cancel)
                finally:
                    self._backend.button(button, False, None)
            elif name == "type_text":
                value = args.get("text")
                if not isinstance(value, str) or not 1 <= len(value) <= 4000:
                    raise DesktopError("text must contain 1 to 4000 characters.")
                syms = [_keysym(character) for character in value]
                self._backend.validate_keys(syms)
                for sym in syms:
                    self._permission(cancel)
                    self._chord([sym], cancel)
            elif name in ("press_key", "hold_key"):
                keys = args.get("keys")
                if not isinstance(keys, list) or not 1 <= len(keys) <= 8:
                    raise DesktopError("keys must contain 1 to 8 key names.")
                syms = [_keysym(key) for key in keys]
                if len(set(syms)) != len(syms):
                    raise DesktopError("A key chord cannot contain duplicate keys.")
                self._backend.validate_keys(syms)
                duration = 0.025 if name == "press_key" else _number(
                    args.get("seconds", 0.25), "seconds", 0.05, 5)
                self._hold_chord(syms, duration, cancel)
            elif name == "scroll":
                dx = _integer(args.get("dx", 0), "dx", -30, 30)
                dy = _integer(args.get("dy", 0), "dy", -30, 30)
                self._backend.scroll(dx, dy, cancel)
            else:
                raise DesktopError(f"Unknown desktop tool: {str(name)[:60]}")
            self._permission(cancel)
            return {"ok": True, "action": name}

    def _chord(self, syms, cancel) -> None:
        self._hold_chord(syms, 0.025, cancel)

    def _hold_chord(self, syms, seconds, cancel) -> None:
        pressed = []
        try:
            for sym in syms:
                self._permission(cancel)
                pressed.append(sym)
                self._backend.key(sym, True, cancel)
            _pause(seconds, cancel)
        finally:
            # Never let cancellation skip key releases.
            failures = []
            for sym in reversed(pressed):
                try:
                    self._backend.key(sym, False, None)
                except Exception as exc:
                    failures.append(exc)
            if failures:
                self._enabled = False
                raise DesktopError("Keyboard release failed; desktop control has been disabled.") from failures[0]

    def _open_app(self, args, cancel):
        requested = args.get("app")
        if not isinstance(requested, str) or not requested.strip() or len(requested) > 200:
            raise DesktopError("app must be a name or ID from list_apps.")
        query = requested.strip().casefold()
        matches = [a for a in _application_inventory()
                   if query in (a["id"].casefold(), a["name"].casefold(), a["id"].removesuffix(".desktop").casefold())]
        if len(matches) != 1:
            raise DesktopError("Choose an exact installed application name or ID from list_apps.")
        launcher = shutil.which("gio")
        if not launcher:
            raise DesktopError("Install libglib2.0-bin (gio) to launch applications.")
        _check(cancel)
        # gio interprets the installed desktop entry; model text never becomes
        # an executable, a shell expression, a file path, or a command argument.
        process = subprocess.run([launcher, "launch", matches[0]["path"]],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=10, check=False)
        if process.returncode:
            raise DesktopError(f"Could not open {matches[0]['name']} (launcher exit {process.returncode}).")


