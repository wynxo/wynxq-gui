import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*! Errors explain what happened and what to do about it. */
Item {
    id: root
    signal actionInvoked(string action)
    visible: bridge && bridge.error.length > 0
    implicitHeight: visible ? card.height : 0
    Accessible.role: Accessible.AlertMessage
    Accessible.name: bridge ? bridge.errorTitle + ". " + bridge.error : ""

    Rectangle {
        id: card
        width: parent.width
        height: layout.implicitHeight + Theme.s3 * 2
        radius: Theme.r2
        color: Theme.dangerMuted
        border.width: 1
        border.color: Theme.alpha(Theme.danger, 0.4)

        RowLayout {
            id: layout
            anchors.fill: parent
            anchors.margins: Theme.s3
            spacing: Theme.s3

            Icon { name: "warning"; ink: Theme.danger; width: 15; height: 15; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Theme.s2
                Text {
                    Layout.fillWidth: true
                    text: bridge && bridge.errorTitle ? bridge.errorTitle : "Something went wrong"
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.label
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: bridge ? bridge.error : ""
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                    wrapMode: Text.WordWrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                    lineHeight: 1.45
                }
                Row {
                    spacing: Theme.s2
                    visible: bridge && bridge.errorActions.length > 0
                    Repeater {
                        model: bridge ? bridge.errorActions : []
                        delegate: WButton {
                            required property var modelData
                            required property int index
                            text: modelData.label
                            variant: index === 0 ? "secondary" : "ghost"
                            compactPadding: true
                            implicitHeight: Theme.controlSmall
                            onClicked: root.actionInvoked(modelData.action)
                        }
                    }
                }
            }

            IconButton {
                iconName: "close"; tooltip: "Dismiss"
                Layout.alignment: Qt.AlignTop
                width: 26; height: 26; iconSize: 13
                onClicked: if (bridge) bridge.clearError()
            }
        }
    }
}
