"""Measure real pointer, scrolling and constrained-window behavior in QML."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QUrl, QMetaObject, Qt
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from wynxq.demo import DemoController
from wynxq import context as ctx
from wynxq.__main__ import _load_fonts

UI = Path(__file__).resolve().parents[1] / "wynxq" / "ui"


def visual_descendants(item):
    # ListView delegates belong to its visual tree, which is not necessarily
    # the QObject ownership tree used by findChildren.
    for child in item.childItems():
        yield child
        yield from visual_descendants(child)


HARNESS = """
import QtQuick
import QtQuick.Controls
import Wynxq

ApplicationWindow {
    id: window
    width: 800; height: 600; visible: true
    property bool conversation: false
    Binding { target: Theme; property: "bridge"; value: bridge }
    AssistantMessage {
        objectName: "answer"
        x: 20; y: 20; width: 500
        visible: !window.conversation
        body: "An older answer with copy and branch actions."
        tail: body
    }
    MessageList {
        objectName: "messages"
        x: 20; y: 20; width: 700; height: window.height - 40
        visible: window.conversation
        model: bridge.messageModel
    }
    PermissionPrompt { objectName: "permission" }
}
"""


def main():
    QQuickStyle.setStyle("Basic")
    app = QApplication([])
    _load_fonts(app)
    app.setFont(QFont("Inter", 10))
    controller = DemoController("empty")
    engine = QQmlEngine()
    engine.addImportPath(str(UI))
    engine.rootContext().setContextProperty("bridge", controller)
    component = QQmlComponent(engine)
    component.setData(HARNESS.encode(), QUrl.fromLocalFile(str(UI / "stability.qml")))
    assert not component.isError(), [error.toString() for error in component.errors()]
    window = component.create()
    assert window, [error.toString() for error in component.errors()]
    result = {}

    try:
        answer = window.findChild(QObject, "answer")
        QTest.mouseMove(window, QPoint(780, 580))
        QTest.qWait(200)
        before = answer.property("implicitHeight")
        QTest.mouseMove(window, QPoint(40, 35))
        QTest.qWait(250)
        result["answer_hover_height_delta"] = answer.property("implicitHeight") - before
        QTest.mouseMove(window, QPoint(780, 580))
        QTest.qWait(200)
        actions = answer.findChild(QObject, "responseActions")
        if actions:
            copy = next(obj for obj in actions.findChildren(QObject) if obj.property("iconName") == "copy")
            copy.forceActiveFocus(Qt.TabFocusReason)
            QTest.qWait(200)
            result["keyboard_actions_visible"] = actions.property("opacity") == 1
            result["keyboard_actions_height_delta"] = answer.property("implicitHeight") - before
            QTest.keyClick(window, Qt.Key_Space)
            result["keyboard_copied_answer"] = app.clipboard().text() == answer.property("body")

        window.setProperty("conversation", True)
        for index in range(35):
            controller.messages.append_message("user", f"Message {index}: " + "read this earlier turn. " * 5)
        listing = window.findChild(QObject, "messages")
        QMetaObject.invokeMethod(listing, "jumpToEnd")
        QTest.qWait(400)
        result["initial_at_bottom"] = listing.property("atBottom")
        result["initial_geometry"] = {name: listing.property(name) for name in
                                      ("contentY", "contentHeight", "height", "originY", "atYEnd", "following")}
        # Shrinking the viewport is what a growing composer or smaller window
        # does. A reader following the tail should still see the latest output.
        window.setHeight(400)
        QTest.qWait(300)
        result["resize_at_bottom"] = listing.property("atBottom")
        result["resized_geometry"] = {name: listing.property(name) for name in
                                      ("contentY", "contentHeight", "height", "originY", "atYEnd", "following")}

        QMetaObject.invokeMethod(listing, "jumpToEnd")
        QTest.qWait(200)
        # Drive the actual scrollbar thumb, rather than assigning contentY.
        bars = [obj for obj in listing.findChildren(QObject)
                if obj.objectName() == "wynxqScrollBar"]
        if not bars:
            bars = [obj for obj in visual_descendants(listing)
                    if obj.objectName() == "wynxqScrollBar"]
        assert bars, "conversation scrollbar was not instantiated"
        scrollbar = bars[0]
        position = float(scrollbar.property("position"))
        size = float(scrollbar.property("size"))
        p = scrollbar.mapToScene(QPointF(scrollbar.width() / 2,
                                        scrollbar.height() * (position + size / 2)))
        QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, p.toPoint())
        QTest.mouseMove(window, QPoint(round(p.x()), 80), 100)
        QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(round(p.x()), 80))
        QTest.qWait(300)
        result["scrollbar_left_bottom"] = not listing.property("atBottom")
        result["scrollbar_paused_following"] = not listing.property("following")
        previous_y = float(listing.property("contentY"))
        controller.messages.append_message("user", "New output while reading history")
        QTest.qWait(300)
        result["append_while_reading_y_delta"] = abs(float(listing.property("contentY")) - previous_y)
        QMetaObject.invokeMethod(listing, "jumpToEnd")
        QTest.qWait(200)
        result["jump_resumes_following"] = listing.property("following") and listing.property("atBottom")

        # A recycled delegate must not display a different message in an editor
        # that was opened for the old row.
        turns = [obj for obj in visual_descendants(listing)
                 if obj.metaObject().className().startswith("UserMessage_")]
        last_turn = max(turns, key=lambda obj: obj.property("row"))
        old_row = last_turn.property("row")
        last_turn.setProperty("editing", True)
        listing.setProperty("following", False)
        QMetaObject.invokeMethod(listing, "positionViewAtBeginning")
        QTest.qWait(300)
        result["recycled_editor_closed"] = not last_turn.property("editing")
        result["edited_row_was_scrolled_away"] = old_row >= 30 and not listing.property("atBottom")

        window.setWidth(560)
        window.setHeight(520)
        controller._pending_permission = {
            "tool": "run_command", "risk": "sensitive",
            "summary": "Run a multiline command", "command": "printf 'review this line\\n'\n" * 70,
            "directory": "/tmp", "detail": "exact arguments\n" * 40,
        }
        controller.permissionChanged.emit()
        QTest.qWait(400)
        permission = window.findChild(QObject, "permission")
        deny = window.findChild(QObject, "permissionDeny")
        result["permission_defaults_to_deny"] = deny.property("activeFocus") if deny else False
        result["permission_height"] = permission.property("height")
        result["window_height"] = window.height()
        result["permission_width"] = permission.property("width")
        permission.setProperty("showDetails", True)
        QTest.qWait(250)
        result["permission_details_height"] = permission.property("height")
        actions = window.findChild(QObject, "permissionActions")
        review = window.findChild(QObject, "permissionReview")
        if actions and review:
            action_pos = actions.mapToScene(QPointF(0, 0))
            review_pos = review.mapToScene(QPointF(0, 0))
            result["permission_actions_inside"] = (action_pos.x() >= 0 and action_pos.y() >= 0
                and action_pos.x() + actions.width() <= window.width()
                and action_pos.y() + actions.height() <= window.height())
            result["permission_no_overlap"] = review_pos.y() + review.height() <= action_pos.y()
            result["permission_scrollable"] = review.property("contentHeight") > review.height()
        if os.environ.get("WYNXQ_STABILITY_SCREENSHOTS"):
            target = Path(os.environ["WYNXQ_STABILITY_SCREENSHOTS"])
            target.mkdir(parents=True, exist_ok=True)
        controller._pending_permission = None
        controller.permissionChanged.emit()
        window.close()

        # Measure the full application too: long drafts and the supported
        # maximum of 12 attachments must not push Send out of the window.
        controller.messages.replace([])
        controller.changed.emit()
        shell_engine = QQmlApplicationEngine()
        shell_engine.addImportPath(str(UI))
        shell_engine.rootContext().setContextProperty("bridge", controller)
        shell_engine.load(QUrl.fromLocalFile(str(UI / "Main.qml")))
        shell = shell_engine.rootObjects()[0]
        shell.setWidth(560)
        shell.setHeight(520)
        controller._attachments = [ctx.make(ctx.FILE, f"project-context-{i}.py", text="source", subtitle="1 KB")
                                   for i in range(12)]
        controller.attachmentsChanged.emit()
        composer = shell.findChild(QObject, "mainComposer")
        composer.setProperty("text", "A long draft that should remain editable.\n" * 45)
        QTest.qWait(350)
        send = shell.findChild(QObject, "sendButton")
        send_pos = send.mapToScene(QPointF(0, 0))
        result["long_draft_send_inside"] = (send_pos.x() >= 0 and send_pos.y() >= 0
            and send_pos.x() + send.width() <= shell.width()
            and send_pos.y() + send.height() <= shell.height())
        result["long_draft_composer_height"] = composer.height()
        starters = next(obj for obj in visual_descendants(shell.contentItem())
                        if obj.metaObject().className().startswith("TaskStarters_"))
        starter_pos = starters.mapToScene(QPointF(0, 0))
        result["long_draft_starters_inside"] = starter_pos.y() + starters.height() <= shell.height()
        result["long_draft_geometry"] = {
            "maxHeight": composer.property("maxHeight"), "chromeHeight": composer.property("chromeHeight"),
            "contentHeight": composer.parentItem().parentItem().height(),
            "starter_y": starter_pos.y(), "starter_height": starters.height(),
            "starter_implicit_height": starters.property("implicitHeight"),
        }
        result["long_draft_preserved"] = controller.draftText == composer.property("text")
        attachment_scroll = shell.findChild(QObject, "composerAttachments")
        result["attachments_scrollable"] = (attachment_scroll.property("contentHeight")
                                             > attachment_scroll.height())
        if os.environ.get("WYNXQ_STABILITY_SCREENSHOTS"):
            target = Path(os.environ["WYNXQ_STABILITY_SCREENSHOTS"])
            assert shell.grabWindow().save(str(target / "constrained-composer.png"))
            controller._pending_permission = {
                "tool": "run_command", "risk": "sensitive",
                "summary": "Review the workspace", "command": "printf 'review this line\\n'\n" * 70,
                "directory": "/tmp", "detail": "exact arguments\n" * 40,
            }
            controller.permissionChanged.emit()
            QTest.qWait(300)
            assert shell.grabWindow().save(str(target / "permission-review.png"))
            controller._pending_permission = None
            controller.permissionChanged.emit()
        shell.close()
        print(json.dumps(result))
    finally:
        window.close()
        controller.shutdown()


if __name__ == "__main__":
    main()
