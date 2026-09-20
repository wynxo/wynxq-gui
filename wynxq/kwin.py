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


# Script lifetime is the visible control session, not a one-shot raise.
# KWin owns placement on Wayland; QWindow.setPosition is only a hint there.
_KWIN_SCRIPT = r"""
var ownerPid = __OWNER_PID__;
var watched = [];
var updating = false;
function isHud(window) {
    return window && Number(window.pid) === ownerPid &&
        (String(window.captionNormal || window.caption) === "Wynxq computer control" ||
         String(window.captionNormal || window.caption) === "Wynxq live computer activity");
}
function place(window) {
    if (!isHud(window) || updating) return;
    updating = true;
    try {
        window.keepAbove = true;
        window.skipTaskbar = true;
        window.skipPager = true;
        window.onAllDesktops = true;
        var panel = String(window.captionNormal || window.caption) === "Wynxq live computer activity";
        var area = workspace.clientArea(panel ? KWin.MaximizeArea : KWin.ScreenArea, window);
        var rect = window.frameGeometry;
        var width = panel ? Math.min(rect.width, area.width - 24) : area.width;
        var height = panel ? Math.min(rect.height, area.height - 24) : area.height;
        var x = panel ? area.x + area.width - width - 12 : area.x;
        var y = panel ? area.y + area.height - height - 12 : area.y;
        if (rect.x !== x || rect.y !== y || rect.width !== width || rect.height !== height)
            window.frameGeometry = {x: x, y: y, width: width, height: height};
        workspace.raiseWindow(window);
    } finally { updating = false; }
}
function watch(window) {
    if (!isHud(window) || watched.indexOf(window) !== -1) return;
    watched.push(window);
    window.frameGeometryChanged.connect(function() { place(window); });
    window.keepAboveChanged.connect(function() { place(window); });
    place(window);
}
function refresh() {
    var windows = workspace.windowList ? workspace.windowList() : workspace.clientList();
    for (var i = 0; i < windows.length; ++i) { watch(windows[i]); place(windows[i]); }
}
refresh();
if (workspace.windowAdded) workspace.windowAdded.connect(watch);
else if (workspace.clientAdded) workspace.clientAdded.connect(watch);
if (workspace.windowActivated) workspace.windowActivated.connect(refresh);
else if (workspace.clientActivated) workspace.clientActivated.connect(refresh);
if (workspace.screensChanged) workspace.screensChanged.connect(refresh);
if (workspace.desktopResized) workspace.desktopResized.connect(refresh);
if (workspace.currentDesktopChanged) workspace.currentDesktopChanged.connect(refresh);
"""


def _is_kde_wayland() -> bool:
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + ":" +
               os.environ.get("KDE_FULL_SESSION", "")).casefold()
    return bool(os.environ.get("WAYLAND_DISPLAY") and
                ("kde" in desktop or "plasma" in desktop or os.environ.get("KDE_FULL_SESSION")))


async def _call(bus, *, path: str, interface: str, member: str,
                signature: str = "", body=None):
    from dbus_next import Message, MessageType

    reply = await asyncio.wait_for(bus.call(Message(
        destination="org.kde.KWin",
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=list(body or []),
    )), timeout=1.0)
    if reply.message_type == MessageType.ERROR:
        detail = ": ".join(str(item) for item in (reply.body or []))
        raise RuntimeError(detail or f"KWin {member} failed")
    return reply.body or []


async def _promote(script_path: str, script_name: str, cancel: threading.Event | None):
    from dbus_next.aio import MessageBus

    bus = await asyncio.wait_for(MessageBus().connect(), timeout=1.0)
    script_id = None
    unload_name = script_name
    try:
        if cancel is not None and cancel.is_set():
            return False
        try:
            loaded = await _call(
                bus, path="/Scripting", interface="org.kde.kwin.Scripting",
                member="loadScript", signature="ss", body=[script_path, script_name])
        except RuntimeError:
            unload_name = script_path
            loaded = await _call(
                bus, path="/Scripting", interface="org.kde.kwin.Scripting",
                member="loadScript", signature="s", body=[script_path])
        if not loaded or int(loaded[0]) < 0:
            return False
        script_id = int(loaded[0])
        script_object = f"/Scripting/Script{script_id}"
        await _call(bus, path=script_object, interface="org.kde.kwin.Script", member="run")
        # Keep signal handlers alive through application switches and resizes.
        while cancel is not None and not cancel.is_set():
            await asyncio.sleep(0.1)
        return True
    finally:
        if script_id is not None:
            try:
                await _call(bus, path="/Scripting", interface="org.kde.kwin.Scripting",
                            member="unloadScript", signature="s", body=[unload_name])
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
        os.write(fd, _KWIN_SCRIPT.replace("__OWNER_PID__", str(os.getpid())).encode("utf-8"))
        os.close(fd)
        fd = -1
        return bool(asyncio.run(_promote(path, "wynxq-control-" + uuid.uuid4().hex, cancel)))
    except Exception:
        import logging
        logging.getLogger(__name__).warning("KWin could not place the control HUD", exc_info=True)
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
