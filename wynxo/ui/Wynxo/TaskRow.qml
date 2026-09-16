import QtQuick
import QtQuick.Controls

/*! One task in the sidebar: its title, task mode, and — on hover or from the
    keyboard — what you can do with it. */
AbstractButton {
    id: row
    property var entry: ({})
    readonly property bool current: bridge && entry.id === bridge.taskId
    readonly property string mode: entry.mode || "chat"
    signal renameRequested()
    signal deleteRequested()

    height: Theme.rowHeight
    hoverEnabled: true
    Accessible.role: Accessible.ListItem
    Accessible.name: (entry.title || "")
                     + (row.mode === "work" ? ", Work task" : ", Chat task")
                     + (entry.pinned ? ", pinned" : "")
    Accessible.description: entry.preview || ""
    Accessible.selected: current
    onClicked: if (bridge) bridge.openTask(entry.id)

    background: Rectangle {
        radius: Theme.r2
        color: row.current ? Theme.surfaceSelected
             : row.hovered || moreMenu.opened ? Theme.surfaceHover : "transparent"
        border.width: row.visualFocus ? 1 : 0
        border.color: Theme.accentEdge

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 2
            height: row.current ? 16 : 0
            radius: 1
            color: Theme.accent
            Behavior on height { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
        }
    }

    contentItem: Item {
        // Chat is the default and gets no mark; Work gets one because it can
        // operate on the project and desktop instead of only answering.
        Icon {
            id: modeIcon
            visible: row.mode === "work"
            x: Theme.s3
            anchors.verticalCenter: parent.verticalCenter
            name: "cursor"
            ink: row.current ? Theme.textSecondary : Theme.textDisabled
            width: 11; height: 11
        }
        Icon {
            id: pinIcon
            visible: !!row.entry.pinned && !modeIcon.visible
            x: Theme.s3
            anchors.verticalCenter: parent.verticalCenter
            name: "pin"
            ink: Theme.textDisabled
            width: 11; height: 11
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: modeIcon.visible || pinIcon.visible ? Theme.s3 + 17 : Theme.s3
            anchors.right: parent.right
            anchors.rightMargin: 30
            anchors.verticalCenter: parent.verticalCenter
            text: row.entry.title || ""
            elide: Text.ElideRight
            color: row.current ? Theme.textPrimary : Theme.textSecondary
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
            font.weight: row.current ? Font.Medium : Font.Normal
        }
    }

    IconButton {
        id: more
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.verticalCenter: parent.verticalCenter
        width: 26; height: 26; iconSize: 12
        iconName: "moreVertical"
        tooltip: "Task actions"
        opacity: row.hovered || row.visualFocus || moreMenu.opened ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
        onClicked: moreMenu.opened ? moreMenu.close() : moreMenu.open()

        WMenu {
            id: moreMenu
            anchorX: -menuWidth + more.width
            menuWidth: 190
            items: [
                { id: "rename", label: "Rename", icon: "edit" },
                { id: "pin", label: row.entry.pinned ? "Unpin" : "Pin", icon: "pin" },
                { id: "duplicate", label: "Duplicate", icon: "duplicate" },
                { separator: true },
                { id: "delete", label: "Delete", icon: "trash", danger: true },
            ]
            onPicked: function(id) {
                if (!bridge) return;
                if (id === "rename") row.renameRequested();
                else if (id === "pin") bridge.togglePin(row.entry.id);
                else if (id === "duplicate") bridge.duplicateTaskById(row.entry.id);
                else if (id === "delete") row.deleteRequested();
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        anchors.rightMargin: 30
        acceptedButtons: Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onClicked: moreMenu.open()
    }
}
