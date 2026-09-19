import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

/*!
    Compact independent desktop-control HUD. It stays interactive so the user
    can steer a live run without bringing the main Wynxq window forward.
*/
Window {
    id: root

    required property var targetScreen
    property bool controlVisible: false
    property string statusText: "Working…"
    property string thoughtText: ""
    property string replyText: ""
    property int queuedCount: 0
    property string stopShortcut: "Esc"

    signal submitted(string text)
    signal stopRequested()

    readonly property color purple: "#a78bfa"

    transientParent: null
    modality: Qt.NonModal
    screen: targetScreen
    width: Math.min(390, Math.max(320, (targetScreen ? targetScreen.width : 390) - 32))
    height: 292
    x: targetScreen ? targetScreen.virtualX + targetScreen.width - width - 22 : 0
    y: targetScreen ? targetScreen.virtualY + targetScreen.height - height - 22 : 0
    visible: controlVisible && !!targetScreen
    color: "transparent"
    title: "Wynxq control panel"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool

    Rectangle {
        anchors.fill: parent
        radius: 20
        color: Qt.rgba(0.055, 0.047, 0.075, 0.86)
        border.width: 1
        border.color: Qt.rgba(0.68, 0.56, 0.98, 0.58)

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 9

            RowLayout {
                Layout.fillWidth: true
                spacing: 9

                Rectangle {
                    width: 9; height: 9; radius: 5
                    color: root.purple
                    SequentialAnimation on opacity {
                        running: root.controlVisible && !Theme.reducedMotion
                        loops: Animation.Infinite
                        NumberAnimation { from: 0.42; to: 1.0; duration: 560 }
                        NumberAnimation { from: 1.0; to: 0.42; duration: 560 }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: "Wynxq is using your computer"
                        color: Theme.textPrimary
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.label
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        text: root.statusText
                        color: root.purple
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.caption
                        elide: Text.ElideRight
                    }
                }

                Rectangle {
                    visible: root.queuedCount > 0
                    radius: 9
                    color: Qt.rgba(0.66, 0.55, 0.98, 0.14)
                    border.width: 1
                    border.color: Qt.rgba(0.66, 0.55, 0.98, 0.32)
                    implicitWidth: queueLabel.implicitWidth + 12
                    implicitHeight: 24
                    Text {
                        id: queueLabel
                        anchors.centerIn: parent
                        text: root.queuedCount + " queued"
                        color: root.purple
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.micro
                        font.weight: Font.Medium
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 4

                Text {
                    text: root.thoughtText ? "Thinking" : "Live"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.micro
                    font.weight: Font.DemiBold
                }

                Text {
                    Layout.fillWidth: true
                    Layout.maximumHeight: 74
                    text: root.thoughtText || root.statusText
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    wrapMode: Text.Wrap
                    elide: Text.ElideRight
                    maximumLineCount: 4
                }

                Text {
                    visible: root.replyText.length > 0
                    text: "Reply"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.micro
                    font.weight: Font.DemiBold
                }

                Text {
                    visible: root.replyText.length > 0
                    Layout.fillWidth: true
                    Layout.maximumHeight: 52
                    text: root.replyText
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    wrapMode: Text.Wrap
                    elide: Text.ElideRight
                    maximumLineCount: 3
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 7

                TextField {
                    id: steering
                    Layout.fillWidth: true
                    placeholderText: "Steer now · /queue message for later"
                    color: Theme.textPrimary
                    placeholderTextColor: Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    selectByMouse: true
                    background: Rectangle {
                        radius: 11
                        color: Qt.rgba(1, 1, 1, steering.activeFocus ? 0.10 : 0.065)
                        border.width: 1
                        border.color: steering.activeFocus
                            ? Qt.rgba(0.68, 0.56, 0.98, 0.60)
                            : Qt.rgba(1, 1, 1, 0.10)
                    }
                    onAccepted: {
                        var value = text.trim();
                        if (!value) return;
                        root.submitted(value);
                        text = "";
                    }
                }

                Button {
                    text: "Send"
                    enabled: steering.text.trim().length > 0
                    onClicked: {
                        var value = steering.text.trim();
                        if (!value) return;
                        root.submitted(value);
                        steering.text = "";
                    }
                }

                Button {
                    text: root.stopShortcut || "Stop"
                    onClicked: root.stopRequested()
                    ToolTip.visible: hovered
                    ToolTip.text: "Stop desktop control instantly"
                }
            }
        }
    }
}
