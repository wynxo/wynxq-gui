"""Wayland RemoteDesktop/ScreenCast/Screenshot portal backend."""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
from pathlib import Path
import threading
import time
from urllib.parse import unquote, urlparse
import uuid

from .desktop_common import DesktopError, SessionTokens, _check
from .desktop_stop import GlobalStop

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
            capture_size = properties.get("size")
            logical_size = properties.get("logical_size")
            if position is not None and (not isinstance(position, (list, tuple)) or len(position) != 2):
                raise DesktopError("The desktop portal returned invalid monitor positions.")
            for label, size in (("capture", capture_size), ("logical", logical_size)):
                if size is not None and (not isinstance(size, (list, tuple)) or len(size) != 2
                                         or any(not isinstance(v, (int, float)) or v <= 0 for v in size)):
                    raise DesktopError(f"The desktop portal returned invalid {label} monitor dimensions.")
            entries.append({"index": index, "stream": stream, "position": position,
                            "capture_size": capture_size, "logical_size": logical_size})

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

        # Qt screen geometry and RemoteDesktop absolute pointer coordinates are
        # logical pixels. Prefer the portal's explicit logical_size. The
        # ScreenCast "size" may instead be the physical/capture resolution
        # (for example 3840×2160 for a 1920×1080 screen at 200% scaling), so it
        # must never be used as the absolute input coordinate space.
        unresolved = []
        for entry in pending:
            logical = entry["logical_size"]
            fallback = entry["capture_size"] if logical is None else None
            match_size = logical or fallback
            candidates = [m for m in unused if match_size is not None and
                          m["width"] == match_size[0] and m["height"] == match_size[1]]
            if len(candidates) == 1:
                assigned[entry["index"]] = (entry, candidates[0])
                unused.remove(candidates[0])
            else:
                unresolved.append(entry)

        if unresolved:
            if len(unresolved) != len(unused):
                raise DesktopError("The desktop portal did not return all selected monitors.")
            # No position or unique logical size was available. Pair in the
            # compositor's stable stream order. A physical capture size may
            # legitimately differ from Qt's logical geometry under scaling.
            for entry, monitor in zip(unresolved, unused):
                logical = entry["logical_size"]
                if logical is not None and (
                        logical[0] != monitor["width"] or logical[1] != monitor["height"]):
                    raise DesktopError("The desktop portal returned logical monitor dimensions that do not match this desktop.")
                assigned[entry["index"]] = (entry, monitor)
            unused = []

        mapped = []
        for index in range(len(entries)):
            entry, monitor = assigned[index]
            logical = entry["logical_size"] or [monitor["width"], monitor["height"]]
            capture = entry["capture_size"]
            mapped.append({"stream": entry["stream"], "x": monitor["x"], "y": monitor["y"],
                           "width": monitor["width"], "height": monitor["height"],
                           "input_width": float(logical[0]), "input_height": float(logical[1]),
                           "capture_width": float(capture[0]) if capture is not None else 0.0,
                           "capture_height": float(capture[1]) if capture is not None else 0.0})
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
            lx = (logical_x - selected["x"]) * selected["input_width"] / selected["width"]
            ly = (logical_y - selected["y"]) * selected["input_height"] / selected["height"]
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
