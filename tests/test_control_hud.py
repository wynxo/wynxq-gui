"""Exercise compositor placement logic and GUI/worker capture coordination."""
import threading
import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QJSEngine

from wynxq.controller_support import CaptureVisibility
from wynxq.desktop_common import DesktopCancelled
from wynxq.kwin import _KWIN_SCRIPT

APP = QCoreApplication.instance() or QCoreApplication([])


def test_kwin_places_only_this_process_hud_and_tracks_changes():
    engine = QJSEngine()
    setup = engine.evaluate('''
        function signal() { return {slots: [], connect: function(f) { this.slots.push(f); },
            emit: function(arg) { this.slots.forEach(function(f) {f(arg);}); }}; }
        function windowFor(title, pid) { return {caption: title, pid: pid,
            frameGeometry: {x: 30, y: 40, width: 360, height: 180},
            frameGeometryChanged: signal(), keepAboveChanged: signal()}; }
        var KWin = {MaximizeArea: 1, ScreenArea: 2};
        var panel = windowFor("Wynxq live computer activity", 123);
        var unrelated = windowFor("Editor", 123);
        var impostor = windowFor("Wynxq live computer activity", 456);
        var area = {x: -1920, y: 0, width: 1920, height: 1040};
        var windows = [panel, unrelated, impostor];
        var raised = [];
        var workspace = {windowList: function() { return windows; },
            clientArea: function() { return area; },
            raiseWindow: function(w) { raised.push(w); },
            windowAdded: signal(), windowActivated: signal(), screensChanged: signal(),
            currentDesktopChanged: signal()};
    ''')
    assert not setup.isError(), setup.toString()
    result = engine.evaluate(_KWIN_SCRIPT.replace("__OWNER_PID__", "123"))
    assert not result.isError(), result.toString()
    assert engine.evaluate('panel.frameGeometry.x').toInt() == -372
    assert engine.evaluate('panel.frameGeometry.y').toInt() == 848
    assert engine.evaluate('panel.keepAbove && panel.onAllDesktops').toBool()
    assert engine.evaluate('raised.indexOf(unrelated) === -1 && raised.indexOf(impostor) === -1').toBool()
    engine.evaluate('panel.frameGeometry.height = 250; panel.frameGeometryChanged.emit();')
    assert engine.evaluate('panel.frameGeometry.y').toInt() == 778
    engine.evaluate('area = {x: 1920, y: -200, width: 1280, height: 720}; workspace.screensChanged.emit();')
    assert engine.evaluate('panel.frameGeometry.x').toInt() == 2828
    assert engine.evaluate('panel.frameGeometry.y').toInt() == 258
    engine.evaluate('panel.keepAbove = false; panel.keepAboveChanged.emit();')
    assert engine.evaluate('panel.keepAbove').toBool()
    engine.evaluate('var overlay = windowFor("Wynxq computer control", 123); windows.push(overlay); workspace.windowAdded.emit(overlay);')
    assert engine.evaluate('overlay.frameGeometry.x').toInt() == 1920
    assert engine.evaluate('overlay.frameGeometry.width').toInt() == 1280
    engine.evaluate('workspace.windowActivated.emit(unrelated);')
    assert engine.evaluate('panel.frameGeometryChanged.slots.length').toInt() == 1


def pump_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_capture_waits_for_gui_and_restores_after_failure():
    visibility = CaptureVisibility()
    states = []
    visibility.changed.connect(lambda: states.append(visibility.hidden))
    results = []
    def worker():
        try:
            with visibility.capture():
                results.append(visibility.hidden)
                raise RuntimeError("backend failed")
        except RuntimeError:
            results.append("failed")
    thread = threading.Thread(target=worker)
    thread.start()
    pump_until(lambda: not thread.is_alive())
    thread.join()
    pump_until(lambda: not visibility.hidden)
    assert results == [True, "failed"]
    assert states == [True, False]


def test_cancelled_capture_restores_hud_without_taking_image():
    visibility = CaptureVisibility()
    cancel = threading.Event()
    cancel.set()
    results = []
    def worker():
        try:
            with visibility.capture(cancel):
                results.append("captured")
        except DesktopCancelled:
            results.append("cancelled")
    thread = threading.Thread(target=worker)
    thread.start()
    pump_until(lambda: not thread.is_alive())
    thread.join()
    APP.processEvents()
    assert results == ["cancelled"]
    assert not visibility.hidden
