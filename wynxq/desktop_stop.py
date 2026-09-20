"""Emergency-stop integrations for X11 and Wayland portal sessions."""
from __future__ import annotations

import threading
import uuid

from .desktop_common import _KEYSYMS

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
