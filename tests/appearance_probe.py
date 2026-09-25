"""Verify app-wide appearance switches in the real Qt UI."""
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, Qt, QUrl
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
    settings = window.findChild(QObject, "settingsSheet")
    settings.setProperty("page", settings.property("appearancePage"))
    QTest.qWait(400)
    picker = find(window.contentItem(), "appColorSchemePicker")
    for index, scheme in enumerate(("Dark", "Black", "Midnight")):
        point = picker.mapToScene(QPointF(3 + (index + .5) * picker.property("segmentWidth"), picker.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(250)
        assert controller.colorScheme == scheme
        assert picker.property("current") == scheme
        expected = {"Dark": "#171717", "Black": "#090909", "Midnight": "#141518"}[scheme]
        assert window.property("color").name() == expected
        assert settings.property("background").property("color").name() == expected
    controller.setColorScheme("Dark")
    controller.setTheme("Mint")
    QTest.mouseMove(window, QPointF(10, 10).toPoint())
    QTest.qWait(300)
    assert window.grabWindow().save(str(output / "appearance-settings.png"))
    print("App palette clicks update window and Settings: OK")
finally:
    window.close()
    controller.shutdown()
