import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Everything the model can currently see, in one place.

    This is a mirror, not a second store: the rows are composed from the real
    attachments, the real project, the real open file and the real browser
    page. Removing something here removes the actual thing, so the panel can
    never drift out of step with the composer.
*/
Item {
    id: root
    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property var groups: dock ? dock.contextItems : []
    readonly property real fraction: bridge ? bridge.contextFraction : 0

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Context"
            detail: bridge ? bridge.contextCompact : ""
            detailFont: "mono"

            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "paperclip"
                tooltip: "Attach a file"
                onClicked: if (bridge) bridge.attachFile()
            }
        }

        // The window meter, stated once, where the contents are listed.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            visible: root.fraction > 0

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                anchors.topMargin: Theme.s2
                spacing: Theme.s1

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: "Context window"
                        color: Theme.textMuted
                        font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                    }
                    Text {
                        text: Math.round(root.fraction * 100) + "%"
                        color: root.fraction > 0.9 ? Theme.warning : Theme.textMuted
                        font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                    }
                }
                Meter { Layout.fillWidth: true; value: root.fraction }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            visible: bridge && bridge.contextOmittedTurns > 0

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                spacing: Theme.s2
                Icon {
                    name: "info"
                    ink: Theme.textMuted
                    Layout.preferredWidth: 12; Layout.preferredHeight: 12
                }
                Text {
                    Layout.fillWidth: true
                    text: bridge ? bridge.contextCompactionLabel : ""
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                    wrapMode: Text.Wrap
                }
            }
        }

        ListView {
            id: list
            objectName: "contextGroups"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.groups.length > 0
            clip: true
            model: root.groups
            spacing: Theme.s2
            topMargin: Theme.s2
            bottomMargin: Theme.s4
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true
            ScrollBar.vertical: WScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Column {
                required property var modelData
                width: list.width
                spacing: 1

                Row {
                    x: Theme.s3
                    spacing: Theme.s2
                    bottomPadding: Theme.s1
                    Icon {
                        name: modelData.icon
                        ink: Theme.textDisabled
                        width: 11; height: 11
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    SectionLabel {
                        text: modelData.title
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Repeater {
                    model: modelData.items
                    delegate: Item {
                        id: entry
                        required property var modelData
                        width: list.width
                        height: Theme.rowHeight

                        Rectangle {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s2
                            anchors.rightMargin: Theme.s2
                            radius: Theme.r2
                            color: hover.hovered ? Theme.surfaceHover : "transparent"
                        }
                        HoverHandler { id: hover }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s3
                            anchors.rightMargin: Theme.s3
                            spacing: Theme.s2

                            Icon {
                                Layout.preferredWidth: 13; Layout.preferredHeight: 13
                                name: Theme.kindIcon(entry.modelData.kind)
                                ink: Theme.textMuted
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 0
                                Text {
                                    Layout.fillWidth: true
                                    text: entry.modelData.label
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                    elide: Text.ElideMiddle
                                }
                                Text {
                                    Layout.fillWidth: true
                                    visible: !!entry.modelData.detail
                                    text: entry.modelData.detail
                                    color: Theme.textDisabled
                                    font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                                    elide: Text.ElideLeft
                                }
                            }
                            Text {
                                readonly property int tokens: entry.modelData.tokens || 0
                                visible: tokens > 0 && !(hover.hovered || removeButton.visualFocus)
                                text: tokens > 999 ? (tokens / 1000).toFixed(1) + "k" : String(tokens)
                                color: Theme.textDisabled
                                font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                            }
                            IconButton {
                                id: removeButton
                                Layout.preferredWidth: Theme.controlSmall
                                Layout.preferredHeight: Theme.controlSmall
                                iconSize: 11
                                visible: !!entry.modelData.removable
                                opacity: hover.hovered || visualFocus ? 1 : 0
                                iconName: "close"
                                tooltip: "Remove from context"
                                Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                                onClicked: if (root.dock) root.dock.removeContext(entry.modelData.id)
                            }
                        }
                    }
                }
            }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.groups.length === 0
            iconName: "layers"
            title: "Nothing attached"
            detail: "Files, folders, captures, an open file or a web page appear here once the model can see them."
        }
    }
}
