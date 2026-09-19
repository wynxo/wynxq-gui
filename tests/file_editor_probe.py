"""Exercise the real file editor without Ollama or user files."""
import json
import sys
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, QMetaObject
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
    width: 500; height: 320; visible: true
    property var bridge: fakeBridge
    QtObject { id: fakeBridge; property var workspaceDock: fakeDock }
    QtObject {
        id: fakeDock
        objectName: "fakeDock"
        property string command: ""
        function runInTerminal(value) { command = value }
        property var file: ({path: "/tmp/example.txt", name: "example.txt", text: "first", lines: 1})
        property bool fileModified: false
        function setFileBuffer(text) {}
    }
    FileViewer { objectName: "viewer"; anchors.fill: parent }
}
''', QUrl.fromLocalFile(str(ui / 'editor-probe.qml')))
window = component.create()
assert window, [e.toString() for e in component.errors()]
viewer = window.findChild(QObject, 'viewer')
editor = window.findChild(QObject, 'fileEditor')
viewport = window.findChild(QObject, 'fileViewport')
editor.setProperty('text', '\n'.join(f'line {n}' for n in range(100)))
QTest.qWait(100)
assert viewer.property('bufferLines') == 100
assert str(viewer.property('numbers')).endswith('99\n100')
editor.setProperty('cursorPosition', len(editor.property('text')))
QTest.qWait(100)
assert viewport.property('contentY') > 0
cursor = editor.property('cursorRectangle')
assert editor.property('y') + cursor.y() + cursor.height() <= viewport.property('contentY') + viewport.property('height') + 1
editor.setProperty('cursorPosition', 0)
QTest.qWait(100)
assert viewport.property('contentY') <= editor.property('y')
editor.setProperty('text', 'a' * 300)
editor.setProperty('cursorPosition', 300)
QTest.qWait(100)
assert viewport.property('contentX') > 0
assert viewer.property('bufferLines') == 1
editor.select(10, 20)
QTest.qWait(50)
assert editor.property('selectedText') == 'a' * 10
viewer.setProperty('wrap', True)
QTest.qWait(50)
assert viewer.property('bufferLines') == 1
viewer.setProperty('wrap', False)
editor.setProperty('text', 'start\n' + 'middle\n' * 100 + 'needle')
QMetaObject.invokeMethod(viewer, 'openFind')
search = window.findChild(QObject, 'fileFindInput')
search.setProperty('text', 'needle')
QTest.qWait(100)
assert editor.property('selectedText') == 'needle'
assert viewport.property('contentY') > 0
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary) / "space ' $(touch INJECTED) `touch ALSO_INJECTED`"
    folder.mkdir()
    dock = window.findChild(QObject, 'fakeDock')
    dock.setProperty('file', {'path': str(folder / 'file.txt'), 'name': 'file.txt', 'text': ''})
    QMetaObject.invokeMethod(viewer, 'terminalInFileFolder')
    result = subprocess.run(['bash', '-c', dock.property('command') + '\npwd'],
                            cwd=temporary, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == str(folder)
    assert not (Path(temporary) / 'INJECTED').exists()
    assert not (Path(temporary) / 'ALSO_INJECTED').exists()
print(json.dumps({'ok': True}))
window.close()
