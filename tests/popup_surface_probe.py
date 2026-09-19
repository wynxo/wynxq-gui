"""Verify floating surfaces obscure underlying pixels on the software renderer."""
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

QQuickStyle.setStyle('Basic')
app = QGuiApplication(sys.argv[:1])
engine = QQmlEngine()
ui = Path(__file__).resolve().parents[1] / 'wynxq/ui'
engine.addImportPath(str(ui))
component = QQmlComponent(engine)
component.setData(b'''
import QtQuick
import QtQuick.Controls
import Wynxq
ApplicationWindow {
    width: 400; height: 300; visible: true
    property color behind: "#ffffff"
    Rectangle { anchors.fill: parent; color: behind }
    Sheet { objectName: "sheet"; width: 240; height: 180 }
    Item {
        x: 60; y: 20; width: 30; height: 30
        Popover { objectName: "popover"; width: 240; height: 180 }
    }
}
''', QUrl.fromLocalFile(str(ui / 'popup-probe.qml')))
window = component.create()
assert window, [e.toString() for e in component.errors()]
for name in ('sheet', 'popover'):
    popup = window.findChild(QObject, name)
    popup.open()
    QTest.qWait(300)
    background = popup.property('background')
    assert not background.property('liveBlurOn')
    assert background.property('color').alphaF() == 1.0
    before = window.grabWindow()
    assert not before.isNull()
    window.setProperty('behind', '#ff00ff')
    QTest.qWait(100)
    after = window.grabWindow()
    # Both surfaces cover this interior point; the underlying colour must have
    # no effect on the rendered popup, including its decorative material.
    assert before.pixelColor(160, 140) == after.pixelColor(160, 140)
    popup.close()
    QTest.qWait(200)
    window.setProperty('behind', '#ffffff')
print('popup surfaces: ok')
window.close()
