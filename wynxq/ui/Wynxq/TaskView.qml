import QtQuick
import QtQuick.Controls

/*!
    The conversation: a work stream, scrolled.

    The jump button appears only once you have scrolled away from the newest
    output, so following a live run costs nothing and reading back does not
    fight you.
*/
Item {
    id: root
    signal linkClicked(string link)

    function jumpToEnd() { list.jumpToEnd(); }

    MessageList {
        id: list
        anchors.fill: parent
        model: bridge ? bridge.messageModel : null
        onLinkClicked: function(link) { root.linkClicked(link); }
    }

    // ------------------------------------------------------ jump to latest
    AbstractButton {
        id: jump
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.s2
        implicitHeight: Theme.controlSmall
        implicitWidth: jumpRow.implicitWidth + Theme.s3 * 2
        hoverEnabled: true
        opacity: !list.following && !list.atBottom ? 1 : 0
        visible: opacity > 0
        Accessible.name: "Jump to the latest message"
        onClicked: list.jumpToEnd()
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }

        background: Rectangle {
            radius: Theme.rPill
            color: jump.hovered ? Theme.surfaceSelected : Theme.surfaceRaised
            border.width: 1
            border.color: Theme.borderStrong
            Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
        }
        contentItem: Row {
            id: jumpRow
            anchors.centerIn: parent
            spacing: Theme.s2
            Icon { name: "down"; ink: Theme.textSecondary; width: 12; height: 12; anchors.verticalCenter: parent.verticalCenter }
            Text {
                text: "Latest"
                color: Theme.textSecondary
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
    }
}
