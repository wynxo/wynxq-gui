"""Drive real QML components and report what they did, as JSON on stdout.

Qt allows one application object per process and QML needs a GUI one, while the
rest of the suite runs on a plain QCoreApplication. So the interaction checks
live here and `test_qml_interaction.py` runs this in a subprocess, the same way
the headless load check already does.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "wynxq" / "ui"

# A window gives popups an Overlay to place themselves inside, which is exactly
# what the placement logic under test depends on.
HARNESS = """
import QtQuick
import QtQuick.Controls
import Wynxq

ApplicationWindow {
    id: window
    width: 900; height: 700; visible: true
    property alias menu: menu
    property alias toggle: toggle
    property alias chip: chip
    property alias anchorButton: anchorButton
    property string toggleLog: ""

    Item {
        id: anchorButton
        objectName: "anchor"
        x: 820; y: 40; width: 60; height: 30

        WMenu {
            id: menu
            objectName: "menu"
            anchorX: -menuWidth + parent.width
            menuWidth: 240
            items: [
                { id: "one", label: "One" },
                { id: "two", label: "Two" },
                { separator: true },
                { id: "three", label: "Three", disabled: true },
                { id: "four", label: "Four" },
            ]
        }
    }

    Toggle {
        id: toggle
        objectName: "toggle"
        x: 20; y: 200; width: 300
        text: "A setting"
        // Bound, as every real use of it is: the control must not fight this.
        checked: window.backing
        onSwitched: function(value) { window.toggleLog += value ? "on " : "off "; }
    }
    UserMessage {
        objectName: "longMessage"
        x: 20; y: 400; width: 280
        body: "A long message that should wrap without pushing the edit and copy controls outside the message row. ".repeat(8)
    }
    property bool backing: false

    Chip {
        id: chip
        objectName: "chip"
        x: 20; y: 300
        width: 160
        text: "a-very-long-attachment-name.py"
        subtitle: "4210 lines"
        iconName: "file"
        removable: true
    }
}
"""


def main() -> int:
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlEngine()
    engine.addImportPath(str(UI))

    component = QQmlComponent(engine)
    component.setData(HARNESS.encode(), QUrl.fromLocalFile(str(UI) + "/probe.qml"))
    if component.isError():
        print(json.dumps({"error": [e.toString() for e in component.errors()]}))
        return 1
    window = component.create()
    if window is None:
        print(json.dumps({"error": ["component produced no object"]}))
        return 1
    assert isinstance(window, QQuickWindow)
    app.processEvents()

    result: dict = {}
    # Popups are not items, so they are reached by objectName rather than by a
    # property alias PySide would have to convert.
    menu = window.findChild(QObject, "menu")
    toggle = window.findChild(QObject, "toggle")
    chip = window.findChild(QObject, "chip")
    anchor = window.findChild(QObject, "anchor")

    # A menu anchored to the right edge of a control near the window edge must
    # land in the same place every time it opens, not creep further each time.
    positions = []
    for _ in range(3):
        menu.setProperty("visible", True)
        app.processEvents()
        positions.append(round(float(menu.property("x")), 2))
        menu.setProperty("visible", False)
        app.processEvents()
    result["menu_x_positions"] = positions

    # It must also stay inside the window rather than hanging off the edge.
    anchor_left = float(anchor.property("x"))
    result["menu_right_edge"] = anchor_left + positions[0] + float(menu.property("width"))
    result["window_width"] = float(window.property("width"))

    # Arrow keys walk the menu and skip separators and disabled entries.
    menu.setProperty("visible", True)
    app.processEvents()
    walk = []
    for _ in range(4):
        menu.metaObject().invokeMethod(menu, "step", *_int_arg(1))
        walk.append(menu.property("highlighted"))
    result["menu_walk"] = walk
    menu.setProperty("visible", False)
    app.processEvents()

    # The switch reports the value it wants and leaves `checked` to its binding,
    # so a setting the controller refuses cannot drift out of sync.
    toggle.metaObject().invokeMethod(toggle, "clicked")
    app.processEvents()
    result["toggle_requested"] = str(window.property("toggleLog")).split()
    result["toggle_checked_after_click"] = bool(toggle.property("checked"))
    window.setProperty("backing", True)
    app.processEvents()
    result["toggle_follows_binding"] = bool(toggle.property("checked"))

    # A constrained chip elides rather than overflowing its own background.
    content = chip.property("contentItem")
    result["chip_width"] = float(chip.property("width"))
    result["chip_content_width"] = float(content.property("width")) if content else -1
    result["chip_implicit_width"] = float(chip.property("implicitWidth"))

    message = window.findChild(QObject, "longMessage")
    actions = window.findChild(QObject, "messageActions")
    result["message_actions_left"] = float(actions.property("x"))
    result["message_actions_visible"] = bool(actions.property("visible"))
    result["message_height"] = float(message.property("implicitHeight"))

    print(json.dumps(result))
    return 0


def _int_arg(value):
    """QML functions take variants, so that is what invokeMethod must pass."""
    from PySide6.QtCore import Q_ARG
    return (Q_ARG("QVariant", value),)


if __name__ == "__main__":
    sys.exit(main())
