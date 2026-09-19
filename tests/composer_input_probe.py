"""Exercise the real QML composer Return path with Qt key events."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Qt
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wynxq.__main__ import _load_fonts
from wynxq.demo import DemoController

UI = Path(__file__).resolve().parents[1] / "wynxq" / "ui"

HARNESS = """
import QtQuick
import QtQuick.Controls
import Wynxq

ApplicationWindow {
    id: window
    width: 760
    height: 420
    visible: true
    property string sent: ""
    Binding { target: Theme; property: "bridge"; value: bridge }

    Composer {
        id: composerRoot
        objectName: "composerRoot"
        width: 620
        anchors.centerIn: parent
        maxHeight: 160
        onSubmitted: function(text) { window.sent = text }
    }
}
"""


def main() -> int:
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv[:1])
    _load_fonts(app)
    app.setFont(QFont("Inter", 10))
    bridge = DemoController("empty")
    engine = QQmlEngine()
    engine.addImportPath(str(UI))
    engine.rootContext().setContextProperty("bridge", bridge)
    component = QQmlComponent(engine)
    component.setData(HARNESS.encode(), QUrl.fromLocalFile(str(UI / "composer-input-probe.qml")))
    if component.isError():
        print(json.dumps({"error": [e.toString() for e in component.errors()]}), flush=True)
        return 1
    window = component.create()
    if window is None:
        print(json.dumps({"error": [e.toString() for e in component.errors()]}), flush=True)
        return 1

    try:
        input_item = window.findChild(QObject, "composer")
        assert input_item is not None
        input_item.forceActiveFocus()
        QTest.qWait(80)

        input_item.setProperty("text", "send with return")
        QTest.keyClick(window, Qt.Key_Return)
        QTest.qWait(100)
        return_sent = window.property("sent") == "send with return"
        return_cleared = input_item.property("text") == ""

        window.setProperty("sent", "")
        input_item.setProperty("text", "keep editing")
        input_item.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Return, Qt.ShiftModifier)
        QTest.qWait(100)
        result = {
            "return_sent": return_sent,
            "return_cleared": return_cleared,
            "shift_return_did_not_send": window.property("sent") == "",
            "shift_return_inserted_newline": "\n" in input_item.property("text"),
        }
        print(json.dumps(result), flush=True)
        return 0
    finally:
        window.close()
        bridge.shutdown()
        app.processEvents()


if __name__ == "__main__":
    sys.exit(main())
