"""Exercise every welcome page at the smallest supported window size."""
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, QUrl, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from wynxq.demo import DemoController

QQuickStyle.setStyle('Basic')
app = QApplication([])
bridge = DemoController('welcome')
engine = QQmlApplicationEngine()
ui = Path(__file__).resolve().parents[1] / 'wynxq/ui'
engine.addImportPath(str(ui))
engine.rootContext().setContextProperty('bridge', bridge)
engine.load(QUrl.fromLocalFile(str(ui / 'Main.qml')))
window = engine.rootObjects()[0]
window.resize(560, 520)
QTest.qWait(600)
popup = window.findChild(QObject, 'welcomeDialog')
next_button = window.findChild(QObject, 'welcomeContinue')
back_button = window.findChild(QObject, 'welcomeBack')
body = window.findChild(QObject, 'welcomeBody')


def click(item):
    position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position.toPoint())
    QTest.qWait(100)


try:
    assert popup.property('opened')
    click(next_button)
    assert popup.property('step') == 1
    click(back_button)
    assert popup.property('step') == 0
    # Long host names must scroll within the panel instead of hiding actions.
    bridge._endpoint = 'https://' + 'long-host-name-' * 30 + '.example:11434'
    bridge._working_directory = ''
    bridge.changed.emit()
    for step in range(5):
        popup.setProperty('step', step)
        QTest.qWait(100)
        assert popup.property('height') <= window.height() - 24
        for item in (body, next_button):
            position = item.mapToScene(QPointF(0, 0))
            assert position.x() >= 0 and position.y() >= 0
            assert position.x() + item.width() <= window.width()
            assert position.y() + item.height() <= window.height()
    popup.setProperty('step', 3)
    QTest.qWait(100)
    click(next_button)
    assert popup.property('step') == 4, 'a project folder must remain optional'
    click(next_button)
    assert not popup.property('opened')
    print('welcome interactions: ok')
finally:
    window.close()
    bridge.shutdown()
