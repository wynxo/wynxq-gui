"""No test here captures or sends input to the user's desktop."""
import asyncio
import base64
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from wynxq.desktop import (DesktopController, DesktopError, DesktopCancelled,
                           _PortalBackend, _X11Backend, _application_inventory, _keysym)


class FakeBackend:
    name = "test"
    available = True
    unavailable_reason = ""
    detail = "Connected for testing"

    def __init__(self):
        self.connected = False
        self.events = []
        self.cancel_on_move = None
        self.cancel_on_key = None

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def move(self, x, y, cancel):
        self.events.append(("move", x, y))
        if self.cancel_on_move:
            self.cancel_on_move.set()

    def button(self, button, down, cancel):
        self.events.append(("button", button, down))

    def validate_keys(self, syms):
        pass

    def key(self, sym, down, cancel):
        self.events.append(("key", sym, down))
        if down and self.cancel_on_key:
            self.cancel_on_key.set()

    picture_size = (640, 480)

    def screenshot(self, cancel):
        from PIL import Image
        return Image.new("RGB", self.picture_size, "#112233")

    def scroll(self, dx, dy, cancel):
        self.events.append(("scroll", dx, dy))


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.desktop = DesktopController(backend=self.backend)
        self.cancel = threading.Event()

    def enabled(self):
        self.desktop.connect()
        self.desktop._size = (640, 480)

    def test_control_requires_explicit_connection(self):
        self.assertFalse(self.desktop.status()["connected"])
        with self.assertRaisesRegex(DesktopError, "off"):
            self.desktop.execute("press_key", {"keys": ["enter"]}, self.cancel)
        self.assertEqual(self.backend.events, [])

    def test_screenshot_returns_real_png_and_dimensions(self):
        self.desktop.connect()
        result = self.desktop.execute("screenshot", {}, self.cancel)
        self.assertEqual((result["width"], result["height"]), (640, 480))
        self.assertTrue(base64.b64decode(result["image"]).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(self.desktop._size, (640, 480))

    def test_input_rejects_unknown_and_outside_coordinates(self):
        self.enabled()
        for args in ({"x": -1, "y": 2}, {"x": 640, "y": 2},
                     {"x": float("nan"), "y": 2}, {"x": True, "y": 2}):
            with self.subTest(args=args), self.assertRaises(DesktopError):
                self.desktop.execute("click", args, self.cancel)
        self.assertEqual(self.backend.events, [])
        self.desktop._size = None
        with self.assertRaisesRegex(DesktopError, "screenshot"):
            self.desktop.execute("move_pointer", {"x": 2, "y": 3}, self.cancel)

    def test_click_releases_button_even_when_stopped(self):
        self.enabled()
        original = self.backend.button
        def stop_on_down(button, down, cancel):
            original(button, down, cancel)
            if down:
                self.cancel.set()
        self.backend.button = stop_on_down
        with self.assertRaises(DesktopCancelled):
            self.desktop.execute("click", {"x": 2, "y": 3}, self.cancel)
        self.assertEqual(self.backend.events[-1], ("button", "left", False))

    def test_cancelled_chord_releases_every_pressed_key(self):
        self.enabled()
        self.backend.cancel_on_key = self.cancel
        with self.assertRaises(DesktopCancelled):
            self.desktop.execute("press_key", {"keys": ["ctrl", "a"]}, self.cancel)
        self.assertEqual(self.backend.events, [("key", _keysym("ctrl"), True),
                                               ("key", _keysym("ctrl"), False)])

    def test_drag_validates_all_points_before_input(self):
        self.enabled()
        with self.assertRaises(DesktopError):
            self.desktop.execute("drag", {"points": [[1, 2], [10, 20], [9999, 5]]}, self.cancel)
        self.assertEqual(self.backend.events, [])

    def test_two_point_drag_interpolates_and_releases(self):
        self.enabled()
        with patch("wynxq.desktop._pause"):
            self.desktop.execute("drag", {"points": [[0, 0], [60, 60]], "duration": .1}, self.cancel)
        moves = [event for event in self.backend.events if event[0] == "move"]
        self.assertGreater(len(moves), 2)
        self.assertEqual(moves[-1], ("move", 60.0, 60.0))
        self.assertEqual(self.backend.events[-1], ("button", "left", False))

    def test_cancel_before_action_produces_no_events(self):
        self.enabled()
        self.cancel.set()
        with self.assertRaises(DesktopCancelled):
            self.desktop.execute("click", {"x": 2, "y": 3}, self.cancel)
        self.assertEqual(self.backend.events, [])

    def test_oversized_actions_and_duplicate_chords_are_rejected(self):
        self.enabled()
        for name, args in [("wait", {"seconds": 11}), ("scroll", {"dy": 31}),
                           ("type_text", {"text": "a" * 4001}),
                           ("press_key", {"keys": ["ctrl", "ctrl"]}),
                           ("click", {"x": 1, "y": 2, "count": 1.5})]:
            with self.subTest(name=name), self.assertRaises(DesktopError):
                self.desktop.execute(name, args, self.cancel)
        self.assertEqual(self.backend.events, [])

    def test_launches_only_inventory_entry_without_screen_control_or_shell(self):
        self.assertFalse(self.desktop.status()["connected"])
        inventory = [{"id": "org.kde.kolourpaint.desktop", "name": "KolourPaint",
                      "description": "Paint", "path": "/usr/share/applications/org.kde.kolourpaint.desktop"}]
        with patch("wynxq.desktop._application_inventory", return_value=inventory), \
             patch("wynxq.desktop.shutil.which", return_value="/usr/bin/gio"), \
             patch("wynxq.desktop.subprocess.run") as run:
            run.return_value.returncode = 0
            self.desktop.execute("open_app", {"app": "KolourPaint"}, self.cancel)
            self.assertEqual(run.call_args.args[0], ["/usr/bin/gio", "launch", inventory[0]["path"]])
            self.assertFalse(run.call_args.kwargs.get("shell", False))
            run.reset_mock()
            with self.assertRaises(DesktopError):
                self.desktop.execute("open_app", {"app": "KolourPaint; touch /tmp/test"}, self.cancel)
            run.assert_not_called()

    def test_list_apps_is_read_only_and_hides_internal_paths(self):
        with patch("wynxq.desktop._application_inventory", return_value=[{"id": "a", "name": "A", "path": "/local/file"}]):
            self.assertEqual(self.desktop.execute("list_apps", {}), {"ok": True, "apps": [{"id": "a", "name": "A"}]})
        self.assertFalse(self.desktop.status()["connected"])

    def test_disconnect_revokes_actions(self):
        self.enabled()
        self.desktop.disconnect()
        with self.assertRaises(DesktopError):
            self.desktop.execute("press_key", {"keys": ["a"]})

    def test_inventory_honors_hidden_user_override(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for directory in (root / "user/applications", root / "system/applications"):
                directory.mkdir(parents=True)
            (root / "system/applications/paint.desktop").write_text("[Desktop Entry]\nType=Application\nName=Paint\nExec=paint\n")
            (root / "user/applications/paint.desktop").write_text("[Desktop Entry]\nType=Application\nName=Paint\nHidden=true\n")
            with patch.dict("os.environ", {"XDG_DATA_HOME": str(root / "user"), "XDG_DATA_DIRS": str(root / "system")}):
                self.assertEqual(_application_inventory(), [])


class X11Tests(unittest.TestCase):
    def test_shifted_character_releases_both_key_and_shift(self):
        from Xlib import X
        backend = _X11Backend()
        backend._display = Mock()
        backend._display.keysym_to_keycodes.return_value = [(38, 1)]
        backend._display.keysym_to_keycode.return_value = 50
        with patch("Xlib.ext.xtest.fake_input") as send:
            backend.key(ord("A"), True, None)
            backend.key(ord("A"), False, None)
        self.assertEqual([(call.args[1], call.args[2]) for call in send.call_args_list],
                         [(X.KeyPress, 50), (X.KeyPress, 38), (X.KeyRelease, 38), (X.KeyRelease, 50)])
        self.assertEqual(backend._held, {})

    def test_unmapped_character_fails_before_any_input(self):
        backend = _X11Backend()
        backend._display = Mock()
        backend._display.keysym_to_keycodes.return_value = []
        with patch("Xlib.ext.xtest.fake_input") as send, self.assertRaisesRegex(DesktopError, "keyboard layout"):
            backend.validate_keys([_keysym("\u03bb")])
        send.assert_not_called()

    def test_scroll_down_sends_paired_button_five_events(self):
        from Xlib import X
        backend = _X11Backend()
        backend._display = Mock()
        with patch("Xlib.ext.xtest.fake_input") as send:
            backend.scroll(0, 2, threading.Event())
        self.assertEqual([(call.args[1], call.args[2]) for call in send.call_args_list],
                         [(X.ButtonPress, 5), (X.ButtonRelease, 5)] * 2)


class PortalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.portal = _PortalBackend([{"x": 0, "y": 0, "width": 1920, "height": 1080}])

    async def test_request_catches_response_before_method_reply(self):
        from dbus_next import Message, Variant
        self.portal._bus = Mock(unique_name=":1.42")
        async def call(interface, member, signature, body):
            token = body[-1]["handle_token"].value
            path = f"{self.portal._PATH}/request/1_42/{token}"
            signal = Message.new_signal(path, self.portal._REQUEST, "Response", "ua{sv}", [0, {"value": Variant("s", "yes")}])
            self.portal._signal(signal)
            return [path]
        self.portal._call = call
        result = await self.portal._request(self.portal._REMOTE, "CreateSession", "a{sv}", [], {})
        self.assertEqual(result, {"value": "yes"})
        self.assertFalse(self.portal._requests)

    async def test_request_supports_legacy_unexpected_path(self):
        from dbus_next import Message
        self.portal._bus = Mock(unique_name=":1.42")
        actual = self.portal._PATH + "/request/legacy"
        async def call(*args, **kwargs):
            self.portal._signal(Message.new_signal(actual, self.portal._REQUEST, "Response", "ua{sv}", [0, {}]))
            return [actual]
        self.portal._call = call
        self.assertEqual(await self.portal._request(self.portal._REMOTE, "Start", "a{sv}", [], {}), {})
        self.assertFalse(self.portal._early)

    async def test_cancelled_request_closes_portal_dialog(self):
        self.portal._bus = Mock(unique_name=":1.42")
        started = asyncio.Event()
        closed = []
        async def call(interface, member, signature="", body=None, path=None):
            if member == "Close":
                closed.append(path)
                return []
            token = body[-1]["handle_token"].value
            started.set()
            return [f"{self.portal._PATH}/request/1_42/{token}"]
        self.portal._call = call
        task = asyncio.create_task(self.portal._request(self.portal._REMOTE, "Start", "a{sv}", [], {}))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(closed), 1)
        self.assertFalse(self.portal._requests)

    async def test_connection_requests_keyboard_pointer_and_one_monitor(self):
        self.portal._init_bus = AsyncMock()
        self.portal._request = AsyncMock(side_effect=[{"session_handle": "/session/test"}, {}, {},
                                                       {"devices": 3, "streams": [[91, {"size": [1920, 1080]}]]}])
        await self.portal._connect()
        self.assertTrue(self.portal.connected)
        calls = self.portal._request.call_args_list
        self.assertEqual([c.args[1] for c in calls], ["CreateSession", "SelectDevices", "SelectSources", "Start"])
        self.assertEqual(calls[1].args[4]["types"].value, 3)
        self.assertFalse(calls[2].args[4]["multiple"].value)
        self.assertEqual(self.portal._stream, 91)

    async def test_denied_device_closes_created_session(self):
        self.portal._init_bus = AsyncMock()
        self.portal._bus = Mock()
        self.portal._call = AsyncMock()
        self.portal._request = AsyncMock(side_effect=[{"session_handle": "/session/test"}, {}, {}, {"devices": 1}])
        with self.assertRaisesRegex(DesktopError, "both keyboard"):
            await self.portal._connect()
        self.assertFalse(self.portal.connected)
        self.portal._call.assert_awaited_once_with(self.portal._SESSION, "Close", path="/session/test")

    async def test_portal_session_closed_revokes_access(self):
        from dbus_next import Message
        self.portal.connected = True
        self.portal._session = "/session/test"
        self.portal._signal(Message.new_signal("/session/test", self.portal._SESSION, "Closed", "a{sv}", [{}]))
        self.assertFalse(self.portal.connected)
        self.assertIsNone(self.portal._session)

    async def test_screenshot_scales_pixels_to_logical_coordinates(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "shot.png"
            Image.new("RGB", (3840, 2160)).save(path)
            self.portal._logical_size = (1920, 1080)
            self.portal._request = AsyncMock(return_value={"uri": path.as_uri()})
            image = await self.portal._screenshot()
            self.assertEqual(image.size, (3840, 2160))
            self.portal._stream = 91
            self.portal._notify = Mock()
            self.portal.move(2000, 1000, None)
            self.portal._notify.assert_called_once_with("NotifyPointerMotionAbsolute", "udd", [91, 1000.0, 500.0], None)

    async def test_ambiguous_screenshot_geometry_is_rejected(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "shot.png"
            Image.new("RGB", (3840, 1080)).save(path)
            self.portal._logical_size = (1920, 1080)
            self.portal._request = AsyncMock(return_value={"uri": path.as_uri()})
            with self.assertRaisesRegex(DesktopError, "geometry"):
                await self.portal._screenshot()
            self.assertIsNone(self.portal._pixel_size)

    async def test_remote_screenshot_uri_is_rejected(self):
        self.portal._request = AsyncMock(return_value={"uri": "https://example.test/image.png"})
        with self.assertRaisesRegex(DesktopError, "local screenshot"):
            await self.portal._screenshot()

    async def test_multimonitor_streams_map_absolute_coordinates(self):
        portal = _PortalBackend([
            {"x": 0, "y": 0, "width": 1920, "height": 1080},
            {"x": 1920, "y": 0, "width": 1920, "height": 1080},
        ])
        portal._init_bus = AsyncMock()
        portal._request = AsyncMock(side_effect=[
            {"session_handle": "/session/test"}, {}, {},
            {"devices": 3, "streams": [
                [91, {"position": [0, 0], "size": [1920, 1080]}],
                [92, {"position": [1920, 0], "size": [1920, 1080]}],
            ]},
        ])
        await portal._connect()
        select = portal._request.call_args_list[2]
        self.assertTrue(select.args[4]["multiple"].value)
        portal._pixel_size = (3840, 1080)
        portal._notify = Mock()
        portal.move(2500, 500, None)
        portal._notify.assert_called_once_with("NotifyPointerMotionAbsolute", "udd", [92, 580.0, 500.0], None)

    async def test_multimonitor_streams_without_positions_use_stable_order(self):
        portal = _PortalBackend([
            {"x": 0, "y": 0, "width": 1920, "height": 1080},
            {"x": 1920, "y": 0, "width": 1920, "height": 1080},
        ])
        mapped = portal._map_streams([
            [101, {"size": [1920, 1080]}],
            [102, {"size": [1920, 1080]}],
        ])
        self.assertEqual([item["x"] for item in mapped], [0, 1920])
        self.assertEqual([item["stream"] for item in mapped], [101, 102])


if __name__ == "__main__":
    unittest.main()


class WaylandSessionTests(unittest.IsolatedAsyncioTestCase):
    """The portal handshake, driven against a recorded fake rather than a real
    compositor. These assert the options Wynxq sends and what it does with the
    replies; they cannot prove any particular desktop honours them."""

    def _portal(self, tokens=None, version=2, start=None):
        from wynxq.desktop import SessionTokens
        portal = _PortalBackend([{"x": 0, "y": 0, "width": 1920, "height": 1080}],
                                tokens=tokens if tokens is not None else SessionTokens())
        portal.calls = []
        portal._init_bus = AsyncMock()
        portal._version = AsyncMock(return_value=version)
        replies = {
            "CreateSession": {"session_handle": "/s/1"},
            "SelectDevices": {},
            "SelectSources": {},
            "Start": start if start is not None else {
                "devices": 3, "restore_token": "fresh-token",
                "streams": [(7, {"position": [0, 0], "size": [1920, 1080]})],
            },
        }

        async def request(interface, member, signature, prefix, options, timeout=120):
            portal.calls.append((member, options))
            return replies[member]

        portal._request = request
        return portal

    async def test_a_remembered_session_is_offered_back_to_the_portal(self):
        from wynxq.desktop import SessionTokens
        tokens = SessionTokens()
        tokens.save("saved-token")
        portal = self._portal(tokens=tokens)
        await portal._connect()

        devices = dict(portal.calls)["SelectDevices"]
        self.assertEqual(devices["restore_token"].value, "saved-token")
        # 2 is "persist until the user revokes it".
        self.assertEqual(devices["persist_mode"].value, 2)
        # The token is single use, so the new one replaces it.
        self.assertEqual(tokens.load(), "fresh-token")
        self.assertTrue(portal.restored)

    async def test_a_portal_without_persistence_is_not_sent_the_options(self):
        portal = self._portal(version=1)
        await portal._connect()
        devices = dict(portal.calls)["SelectDevices"]
        self.assertNotIn("persist_mode", devices)
        self.assertNotIn("restore_token", devices)

    async def test_declining_to_persist_leaves_nothing_stored(self):
        from wynxq.desktop import SessionTokens
        tokens = SessionTokens()
        portal = self._portal(tokens=tokens, start={
            "devices": 3, "streams": [(7, {"position": [0, 0], "size": [1920, 1080]})]})
        await portal._connect()
        self.assertEqual(tokens.load(), "")
        self.assertFalse(portal.restored)

    async def test_a_token_the_portal_will_not_restore_is_thrown_away(self):
        """Keeping a rejected token would fail the same way on every launch."""
        from wynxq.desktop import SessionTokens
        tokens = SessionTokens()
        tokens.save("stale-token")
        portal = self._portal(tokens=tokens, start={"devices": 1, "streams": []})
        with self.assertRaises(DesktopError):
            await portal._connect()
        self.assertEqual(tokens.load(), "")


class GlobalStopTests(unittest.IsolatedAsyncioTestCase):
    """The stop key that has to work while another window has focus."""

    def _shortcut(self, on_stop, version=2, bound=None, fail=False):
        from wynxq.desktop import GlobalStop
        portal = _PortalBackend([{"x": 0, "y": 0, "width": 1920, "height": 1080}])
        portal._version = AsyncMock(return_value=version)

        async def request(interface, member, signature, prefix, options, timeout=120):
            if fail:
                raise DesktopError("portal said no")
            if member == "CreateSession":
                return {"session_handle": "/shortcut/1"}
            return {"shortcuts": bound if bound is not None
                    else [("stop", {"trigger_description": "Ctrl+Alt+Esc"})]}

        portal._request = request
        return GlobalStop(portal, on_stop)

    async def test_the_desktop_decides_the_key_and_we_report_what_it_chose(self):
        stop = self._shortcut(lambda: None,
                              bound=[("stop", {"trigger_description": "Meta+Shift+X"})])
        await stop.bind()
        self.assertTrue(stop.bound)
        self.assertEqual(stop.trigger, "Meta+Shift+X")
        self.assertIn("Meta+Shift+X", stop.detail)

    async def test_pressing_it_stops_the_run(self):
        from dbus_next import Message
        fired = []
        stop = self._shortcut(lambda: fired.append(True))
        await stop.bind()
        stop.handle_signal(Message.new_signal(
            "/org/freedesktop/portal/desktop", stop._IFACE, "Activated",
            "osta{sv}", ["/shortcut/1", "stop", 0, {}]))
        self.assertEqual(fired, [True])

    async def test_another_session_or_another_shortcut_is_ignored(self):
        from dbus_next import Message
        fired = []
        stop = self._shortcut(lambda: fired.append(True))
        await stop.bind()
        for session, name in (("/other", "stop"), ("/shortcut/1", "something-else")):
            stop.handle_signal(Message.new_signal(
                "/org/freedesktop/portal/desktop", stop._IFACE, "Activated",
                "osta{sv}", [session, name, 0, {}]))
        self.assertEqual(fired, [])

    async def test_a_desktop_without_the_portal_still_runs(self):
        """Screen control must not depend on this; Escape in the window is
        still there when the shortcut cannot be bound."""
        for kwargs in ({"version": 0}, {"fail": True}):
            stop = self._shortcut(lambda: None, **kwargs)
            await stop.bind()
            self.assertFalse(stop.bound)
            self.assertTrue(stop.detail)


class PointerMotionTests(unittest.TestCase):
    """A pointer that teleports cannot be followed or interrupted."""

    def _controller(self):
        controller = DesktopController(backend=FakeBackend())
        controller.connect()
        controller._size = (1920, 1080)
        return controller

    def test_the_pointer_travels_to_its_target_and_lands_on_it(self):
        controller = self._controller()
        controller.execute("move_pointer", {"x": 100, "y": 100})
        controller.execute("move_pointer", {"x": 900, "y": 700})
        moves = [event for event in controller._backend.events if event[0] == "move"]
        self.assertGreater(len(moves), 5, "the pointer jumped instead of moving")
        self.assertEqual((round(moves[-1][1]), round(moves[-1][2])), (900, 700))
        # Monotonic travel: no overshoot past the target.
        self.assertTrue(all(100 <= event[1] <= 900 for event in moves[1:]))

    def test_a_short_hop_is_not_drawn_out(self):
        controller = self._controller()
        controller.execute("move_pointer", {"x": 100, "y": 100})
        before = len(controller._backend.events)
        controller.execute("move_pointer", {"x": 103, "y": 102})
        self.assertEqual(len(controller._backend.events) - before, 1)

    def test_stopping_mid_glide_leaves_the_pointer_where_it_stopped(self):
        controller = self._controller()
        controller.execute("move_pointer", {"x": 0, "y": 0})
        cancel = threading.Event()
        controller._backend.cancel_on_move = cancel
        with self.assertRaises(DesktopCancelled):
            controller.execute("move_pointer", {"x": 1900, "y": 1000}, cancel)
        moves = [event for event in controller._backend.events if event[0] == "move"]
        self.assertLess(moves[-1][1], 1900, "the glide ran to completion after a stop")

    def test_a_screenshot_of_the_same_screen_keeps_the_pointer(self):
        controller = self._controller()
        controller._backend.picture_size = (1920, 1080)
        controller.execute("screenshot", {})
        controller.execute("move_pointer", {"x": 900, "y": 700})
        controller.execute("screenshot", {})
        self.assertEqual(controller._pointer, (900, 700))

    def test_a_new_coordinate_space_forgets_where_the_pointer_was(self):
        """Gliding from a point measured in a different screen size would
        drag the cursor across the desktop from nowhere."""
        controller = self._controller()
        controller._backend.picture_size = (1920, 1080)
        controller.execute("screenshot", {})
        controller.execute("move_pointer", {"x": 900, "y": 700})
        self.assertIsNotNone(controller._pointer)

        controller._backend.picture_size = (1280, 720)
        controller.execute("screenshot", {})
        self.assertIsNone(controller._pointer)
