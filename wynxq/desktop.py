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


class _X11Backend:
    name = "X11 / XTEST"
    detail = "Connected to X11. Screenshot coordinates cover the desktop."

    def __init__(self):
        self.available = all(importlib.util.find_spec(p) is not None for p in ("Xlib", "PIL"))
        self.unavailable_reason = "Install the app dependencies (python-xlib and Pillow) for X11 control."
        self.connected = False
        self._display = None
        self._held = {}
        self._held_buttons = set()
        self.on_stop = None
        self.stop_shortcut = None

    def connect(self):
        from Xlib import display
        self._display = display.Display()
        if not self._display.has_extension("XTEST"):
            self._display.close()
            self._display = None
            raise DesktopError("This X server does not support the XTEST input extension.")
        self.connected = True

    def begin_control(self):
        if self.on_stop is not None and self.stop_shortcut is None:
            shortcut = X11GlobalStop(self.on_stop)
            shortcut.bind()
            self.stop_shortcut = shortcut

    def release_all(self):
        if not self._display:
            return
        for button in list(self._held_buttons):
            try:
                self.button(button, False, None)
            except Exception:
                pass
        for sym in list(self._held):
            try:
                self.key(sym, False, None)
            except Exception:
                pass

    def end_control(self):
        self.release_all()
        shortcut, self.stop_shortcut = self.stop_shortcut, None
        if shortcut is not None:
            shortcut.release()

    def disconnect(self):
        if self._display:
            self.end_control()
            self._display.close()
        self._display = None
        self.connected = False

    def screenshot(self, cancel):
        from PIL import ImageGrab
        _check(cancel)
        return ImageGrab.grab(xdisplay=os.environ.get("DISPLAY", ""))

    def _read_only_display(self):
        from Xlib import display
        return display.Display()

    def _focused(self, connection):
        """Return (window, title) for the focused window, or (None, "")."""
        root = connection.screen().root
        try:
            atom = connection.intern_atom("_NET_ACTIVE_WINDOW")
            value = root.get_full_property(atom, 0)
            window = connection.create_resource_object("window", value.value[0]) if value and value.value else None
        except Exception:
            window = None
        if window is None:
            window = connection.get_input_focus().focus
        title = ""
        for name in ("_NET_WM_NAME", "WM_NAME"):
            try:
                prop = window.get_full_property(connection.intern_atom(name), 0)
                if prop and prop.value:
                    title = prop.value.decode("utf-8", "replace") if isinstance(prop.value, bytes) else str(prop.value)
                    break
            except Exception:
                continue
        return window, title.strip()

    def active_window(self):
        connection = self._read_only_display()
        try:
            _, title = self._focused(connection)
            return {"title": title, "detail": "X11"}
        finally:
            connection.close()

    def capture(self, kind, cancel):
        from PIL import ImageGrab
        _check(cancel)
        full = ImageGrab.grab(xdisplay=os.environ.get("DISPLAY", ""))
        if kind != "window":
            return full, "Full screen"
        connection = self._read_only_display()
        try:
            window, title = self._focused(connection)
            geometry = window.get_geometry()
            origin = window.translate_coords(connection.screen().root, 0, 0)
            left, top = -origin.x, -origin.y
            box = (max(0, left), max(0, top),
                   min(full.width, left + geometry.width), min(full.height, top + geometry.height))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                return full, "Full screen (window bounds unavailable)"
            return full.crop(box), title or "Active window"
        except Exception:
            return full, "Full screen (window bounds unavailable)"
        finally:
            connection.close()

    def move(self, x, y, cancel):
        from Xlib import X
        from Xlib.ext import xtest
        _check(cancel)
        xtest.fake_input(self._display, X.MotionNotify, x=round(x), y=round(y))
        self._display.sync()

    def button(self, button, down, cancel):
        from Xlib import X
        from Xlib.ext import xtest
        _check(cancel)
        code = {"left": 1, "middle": 2, "right": 3}[button]
        xtest.fake_input(self._display, X.ButtonPress if down else X.ButtonRelease, code)
        if down:
            self._held_buttons.add(button)
        else:
            self._held_buttons.discard(button)
        self._display.sync()

    def _mapping(self, sym):
        # Xlib's second tuple field is the keymap column. Columns 0/1 are
        # unshifted/shifted in the current group; other groups need XKB support.
        mappings = [(code, index) for code, index in self._display.keysym_to_keycodes(sym) if index in (0, 1)]
        if not mappings:
            raise DesktopError("A character is unavailable in the active X11 keyboard layout. Use the matching layout or Wayland portal.")
        return min(mappings, key=lambda pair: pair[1])

    def validate_keys(self, syms):
        for sym in syms:
            self._mapping(sym)

    def key(self, sym, down, cancel):
        from Xlib import X
        from Xlib.ext import xtest
        _check(cancel)
        if down:
            code, column = self._mapping(sym)
            shift = self._display.keysym_to_keycode(_KEYSYMS["shift"]) if column == 1 else None
            # Record first so a subsequent error can still release the keys.
            self._held[sym] = (code, shift)
            if shift:
                xtest.fake_input(self._display, X.KeyPress, shift)
            xtest.fake_input(self._display, X.KeyPress, code)
        else:
            held = self._held.pop(sym, None)
            if held:
                code, shift = held
                xtest.fake_input(self._display, X.KeyRelease, code)
                if shift:
                    xtest.fake_input(self._display, X.KeyRelease, shift)
        self._display.sync()

    def scroll(self, dx, dy, cancel):
        from Xlib import X
        from Xlib.ext import xtest
        for delta, negative, positive in ((dy, 4, 5), (dx, 6, 7)):
            for _ in range(abs(delta)):
                _check(cancel)
                code = negative if delta < 0 else positive
                try:
                    xtest.fake_input(self._display, X.ButtonPress, code)
                finally:
                    xtest.fake_input(self._display, X.ButtonRelease, code)
                self._display.sync()


