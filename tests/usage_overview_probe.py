"""Exercise activity modes and capture the real usage page at desktop/narrow sizes."""
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from wynxq.__main__ import UI, _load_fonts
from wynxq.demo import DemoController

QQuickStyle.setStyle("Basic")
app = QApplication([])
_load_fonts(app)
controller = DemoController("usage")
engine = QQmlApplicationEngine()
engine.addImportPath(str(UI))
engine.rootContext().setContextProperty("bridge", controller)
engine.load(QUrl.fromLocalFile(str(UI / "Main.qml")))
window = engine.rootObjects()[0]
window.setWidth(1440)
window.setHeight(1080)
window.setProperty("previewOverlay", "usageSettings")
QTest.qWait(700)

def find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        result = find(child, name)
        if result is not None:
            return result
    return None

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
try:
    grid = find(window.contentItem(), "usageActivityGrid")
    assert grid is not None
    for mode, name in enumerate(("daily", "weekly", "cumulative")):
        button = find(window.contentItem(), "usageActivityMode" + str(mode))
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(200)
        assert grid.property("mode") == mode
        assert window.grabWindow().save(str(output / ("usage-" + name + ".png")))
    overview = find(window.contentItem(), "usageOverview")
    for key in ("today", "week", "month", "year", "allTime"):
        button = find(window.contentItem(), "usagePeriod_" + key)
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(100)
        assert overview.property("period") == key
        assert overview.property("selected")["tokens"] == controller.tokenUsage[key]["tokens"]
    window.setWidth(900)
    window.setHeight(720)
    QTest.qWait(300)
    assert grid.width() > 0
    assert grid.mapToScene(QPointF(grid.width(), 0)).x() <= window.width()
    assert window.grabWindow().save(str(output / "usage-compact.png"))
    scroll = find(window.contentItem(), "settingsScroll")
    bar = next(item for item in scroll.findChildren(QObject) if item.objectName() == "wynxqScrollBar" and item.property("orientation") == Qt.Vertical)
    QTest.mouseMove(window, QPoint(5, 5))
    QTest.qWait(900)
    assert bar.property("size") < 1
    assert bar.property("opacity") == 0
    assert bar.mapToScene(QPointF(0, 0)).x() > window.width() - 30
    point = scroll.mapToScene(QPointF(scroll.width()/2, scroll.height()/2))
    QTest.mouseMove(window, point.toPoint())
    QTest.qWait(200)
    assert bar.property("opacity") == 0
    QTest.wheelEvent(window, point, QPoint(0, -120))
    QTest.qWait(150)
    assert bar.property("opacity") > 0, "Wheel scrolling must reveal the bar"
    QTest.qWait(1000)
    assert bar.property("opacity") == 0
    print("Usage periods, grid modes, and Settings wheel/idle behavior: OK")
finally:
    window.close()
    controller.shutdown()
