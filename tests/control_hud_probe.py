"""Render the actual HUD and check placement, Markdown and capture exclusion.

Run with QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python
 tests/control_hud_probe.py OUTPUT_DIRECTORY. No model or desktop input is used.
"""
import json
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
from wynxq.__main__ import UI, _load_fonts
from wynxq.demo import DemoController

QQuickStyle.setStyle("Basic")
app = QApplication([])
_load_fonts(app)
bridge = DemoController("computer-control")
bridge._run_sessions[bridge._task_id].update(messages=bridge.messages, history=[], usage=bridge._usage)
engine = QQmlApplicationEngine()
engine.addImportPath(str(UI))
engine.rootContext().setContextProperty("bridge", bridge)
engine.load(QUrl.fromLocalFile(str(UI / "Main.qml")))
assert engine.rootObjects()
root = engine.rootObjects()[0]
panel = root.property("computerControlPanelWindow")
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
token = object()
report = {}


def check_geometry():
    assert panel.isVisible()
    assert panel.x() == round(panel.property("screenX") + panel.property("screenWidth") - panel.width() - 12)
    assert panel.y() == round(panel.property("screenY") + panel.property("screenHeight") - panel.height() - 12)
    assert not panel.isActive()
    return [panel.x(), panel.y(), panel.width(), panel.height()]


def save(name):
    image = panel.grabWindow()
    assert not image.isNull()
    assert image.save(str(output / name))


def run(function):
    try:
        function()
    except Exception:
        traceback.print_exc()
        app.exit(1)


def first():
    bridge._on_event({"type": "thinking", "text": ""})
    bridge._on_event({"type": "message_end", "message": {
        "role": "assistant", "thinking": "The calculator is visible. I’ll enter the expression, then check the updated screen.",
        "content": "Entering **4 + 6** in KCalc and checking the result."}})
    QTimer.singleShot(200, lambda: run(normal))


def normal():
    report["normal_geometry"] = check_geometry()
    save("33-control-panel.png")
    bridge._on_event({"type": "thinking", "text": "Earlier line. " * 100 + "Latest thought: checking the result shown in KCalc."})
    bridge._on_event({"type": "token", "text": "Earlier update. " * 100 + "\n\n**Latest update:** 4 + 6 = **10**."})
    QTimer.singleShot(200, lambda: run(long_text))


def long_text():
    report["long_geometry"] = check_geometry()
    assert panel.height() < 330
    save("34-control-panel-streaming.png")
    bridge.captureVisibility.requested.emit((token, True, None))
    QTimer.singleShot(200, lambda: run(hidden))


def hidden():
    assert panel.isVisible()  # Native window remains mapped and never steals focus.
    assert panel.contentItem().opacity() == 0
    image = panel.grabWindow()
    assert all(image.pixelColor(x, y).alpha() == 0
               for x in range(0, image.width(), 15) for y in range(0, image.height(), 15))
    report["capture_exclusion"] = "HUD pixels are transparent during capture"
    bridge.captureVisibility.requested.emit((token, False, None))
    QTimer.singleShot(180, lambda: run(restored))


def restored():
    assert panel.contentItem().opacity() == 1
    check_geometry()
    print(json.dumps(report, indent=2))
    root.close()
    app.quit()


QTimer.singleShot(700, lambda: run(first))
QTimer.singleShot(10000, lambda: app.exit(2))
code = app.exec()
bridge.shutdown()
sys.exit(code)