class X11GlobalStop:
    """Temporary bare-Escape grab while Wynxq is actively controlling X11."""

    trigger = "Esc"
    detail = "Emergency stop: Esc"

    def __init__(self, on_stop):
        self._on_stop = on_stop
        self._display = None
        self._root = None
        self._keycode = 0
        self._stop = threading.Event()
        self._thread = None

    def bind(self) -> None:
        from Xlib import X, display
        try:
            connection = display.Display()
            root = connection.screen().root
            code = connection.keysym_to_keycode(_KEYSYMS["escape"])
            root.grab_key(code, X.AnyModifier, False, X.GrabModeAsync, X.GrabModeAsync)
            connection.sync()
            self._display, self._root, self._keycode = connection, root, code
            self._thread = threading.Thread(
                target=self._watch, name="wynxq-x11-emergency-stop", daemon=True)
            self._thread.start()
        except Exception as exc:
            self.detail = "Global Esc unavailable: " + str(exc)[:100]
            try:
                connection.close()
            except Exception:
                pass

    def _watch(self) -> None:
        from Xlib import X
        while not self._stop.wait(0.02):
            try:
                while self._display and self._display.pending_events():
                    event = self._display.next_event()
                    if event.type == X.KeyPress and event.detail == self._keycode:
                        self._on_stop()
                        return
            except Exception:
                return

    def release(self) -> None:
        self._stop.set()
        connection, root = self._display, self._root
        self._display = self._root = None
        if connection and root:
            try:
                from Xlib import X
                root.ungrab_key(self._keycode, X.AnyModifier)
                connection.sync()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(0.2)
        self._thread = None


