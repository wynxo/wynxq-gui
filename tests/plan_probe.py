"""Drive the real QML shell with an agent-authored plan and report its state."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wynxq.demo import DemoController


QQuickStyle.setStyle("Basic")
app = QApplication([])
controller = DemoController("conversation")
engine = QQmlApplicationEngine()
ui = Path(__file__).resolve().parents[1] / "wynxq" / "ui"
engine.addImportPath(str(ui))
engine.rootContext().setContextProperty("bridge", controller)
engine.load(QUrl.fromLocalFile(str(ui / "Main.qml")))
window = engine.rootObjects()[0]

try:
    QTest.qWait(250)
    controller._set_plan([
        {"id": "inspect", "title": "Inspect the current workspace", "status": "completed"},
        {"id": "edit", "title": "Implement the layout changes", "status": "in_progress"},
        {"id": "verify", "title": "Run the UI verification", "status": "pending"},
    ], persist=False)
    QTest.qWait(350)

    rows = window.findChild(QObject, "planRows")
    print(json.dumps({
        "loaded": rows is not None,
        "visible": bool(rows and rows.property("visible")),
        "count": int(rows.property("count")) if rows else 0,
        "dock_visible": bool(controller.workspaceDock.visible),
        "summary": controller.planSummary,
    }))
finally:
    window.close()
    controller.shutdown()
