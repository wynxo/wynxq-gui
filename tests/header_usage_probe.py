"""Verify header padding, mode clicks, chat totals and Settings routing in Qt."""
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, QUrl, QMetaObject, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from wynxq.demo import DemoController

QQuickStyle.setStyle('Basic')
app = QApplication([])
controller = DemoController('conversation')
controller.store.record_token_usage(controller.taskId, 'demo', {'tokens': 427, 'prompt_tokens': 1800})
controller.refreshTokenUsage()
controller._conversation_tokens = controller._read_conversation_tokens()
controller._usage.exact_metrics({'tokens': 427, 'tokens_per_second': 18.6})
engine = QQmlApplicationEngine()
ui = Path(__file__).resolve().parents[1] / 'wynxq' / 'ui'
engine.addImportPath(str(ui))
engine.rootContext().setContextProperty('bridge', controller)
engine.load(QUrl.fromLocalFile(str(ui / 'Main.qml')))
assert engine.rootObjects()
window = engine.rootObjects()[0]
output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if output: output.mkdir(parents=True, exist_ok=True)
def get(name):
    def walk(item):
        if item.objectName() == name: return item
        for child in item.childItems():
            result = walk(child)
            if result is not None: return result
        return None
    obj = window.findChild(QObject, name)
    if obj is None: obj = walk(window.contentItem())
    assert obj is not None, name
    return obj
def capture(name):
    if output: assert window.grabWindow().save(str(output / name))
def settle(): QTest.qWait(400)
try:
    window.setWidth(1280); window.setHeight(820); settle()
    label = get('projectButtonLabel'); button = get('projectButton')
    assert button.width() > 80
    pos = label.mapToItem(button, QPointF(0, 0))
    assert pos.x() >= 9, pos
    assert pos.x() + label.width() <= button.width() - 18
    for mode in ('chat', 'work'):
        choice = get('modeChoice_' + mode)
        content = choice.property('contentItem')
        row = content.childItems()[0]
        assert row.x() >= 10, (mode, row.x())
        assert row.x() + row.width() <= choice.width() - 10
    assert get('tokenUsage').property('chatTokens') == controller.conversationTokens == 3897
    capture('refined-chat.png')
    point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
    QTest.mouseMove(window, point.toPoint()); settle()
    capture('refined-header-hover.png')
    settings = get('settingsSheet')
    settings.setProperty('page', settings.property('usagePage'))
    QMetaObject.invokeMethod(settings, 'open'); settle()
    assert settings.property('visible')
    capture('refined-usage-settings.png')
    QMetaObject.invokeMethod(settings, 'close'); settle()
    # DemoController intentionally uses the base controller's locked-task modes.
    controller.newTask(); settle()
    choice = get('modeChoice_work')
    point = choice.mapToScene(QPointF(choice.width()/2, choice.height()/2))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point.toPoint()); settle()
    assert controller.taskMode == 'work'
    window.setWidth(760); window.setHeight(640); settle()
    send = get('sendButton'); pos = send.mapToScene(QPointF(0,0))
    assert 0 <= pos.x() and pos.x() + send.width() <= window.width()
    capture('refined-compact-work.png')
    print('header and usage interactions: ok')
finally:
    window.close(); controller.shutdown()
