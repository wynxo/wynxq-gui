import QtQuick
import QtQuick.Layouts
import QtQuick.Window

/*!
    Passive live-status HUD for computer use.

    The global control banner already owns the emergency-stop affordance. This
    panel therefore does one job only: show the current thought and reply in a
    quiet bottom-right card without stealing focus, clicks, or keyboard input
    from the application Wynxq is operating.
*/
Window {
    id: root

    required property var targetScreen
    property bool controlVisible: false
    property string statusText: "Working…"
    property string thoughtText: ""
    property string replyText: ""

    readonly property real edgeMargin: 20
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

    width: Math.min(330, Math.max(260, screenWidth - edgeMargin * 2))
    height: Math.min(214, Math.max(92, content.implicitHeight + 28))
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

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 14
        spacing: 8

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            Text {
                text: "Thinking"
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
                font.weight: Font.DemiBold
            }

            Text {
                Layout.fillWidth: true
                text: root.thoughtText || root.statusText || "Working…"
                color: Theme.textSecondary
                font.family: Theme.sansFamily
                font.pixelSize: Theme.caption
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                maximumLineCount: 3
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            visible: root.replyText.length > 0
            color: Qt.rgba(1, 1, 1, 0.08)
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: root.replyText.length > 0
            spacing: 3

            Text {
                text: "Answer"
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
                font.weight: Font.DemiBold
            }

            Text {
                Layout.fillWidth: true
                text: root.replyText
                color: Theme.textPrimary
                font.family: Theme.sansFamily
                font.pixelSize: Theme.caption
                wrapMode: Text.Wrap
                elide: Text.ElideRight
                maximumLineCount: 3
            }
        }
    }
}
