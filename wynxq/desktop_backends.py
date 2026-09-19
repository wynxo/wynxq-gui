"""Platform backends for desktop capture and input control.

The public DesktopController chooses and coordinates these implementations.
Keeping platform code here makes the facade small and lets X11/Wayland evolve
without turning desktop orchestration into a platform-specific monolith.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import os
from pathlib import Path
import threading
import time
from urllib.parse import unquote, urlparse
import uuid

from .desktop_common import DesktopError, SessionTokens, _KEYSYMS, _check


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


__all__ = ["GlobalStop", "X11GlobalStop", "_PortalBackend", "_X11Backend"]