class GlobalStop:
    """A stop key that works while another application has focus.

    Wynxq's own Escape only reaches it when Wynxq is focused, which is exactly
    what it is not while a model is driving some other window. The
    GlobalShortcuts portal is the Wayland-supported way to be reachable
    anyway. The compositor owns the binding: it may assign a different key
    from the one asked for, or refuse entirely, so the trigger it reports back
    is what gets shown to the user rather than an assumption.
    """

    _DEST = "org.freedesktop.portal.Desktop"
    _PATH = "/org/freedesktop/portal/desktop"
    _IFACE = "org.freedesktop.portal.GlobalShortcuts"
    SHORTCUT = "stop"
    # This shortcut only exists while a foreground control session is active,
    # so asking for bare Escape does not steal Escape during normal use.
    PREFERRED = "ESCAPE"

    def __init__(self, portal, on_stop):
        self._portal = portal
        self._on_stop = on_stop
        self._session = None
        self.trigger = ""
        self.detail = ""

    @property
    def bound(self) -> bool:
        return bool(self._session)

    def handle_signal(self, message) -> None:
        """Called from the portal's message handler for every signal."""
        if (self._session and message.interface == self._IFACE
                and message.member == "Activated"
                and message.body and message.body[0] == self._session
                and len(message.body) > 1 and message.body[1] == self.SHORTCUT):
            try:
                self._on_stop()
            except Exception:
                pass

    async def bind(self) -> None:
        """Ask for the shortcut. Failure is not fatal: on a desktop without
        this portal, screen control still works and Escape still stops it
        while Wynxq is focused."""
        from dbus_next import Variant
        portal = self._portal
        self._session = None
        self.trigger = ""
        try:
            if await portal._version(self._IFACE) < 1:
                self.detail = "This desktop has no global shortcut portal."
                return
            created = await portal._request(
                self._IFACE, "CreateSession", "a{sv}", [],
                {"session_handle_token": Variant("s", "wynxq_" + uuid.uuid4().hex)}, timeout=30)
            session = created["session_handle"]
            bound = await portal._request(
                self._IFACE, "BindShortcuts", "oa(sa{sv})sa{sv}",
                [session, [(self.SHORTCUT, {
                    "description": Variant("s", "Stop Wynxq acting on your screen"),
                    "preferred_trigger": Variant("s", self.PREFERRED)})], ""],
                {}, timeout=60)
            self._session = session
            for shortcut in bound.get("shortcuts") or []:
                if shortcut and shortcut[0] == self.SHORTCUT:
                    self.trigger = str((shortcut[1] or {}).get("trigger_description", "") or "")
            self.detail = ("Emergency stop: " + self.trigger if self.trigger
                           else "Emergency stop is bound; your desktop settings show the key.")
        except Exception as exc:
            self._session = None
            self.detail = f"No global stop shortcut: {str(exc)[:120]}"

    async def release(self) -> None:
        session, self._session = self._session, None
        self.trigger = ""
        self.detail = ""
        if session:
            try:
                await self._portal._call("org.freedesktop.portal.Session", "Close", path=session)
            except Exception:
                pass


