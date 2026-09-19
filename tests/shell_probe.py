"""Measure the real application shell across sidebar and window states."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QUrl, QMetaObject
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from wynxq.demo import DemoController

QQuickStyle.setStyle('Basic')
app = QApplication([])
controller = DemoController('empty')
engine = QQmlApplicationEngine()
ui = Path(__file__).resolve().parents[1] / 'wynxq' / 'ui'
engine.addImportPath(str(ui))
engine.rootContext().setContextProperty('bridge', controller)
engine.load(QUrl.fromLocalFile(str(ui / 'Main.qml')))
window = engine.rootObjects()[0]
result = []


def record(label):
    # Sidebar/drawer transitions use the normal UI animation budget. Give Qt
    # enough time to finish them before measuring the final layout; sampling at
    # exactly 250 ms can catch the old drawer and the docked sidebar on the same
    # transition frame on a busy CI runner.
    QTest.qWait(500)
    controls = [item for item in window.findChildren(QObject)
                if item.objectName() in {
                    'headerSidebarToggle', 'sidebarCollapseButton', 'sidebarRestoreButton'
                } and item.property('visible')]
    composer = window.findChild(QObject, 'mainComposer')
    viewport = window.findChild(QObject, 'conversationViewport')
    position = composer.mapToScene(QPointF(0, 0))
    viewport_position = viewport.mapToScene(QPointF(0, 0))
    result.append({'state': label, 'toggles': len(controls),
                   'composer_inside': position.x() >= 0 and position.y() >= 0
                    and position.x() + composer.width() <= window.width()
                    and position.y() + composer.height() <= window.height(),
                   'no_overlap': viewport_position.y() + viewport.height() <= position.y()})


try:
    record('expanded')
    controller.setSidebarCollapsed(True)
    record('collapsed')
    window.setWidth(560)
    window.setHeight(520)
    record('narrow')
    QMetaObject.invokeMethod(window, 'toggleSidebar')
    record('drawer')
    window.setWidth(1400)
    window.setHeight(900)
    record('resized-with-drawer-open')
    controller.setSidebarCollapsed(False)
    record('expanded-again')
    print(json.dumps(result))
finally:
    window.close()
    controller.shutdown()
