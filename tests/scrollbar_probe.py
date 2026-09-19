"""Exercise real viewport hover/drag behavior and optionally capture the app."""
import json
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QPoint, QPointF, QUrl, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from wynxq.demo import DemoController

QQuickStyle.setStyle('Basic')
app = QApplication([])
controller = DemoController('conversation')
engine = QQmlApplicationEngine()
ui = Path(__file__).resolve().parents[1] / 'wynxq' / 'ui'
engine.addImportPath(str(ui))
engine.rootContext().setContextProperty('bridge', controller)
engine.load(QUrl.fromLocalFile(str(ui / 'Main.qml')))
assert engine.rootObjects(), 'Application failed to load'
window = engine.rootObjects()[0]
window.setWidth(1100)
window.setHeight(680)
QTest.qWait(700)
bars = [o for o in window.findChildren(QObject) if o.metaObject().className().startswith('WScrollBar')]
bar = next(o for o in bars if o.property('size') < 1 and o.parentItem().metaObject().className().startswith('MessageList'))
viewport = bar.parentItem()
output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if output: output.mkdir(parents=True, exist_ok=True)
def capture(name):
    if output: assert window.grabWindow().save(str(output / name))
def move(x, y):
    QTest.mouseMove(window, QPoint(x, y))
    QTest.qWait(300)
try:
    move(400, 20)
    assert bar.property('opacity') == 0, 'Idle scrollbar remains visible'
    capture('scrollbar-idle.png')
    point = viewport.mapToScene(QPointF(viewport.width() / 2, 100))
    move(int(point.x()), int(point.y()))
    assert bar.property('opacity') == 1, 'Viewport hover does not reveal scrollbar'
    capture('scrollbar-hover.png')
    thumb = bar.property('contentItem')
    point = thumb.mapToScene(QPointF(thumb.width()/2, thumb.height()/2))
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, point.toPoint())
    assert bar.property('pressed'), 'Thumb cannot be grabbed'
    move(400, 20)
    assert bar.property('opacity') == 1, 'Dragging outside viewport hides scrollbar'
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(400, 20))
    QTest.qWait(300)
    assert bar.property('opacity') == 0, 'Scrollbar stays visible after drag release'
    # Content without overflow must never show a misleading scrollbar.
    window.setHeight(1600)
    QTest.qWait(500)
    point = viewport.mapToScene(QPointF(100, 100))
    move(int(point.x()), int(point.y()))
    assert bar.property('size') >= 1
    assert bar.property('opacity') == 0
    print(json.dumps({'idle_hidden': True, 'hover_visible': True, 'drag_visible_outside': True,
                      'release_hidden': True, 'no_overflow_hidden': True, 'shared_bars': len(bars)}))
finally:
    window.close()
    controller.shutdown()
