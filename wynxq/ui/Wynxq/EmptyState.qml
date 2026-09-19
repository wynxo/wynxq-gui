import QtQuick
import QtQuick.Layouts

/*!
    What a panel says when it has nothing to show.

    One line of what is happening, one line of what to do about it, and — when
    there is something to do — one button. Never a shrug.
*/
Item {
    id: root
    property string iconName: "info"
    property string title: ""
    property string detail: ""
    property string actionText: ""
    property bool tone: false            // true tints the mark as a warning
    signal actionInvoked()

    Accessible.role: Accessible.StaticText
    Accessible.name: title + (detail ? ". " + detail : "")

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - Theme.s6 * 2, 280)
        spacing: Theme.s3

        Icon {
            Layout.alignment: Qt.AlignHCenter
            name: root.iconName
            ink: root.tone ? Theme.warning : Theme.textDisabled
            width: 20; height: 20
        }

        Text {
            Layout.fillWidth: true
            text: root.title
            horizontalAlignment: Text.AlignHCenter
            color: Theme.textSecondary
            font.family: Theme.sansFamily
            font.pixelSize: Theme.label
            wrapMode: Text.WordWrap
        }

        Text {
            Layout.fillWidth: true
            visible: root.detail !== ""
            text: root.detail
            horizontalAlignment: Text.AlignHCenter
            color: Theme.textMuted
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap
            lineHeight: 1.4
        }

        WButton {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: Theme.s1
            visible: root.actionText !== ""
            text: root.actionText
            compactPadding: true
            onClicked: root.actionInvoked()
        }
    }
}
