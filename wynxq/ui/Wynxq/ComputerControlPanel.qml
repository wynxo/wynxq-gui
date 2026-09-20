import QtQuick
import QtQuick.Layouts
import QtQuick.Window

/*!
    Passive live-status HUD for computer use.

    Current thought, reply and the actual emergency-stop shortcut stay together
    at the bottom right without stealing focus, clicks or keyboard input.
*/
Window {
    id: root

    required property var targetScreen
    property bool controlVisible: false
    property string stopShortcut: "Esc"
    property string statusText: "Working…"
    property string thoughtText: ""
    property string replyText: ""

    readonly property real edgeMargin: 12
    readonly property var workArea: targetScreen && targetScreen.availableGeometry
                                    ? targetScreen.availableGeometry : null
    readonly property real screenX: workArea ? workArea.x
        : (targetScreen && targetScreen.virtualX !== undefined ? targetScreen.virtualX : 0)
    readonly property real screenY: workArea ? workArea.y
        : (targetScreen && targetScreen.virtualY !== undefined ? targetScreen.virtualY : 0)
    readonly property real screenWidth: workArea ? workArea.width
        : (targetScreen && targetScreen.width !== undefined ? targetScreen.width : 390)
    readonly property real screenHeight: workArea ? workArea.height
        : (targetScreen && targetScreen.height !== undefined ? targetScreen.height : 260)

    transientParent: null
    modality: Qt.NonModal
    screen: targetScreen

    width: Math.max(1, Math.min(360, screenWidth - edgeMargin * 2))
    height: Math.min(screenHeight - edgeMargin * 2, Math.max(80, content.implicitHeight + 28))
    x: Math.round(screenX + screenWidth - width - edgeMargin)
    y: Math.round(screenY + screenHeight - height - edgeMargin)

    visible: controlVisible && !!targetScreen
    color: "transparent"
    title: "Wynxq live computer activity"
    flags: Qt.FramelessWindowHint
         | Qt.WindowStaysOnTopHint
         | Qt.Tool
         | Qt.WindowTransparentForInput
         | Qt.WindowDoesNotAcceptFocus

    Rectangle {
        anchors.fill: parent
        radius: 18
        color: Qt.rgba(0.055, 0.047, 0.075, 0.84)
        border.width: 1
        border.color: Qt.rgba(0.68, 0.56, 0.98, 0.46)
    }

    Column {
        id: content
        x: 16; y: 14
        width: parent.width - 32
        spacing: 10

        Column {
            width: parent.width
            spacing: 5
            Text {
                text: root.thoughtText ? "Thinking" : "Computer use"
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
                font.weight: Font.DemiBold
            }
            Item {
                width: parent.width
                height: Math.min(thought.implicitHeight, 72)
                clip: true
                Text {
                    id: thought
                    width: parent.width
                    y: Math.min(0, parent.height - implicitHeight)
                    text: root.thoughtText || root.statusText || "Working…"
                    textFormat: Text.PlainText
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.FixedHeight
                    lineHeight: 18
                }
            }
        }
        Rectangle {
            width: parent.width; height: 1
            visible: root.replyText.length > 0
            color: Qt.rgba(1, 1, 1, 0.08)
        }
        Column {
            width: parent.width
            visible: root.replyText.length > 0
            spacing: 5
            Text {
                text: "Answer"
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
                font.weight: Font.DemiBold
            }
            Item {
                width: parent.width
                // Preserve the final paragraph spacing while clipping on a line boundary.
                height: Math.min(answer.implicitHeight, 108 + answer.implicitHeight % 18)
                clip: true
                Text {
                    id: answer
                    width: parent.width
                    y: Math.min(0, parent.height - implicitHeight)
                    text: root.replyText
                    textFormat: Text.MarkdownText
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.FixedHeight
                    lineHeight: 18
                }
            }
        }
        Rectangle {
            width: parent.width; height: 1
            color: Qt.rgba(1, 1, 1, 0.08)
        }
        Row {
            width: parent.width
            spacing: 7
            Rectangle {
                width: 6; height: 6; radius: 3
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.accent
            }
            Text {
                text: "Wynxq · " + (root.stopShortcut || "Esc") + " to stop"
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
                textFormat: Text.PlainText
            }
        }
    }
}