class _PortalBackend:
    name = "Wayland / Desktop portal"
    detail = "Connected through the desktop portal. Screenshot permission is managed separately by your desktop."
    _DEST = "org.freedesktop.portal.Desktop"
    _PATH = "/org/freedesktop/portal/desktop"
    _REMOTE = "org.freedesktop.portal.RemoteDesktop"
    _CAST = "org.freedesktop.portal.ScreenCast"
    _SHOT = "org.freedesktop.portal.Screenshot"
    _REQUEST = "org.freedesktop.portal.Request"
    _SESSION = "org.freedesktop.portal.Session"

    # Permissions persist until the user revokes them in their desktop
    # settings, which is what stops Wynxq asking on every launch.
    _PERSIST_UNTIL_REVOKED = 2

    def __init__(self, monitor_layout, tokens=None):
        self.available = all(importlib.util.find_spec(p) is not None for p in ("dbus_next", "PIL"))
        self.unavailable_reason = "Install the app dependencies (dbus-next and Pillow) for Wayland control."
        self.connected = False
        self.layout = monitor_layout
        self.tokens = tokens if tokens is not None else SessionTokens()
        self.restored = False
        self.on_stop = None            # Set by the controller before connect().
        self.stop_shortcut = None
        self._loop = None
        self._thread = None
        self._bus = None
        self._session = None
        self._stream = None
        self._streams = []
        self._logical_size = None
        self._origin = (0, 0)
        self._pixel_size = None
        self._requests = {}
        self._early = {}
        self._held_keys = set()
        self._held_buttons = set()

    def _ensure_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, name="wynxq-desktop-portal", daemon=True)
            self._thread.start()

    def _run(self, coroutine, cancel=None, timeout=35):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        deadline = time.monotonic() + timeout
        try:
            while True:
                _check(cancel)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DesktopError("The desktop portal did not respond in time.")
                try:
                    return future.result(timeout=min(0.05, remaining))
                except concurrent.futures.TimeoutError:
                    continue
        except BaseException:
            future.cancel()
            raise

    async def _init_bus(self):
        if self._bus is not None:
            return
        from dbus_next.aio import MessageBus
        from dbus_next import Message
        self._bus = await MessageBus().connect()
        self._bus.add_message_handler(self._signal)
        reply = await self._bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                           interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                           body=[f"type='signal',sender='{self._DEST}',path_namespace='{self._PATH}'"]))
        self._check_reply(reply)

    @staticmethod
    def _unwrap(value):
        if hasattr(value, "value"):
            return _PortalBackend._unwrap(value.value)
        if isinstance(value, dict):
            return {k: _PortalBackend._unwrap(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [_PortalBackend._unwrap(v) for v in value]
        return value

    def _signal(self, message):
        from dbus_next import MessageType
        if message.message_type != MessageType.SIGNAL:
            return
        if self.stop_shortcut is not None:
            self.stop_shortcut.handle_signal(message)
        if message.interface == self._SESSION and message.member == "Closed" and message.path == self._session:
            self.connected = False
            self._session = None
            self._streams = []
            self._pixel_size = None
        if message.interface == self._REQUEST and message.member == "Response":
            future = self._requests.get(message.path)
            if future is not None and not future.done():
                future.set_result(message.body)
            elif len(self._early) < 32:
                self._early[message.path] = message.body

    @staticmethod
    def _check_reply(reply):
        from dbus_next import MessageType
        if reply is None or reply.message_type == MessageType.ERROR:
            detail = ": ".join(str(item) for item in reply.body) if reply else "No reply"
            raise DesktopError(f"Desktop portal: {detail[:400]}")
        return reply.body

    async def _version(self, interface) -> int:
        """Portal interface version, so optional options are only sent where
        they are understood. An unreadable version reads as the base one."""
        from dbus_next import Message
        try:
            reply = await asyncio.wait_for(self._bus.call(Message(
                destination=self._DEST, path=self._PATH,
                interface="org.freedesktop.DBus.Properties", member="Get",
                signature="ss", body=[interface, "version"])), 10)
            return int(self._unwrap(self._check_reply(reply)[0]))
        except Exception:
            return 1

    async def _call(self, interface, member, signature="", body=None, path=None):
        from dbus_next import Message
        reply = await asyncio.wait_for(self._bus.call(Message(destination=self._DEST, path=path or self._PATH,
                            interface=interface, member=member, signature=signature, body=body or [])), 15)
        return self._check_reply(reply)

    async def _request(self, interface, member, signature, prefix, options, timeout=120):
        from dbus_next import Variant
        token = "wynxq_" + uuid.uuid4().hex
        options = {**options, "handle_token": Variant("s", token)}
        sender = self._bus.unique_name.lstrip(":").replace(".", "_")
        predicted = f"{self._PATH}/request/{sender}/{token}"
        future = asyncio.get_running_loop().create_future()
        self._requests[predicted] = future  # Subscribe BEFORE issuing the method.
        actual = predicted
        try:
            returned = await self._call(interface, member, signature, [*prefix, options])
            actual = returned[0]
            if actual != predicted:
                self._requests[actual] = future
                if actual in self._early and not future.done():
                    future.set_result(self._early.pop(actual))
            response, result = await asyncio.wait_for(future, timeout)
            if response != 0:
                raise DesktopError("Desktop permission was cancelled." if response == 1 else "The desktop portal denied this request.")
            return self._unwrap(result)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            try:
                await self._call(self._REQUEST, "Close", path=actual)
            except Exception:
                pass
            raise
        finally:
            self._requests.pop(predicted, None)
            self._requests.pop(actual, None)
            self._early.pop(actual, None)

    def connect(self):
        if not self.layout:
            raise DesktopError("Wayland did not report any monitors. Restart Wynxq inside the graphical session.")
        self._run(self._connect(), timeout=135)

    async def _connect(self):
        from dbus_next import Variant
        await self._init_bus()
        remembered = self.tokens.load()
        self.restored = False
        try:
            created = await self._request(self._REMOTE, "CreateSession", "a{sv}", [],
                                          {"session_handle_token": Variant("s", "wynxq_" + uuid.uuid4().hex)})
            self._session = created["session_handle"]
            devices = {"types": Variant("u", 3)}
            # Session persistence arrived in version 2 of the interface; older
            # portals reject nothing, they simply prompt as they always did.
            if await self._version(self._REMOTE) >= 2:
                devices["persist_mode"] = Variant("u", self._PERSIST_UNTIL_REVOKED)
                if remembered:
                    devices["restore_token"] = Variant("s", remembered)
            await self._request(self._REMOTE, "SelectDevices", "oa{sv}", [self._session], devices)
            await self._request(self._CAST, "SelectSources", "oa{sv}", [self._session],
                                {"types": Variant("u", 1), "multiple": Variant("b", len(self.layout) > 1)})
            result = await self._request(self._REMOTE, "Start", "osa{sv}", [self._session, ""], {})
            # The token is single use: whatever comes back replaces what we
            # sent, and an absent one means the user declined to persist.
            issued = str(result.get("restore_token", "") or "")
            self.tokens.save(issued)
            self.restored = bool(remembered and issued)
            if result.get("devices", 0) & 3 != 3:
                raise DesktopError("Allow both keyboard and pointer access in the desktop permission dialog.")
            streams = result.get("streams", [])
            if len(streams) != len(self.layout):
                if len(self.layout) > 1:
                    raise DesktopError("Select every monitor in the desktop sharing dialog so Wynxq can map screen coordinates safely.")
                raise DesktopError("Select exactly one monitor in the desktop sharing dialog.")
            self._streams = self._map_streams(streams)
            self._stream = self._streams[0]["stream"]
            min_x = min(m["x"] for m in self.layout)
            min_y = min(m["y"] for m in self.layout)
            max_x = max(m["x"] + m["width"] for m in self.layout)
            max_y = max(m["y"] + m["height"] for m in self.layout)
            self._origin = (min_x, min_y)
            self._logical_size = (max_x - min_x, max_y - min_y)
            self._pixel_size = None
            self.connected = True
        except BaseException:
            # A token the portal would not restore is worse than none: keep it
            # and every future launch fails the same way. Drop it so the next
            # attempt asks the user cleanly.
            if remembered:
                self.tokens.clear()
            await self._disconnect()
            raise

    def begin_control(self):
        if not self.connected:
            raise DesktopError("The desktop sharing session ended. Reconnect to continue.")
        if self.on_stop is not None and self.stop_shortcut is None:
            shortcut = GlobalStop(self, self.on_stop)
            self._run(shortcut.bind(), timeout=80)
            self.stop_shortcut = shortcut

    def release_all(self):
        if not self.connected:
            self._held_keys.clear()
            self._held_buttons.clear()
            return
        for button in list(self._held_buttons):
            try:
                self.button(button, False, None)
            except Exception:
                pass
        for sym in list(self._held_keys):
            try:
                self.key(sym, False, None)
            except Exception:
                pass

    def end_control(self):
        self.release_all()
        shortcut, self.stop_shortcut = self.stop_shortcut, None
        if shortcut is not None and self._loop:
            self._run(shortcut.release(), timeout=20)

    def disconnect(self):
        if self.connected:
            self.end_control()
        self.connected = False
        if self._loop:
            self._run(self._disconnect(), timeout=20)

    async def _disconnect(self):
        shortcut, self.stop_shortcut = self.stop_shortcut, None
        if shortcut is not None:
            await shortcut.release()
        session, self._session = self._session, None
        self.connected = False
        self._pixel_size = None
        self._streams = []
        if session and self._bus:
            try:
                await self._call(self._SESSION, "Close", path=session)
            except Exception:
                pass

    def screenshot(self, cancel):
        return self._run(self._screenshot(), cancel, timeout=125)

    def capture(self, kind, cancel):
        # The Screenshot portal is independent of RemoteDesktop, so context
        # captures work without ever asking for pointer or keyboard control.
        picture = self._run(self._capture_only(), cancel, timeout=125)
        detail = "Full screen"
        if kind == "window":
            detail = "Full screen (Wayland has no per-window capture)"
        return picture, detail

    async def _capture_only(self):
        from dbus_next import Variant
        from PIL import Image
        await self._init_bus()
        result = await self._request(self._SHOT, "Screenshot", "sa{sv}", [""],
                                     {"interactive": Variant("b", False), "modal": Variant("b", False)})
        uri = urlparse(result.get("uri", ""))
        if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
            raise DesktopError("The portal did not return a local screenshot file.")
        path = Path(unquote(uri.path))
        if path.stat().st_size > 80 * 1024 * 1024:
            raise DesktopError("Screenshot exceeds the 80 MB limit.")
        with Image.open(path) as raw:
            raw.load()
            return raw.convert("RGB")

    def active_window(self):
        # Wayland compositors do not expose the focused window to applications.
        return {"title": "", "detail": "Wayland does not expose window titles"}

    async def _screenshot(self):
        from dbus_next import Variant
        from PIL import Image
        self._pixel_size = None  # A failed capture must invalidate old coordinates.
        result = await self._request(self._SHOT, "Screenshot", "sa{sv}", [""],
                                     {"interactive": Variant("b", False), "modal": Variant("b", False),
                                      "target": Variant("u", 1)})
        uri = urlparse(result.get("uri", ""))
        if uri.scheme != "file" or uri.netloc not in ("", "localhost"):
            raise DesktopError("The portal did not return a local screenshot file.")
        path = Path(unquote(uri.path))
        if path.stat().st_size > 80 * 1024 * 1024:
            raise DesktopError("Screenshot exceeds the 80 MB limit.")
        with Image.open(path) as raw:
            raw.load()
            picture = raw.convert("RGB")
        width, height = self._logical_size
        sx, sy = picture.width / width, picture.height / height
        if abs(sx - sy) > max(sx, sy) * 0.025:
            raise DesktopError("Screenshot geometry does not match the shared monitor. Reconnect desktop control with a single display.")
        self._pixel_size = picture.size
        return picture

    def _map_streams(self, streams):
        """Match portal streams to Qt monitor rectangles.

        ``position`` is optional in the ScreenCast portal metadata.  Prefer it
        when present, then use a unique size match, and finally pair unresolved
        streams with the compositor's stable stream order.  The final fallback
        is what makes two identical monitors usable on portals that omit
        positions (KDE commonly does this); it still requires one stream per
        monitor and never invents coordinates.
        """
        entries = []
        for index, (stream, properties) in enumerate(streams):
            properties = properties or {}
            position = properties.get("position")
            size = properties.get("size") or properties.get("logical_size")
            if position is not None and (not isinstance(position, (list, tuple)) or len(position) != 2):
                raise DesktopError("The desktop portal returned invalid monitor positions.")
            if size is not None and (not isinstance(size, (list, tuple)) or len(size) != 2
                                     or any(not isinstance(v, (int, float)) or v <= 0 for v in size)):
                raise DesktopError("The desktop portal returned invalid monitor dimensions.")
            entries.append({"index": index, "stream": stream, "position": position, "size": size})

        unused = sorted(self.layout, key=lambda monitor: (monitor["x"], monitor["y"]))
        assigned = {}

        # Explicit positions are authoritative and are resolved before any
        # fallback, so a position-bearing stream can never be consumed by an
        # earlier position-less stream.
        pending = []
        for entry in entries:
            position = entry["position"]
            if position is None:
                pending.append(entry)
                continue
            candidates = [m for m in unused if m["x"] == position[0] and m["y"] == position[1]]
            if len(candidates) != 1:
                raise DesktopError("The desktop portal returned a monitor position that does not match this desktop.")
            assigned[entry["index"]] = (entry, candidates[0])
            unused.remove(candidates[0])

        # A unique stream size is enough to identify monitors with different
        # resolutions, even when the optional position field is absent.
        unresolved = []
        for entry in pending:
            size = entry["size"]
            candidates = [m for m in unused if size is not None and
                          m["width"] == size[0] and m["height"] == size[1]]
            if len(candidates) == 1:
                assigned[entry["index"]] = (entry, candidates[0])
                unused.remove(candidates[0])
            else:
                unresolved.append(entry)

        if unresolved:
            if len(unresolved) != len(unused):
                raise DesktopError("The desktop portal did not return all selected monitors.")
            # No position or unique size was available. Pair in the stream
            # order returned by the compositor and document that it is a
            # deterministic fallback rather than an absolute guarantee.
            for entry, monitor in zip(unresolved, unused):
                size = entry["size"] or [monitor["width"], monitor["height"]]
                if size[0] != monitor["width"] or size[1] != monitor["height"]:
                    raise DesktopError("The desktop portal returned monitor dimensions that do not match this desktop.")
                assigned[entry["index"]] = (entry, monitor)
            unused = []

        mapped = []
        for index in range(len(entries)):
            entry, monitor = assigned[index]
            size = entry["size"] or [monitor["width"], monitor["height"]]
            mapped.append({"stream": entry["stream"], "x": monitor["x"], "y": monitor["y"],
                           "width": monitor["width"], "height": monitor["height"],
                           "stream_width": float(size[0]), "stream_height": float(size[1])})
        if unused:
            raise DesktopError("The desktop portal did not return all selected monitors.")
        return mapped

    def _notify(self, member, signature, values, cancel):
        _check(cancel)
        if not self.connected or not self._session:
            raise DesktopError("The desktop sharing session ended. Reconnect to continue.")
        return self._run(self._call(self._REMOTE, member, "oa{sv}" + signature,
                                   [self._session, {}, *values]), cancel, timeout=18)

    def move(self, x, y, cancel):
        if not self._pixel_size or not self._logical_size:
            raise DesktopError("Take a screenshot before moving the pointer.")
        px, py = self._pixel_size
        logical_x = self._origin[0] + x * self._logical_size[0] / px
        logical_y = self._origin[1] + y * self._logical_size[1] / py
        if not self._streams:
            lx = x * self._logical_size[0] / px
            ly = y * self._logical_size[1] / py
            stream = self._stream
        else:
            selected = next((m for m in self._streams
                             if m["x"] <= logical_x < m["x"] + m["width"] and
                                m["y"] <= logical_y < m["y"] + m["height"]), None)
            if selected is None:
                raise DesktopError("The pointer coordinate is outside the shared monitors.")
            stream = selected["stream"]
            lx = (logical_x - selected["x"]) * selected["stream_width"] / selected["width"]
            ly = (logical_y - selected["y"]) * selected["stream_height"] / selected["height"]
        self._notify("NotifyPointerMotionAbsolute", "udd", [stream, lx, ly], cancel)

    def button(self, button, down, cancel):
        code = {"left": 0x110, "right": 0x111, "middle": 0x112}[button]
        self._notify("NotifyPointerButton", "iu", [code, int(down)], cancel)
        if down:
            self._held_buttons.add(button)
        else:
            self._held_buttons.discard(button)

    def validate_keys(self, syms):
        pass  # The compositor resolves XKB/Unicode keysyms.

    def key(self, sym, down, cancel):
        self._notify("NotifyKeyboardKeysym", "iu", [sym, int(down)], cancel)
        if down:
            self._held_keys.add(sym)
        else:
            self._held_keys.discard(sym)

    def scroll(self, dx, dy, cancel):
        if dy:
            self._notify("NotifyPointerAxisDiscrete", "ui", [0, dy], cancel)
        if dx:
            self._notify("NotifyPointerAxisDiscrete", "ui", [1, dx], cancel)
