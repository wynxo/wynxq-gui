"""X11/XTEST desktop capture and input backend."""
from __future__ import annotations

import importlib.util
import os

from .desktop_common import DesktopError, _KEYSYMS, _check

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
