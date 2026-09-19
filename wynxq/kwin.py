"""KWin integration used only to keep the desktop-control HUD visible on Plasma Wayland.

Wayland intentionally gives the compositor final say over stacking. Qt's
WindowStaysOnTopHint is still requested by QML, while this module adds a
best-effort KDE-specific promotion using KWin's scripting API. It never changes
or focuses arbitrary windows: the script matches Wynxq's two fixed HUD titles.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import tempfile
import threading
import uuid


_KWIN_SCRIPT = r"""
function liftWynxq(window) {
    if (!window) return;
    var caption = String(window.caption || "");
    if (caption.indexOf("Wynxq computer control") !== 0 &&
        caption.indexOf("Wynxq control panel") !== 0) return;
    window.keepAbove = true;
    workspace.raiseWindow(window);
}

var windows = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < windows.length; ++i) liftWynxq(windows[i]);

if (workspace.windowAdded) {
    workspace.windowAdded.connect(liftWynxq);
} else if (workspace.clientAdded) {
    workspace.clientAdded.connect(liftWynxq);
}
"""


def _is_kde_wayland() -> bool:
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" +
               os.environ.get("KDE_FULL_SESSION", "")).casefold()
    return bool(os.environ.get("WAYLAND_DISPLAY") and
                ("kde" in desktop or "plasma" in desktop or os.environ.get("KDE_FULL_SESSION")))


async def _call(bus, *, path: str, interface: str, member: str,
                signature: str = "", body=None):
    from dbus_next import Message, MessageType

    reply = await bus.call(Message(
        destination="org.kde.KWin",
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=list(body or []),
    ))
    if reply.message_type == MessageType.ERROR:
        detail = ": ".join(str(item) for item in (reply.body or []))
        raise RuntimeError(detail or f"KWin {member} failed")
    return reply.body or []


async def _promote(script_path: str, script_name: str, cancel: threading.Event | None):
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    script_id = None
    try:
        if cancel is not None and cancel.is_set():
            return False
        try:
            loaded = await _call(
                bus, path="/Scripting", interface="org.kde.kwin.Scripting",
                member="loadScript", signature="ss", body=[script_path, script_name])
        except RuntimeError:
            loaded = await _call(
                bus, path="/Scripting", interface="org.kde.kwin.Scripting",
                member="loadScript", signature="s", body=[script_path])
        if not loaded:
            return False
        script_id = int(loaded[0])
        script_object = f"/Scripting/Script{script_id}"
        await _call(bus, path=script_object, interface="org.kde.kwin.Script", member="run")
        for _ in range(8):
            if cancel is not None and cancel.is_set():
                break
            await asyncio.sleep(0.1)
        return True
    finally:
        if script_id is not None:
            try:
                await _call(bus, path=f"/Scripting/Script{script_id}",
                            interface="org.kde.kwin.Script", member="stop")
            except Exception:
                pass
        try:
            bus.disconnect()
        except Exception:
            pass


def promote_control_windows(cancel: threading.Event | None = None) -> bool:
    """Raise Wynxq's HUD on KDE Wayland; no-op everywhere else."""
    if not _is_kde_wayland() or (cancel is not None and cancel.is_set()):
        return False
    fd, path = tempfile.mkstemp(prefix="wynxq-kwin-", suffix=".js")
    try:
        os.write(fd, _KWIN_SCRIPT.encode("utf-8"))
        os.close(fd)
        fd = -1
        return bool(asyncio.run(_promote(path, "wynxq-control-" + uuid.uuid4().hex, cancel)))
    except Exception:
        return False
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
