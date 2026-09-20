import QtQuick
import QtQuick.Window

/*!
    Click-through control HUD shown on every monitor while the foreground Work
    task is actively observing or controlling the desktop.

    It is intentionally a separate Window rather than content inside Wynxq:
    the user must still see the takeover state after another application gains
    focus. WindowTransparentForInput guarantees the HUD never steals the click
    or key Wynxq is trying to send.
*/
Window {
    id: root

    required property var targetScreen
    property bool controlVisible: false
    property string stopShortcut: "Esc"
    property string stopDetail: "Press Esc to stop instantly"
    readonly property color controlPurple: "#a78bfa"

    // Keep this as an independent top-level instead of a transient child of
    // the main Wynxq window, so it remains mapped over the app being driven.
    transientParent: null
    modality: Qt.NonModal
    readonly property var screenGeometry: targetScreen && targetScreen.geometry
                                          ? targetScreen.geometry : null

    screen: targetScreen
    x: screenGeometry ? screenGeometry.x
        : (targetScreen && targetScreen.virtualX !== undefined ? targetScreen.virtualX : 0)
    y: screenGeometry ? screenGeometry.y
        : (targetScreen && targetScreen.virtualY !== undefined ? targetScreen.virtualY : 0)
    width: screenGeometry ? screenGeometry.width
        : (targetScreen && targetScreen.width !== undefined ? targetScreen.width : 1)
    height: screenGeometry ? screenGeometry.height
        : (targetScreen && targetScreen.height !== undefined ? targetScreen.height : 1)
    visible: controlVisible
    color: "transparent"
    title: "Wynxq computer control"
    flags: Qt.FramelessWindowHint
         | Qt.WindowStaysOnTopHint
         | Qt.Tool
         | Qt.WindowTransparentForInput
         | Qt.WindowDoesNotAcceptFocus

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.52, 0.34, 0.96, 0.045)
        border.width: 3
        border.color: root.controlPurple
        opacity: 0.94
    }

    Rectangle {
        id: edgeGlow
        anchors.fill: parent
        anchors.margins: 4
        radius: 10
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(0.66, 0.55, 0.98, 0.68)
        opacity: Theme.reducedMotion ? 0.62 : 0.78

        SequentialAnimation on opacity {
            running: root.controlVisible && !Theme.reducedMotion
            loops: Animation.Infinite
            NumberAnimation { from: 0.52; to: 0.90; duration: 850; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.90; to: 0.52; duration: 850; easing.type: Easing.InOutSine }
        }
    }

}
