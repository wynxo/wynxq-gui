import QtQuick
import QtQuick.Controls

/*!
    A user turn is the task brief: quiet, full-width and easy to edit. Actions
    stay out of the reading path at rest, but remain in the keyboard focus chain
    so focus reveals the same controls as pointer hover.
*/
Item {
    id: root
    property string body: ""
    property var attachments: []
    property int row: -1
    signal edited(string text)

    implicitHeight: card.height
    property bool editing: false
    function resetTransientState() {
        editing = false;
        editor.text = "";
        text.deselect();
        messageMenu.close();
    }
    function startEditing() {
        editor.text = root.body;
        root.editing = true;
        editor.forceActiveFocus();
    }
    Accessible.role: Accessible.StaticText
    Accessible.name: "You said: " + root.body

    Rectangle {
        id: card
        width: parent.width
        height: root.editing ? editColumn.implicitHeight + Theme.s4 * 2
                             : Math.max(44, displayColumn.implicitHeight + Theme.s3 * 2)
        radius: Theme.r3
        color: Theme.surfaceRaised
        border.width: 1
        border.color: root.editing ? Theme.accentEdge : Theme.borderSubtle

        Column {
            id: displayColumn
            visible: !root.editing
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.s3
            spacing: root.attachments.length > 0 ? Theme.s2 : 0

            TextEdit {
                id: text
                width: Math.max(0, parent.width - 62)
                text: root.body
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: Theme.textPrimary
                selectionColor: Theme.accent
                selectedTextColor: Theme.onAccent
                font.family: Theme.sansFamily
                font.pixelSize: Theme.body
            }

            Flow {
                id: sentContext
                objectName: "sentAttachments"
                width: parent.width
                spacing: Theme.s2
                visible: root.attachments.length > 0
                height: visible ? implicitHeight : 0

                Repeater {
                    model: root.attachments
                    delegate: Item {
                        id: attachment
                        required property var modelData
                        readonly property bool imageAttachment: !!modelData.image
                        width: imageAttachment ? 88 : Math.min(filePill.implicitWidth, sentContext.width)
                        height: imageAttachment ? 58 : 28

                        Rectangle {
                            visible: attachment.imageAttachment
                            anchors.fill: parent
                            radius: Theme.r2
                            color: Theme.surfaceSunken
                            border.width: 1
                            border.color: Theme.borderSubtle
                            clip: true
                            Image {
                                anchors.fill: parent
                                anchors.margins: 1
                                source: attachment.imageAttachment
                                    ? "data:image/png;base64," + modelData.image : ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                smooth: true
                            }
                            ToolTip.visible: imageHover.hovered
                            ToolTip.text: modelData.title
                            HoverHandler { id: imageHover }
                        }

                        Rectangle {
                            id: filePill
                            visible: !attachment.imageAttachment
                            implicitWidth: Math.min(250, fileRow.implicitWidth + Theme.s3 * 2)
                            width: parent.width
                            height: parent.height
                            radius: Theme.rPill
                            color: Theme.surfaceSunken
                            border.width: 1
                            border.color: Theme.borderSubtle
                            Row {
                                id: fileRow
                                anchors.centerIn: parent
                                spacing: Theme.s2
                                Icon {
                                    name: ContextKinds.icon(modelData.kind)
                                    ink: Theme.textMuted
                                    width: 12; height: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: modelData.title
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily
                                    font.pixelSize: Theme.micro
                                    elide: Text.ElideMiddle
                                    width: Math.min(190, implicitWidth)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            ToolTip.visible: fileHover.hovered
                            ToolTip.text: modelData.subtitle || modelData.path || modelData.title
                            HoverHandler { id: fileHover }
                        }
                    }
                }
            }
        }

        Column {
            id: editColumn
            visible: root.editing
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.s4
            spacing: Theme.s3

            TextArea {
                id: editor
                width: parent.width
                wrapMode: TextEdit.Wrap
                color: Theme.textPrimary
                selectionColor: Theme.accent
                selectedTextColor: Theme.onAccent
                font.family: Theme.sansFamily
                font.pixelSize: Theme.body
                padding: 0
                background: Item {}
                Accessible.name: "Edit your message"
                Keys.onEscapePressed: root.editing = false
            }

            Row {
                spacing: Theme.s2
                anchors.right: parent.right
                WButton {
                    text: "Cancel"
                    variant: "ghost"
                    compactPadding: true
                    onClicked: root.editing = false
                }
                WButton {
                    text: "Run again"
                    variant: "primary"
                    compactPadding: true
                    enabled: editor.text.trim().length > 0
                    onClicked: {
                        root.editing = false;
                        root.edited(editor.text);
                    }
                }
            }
        }

        Row {
            objectName: "messageActions"
            anchors.right: parent.right
            anchors.rightMargin: Theme.s2
            anchors.top: parent.top
            anchors.topMargin: Theme.s2
            spacing: 0
            opacity: root.editing ? 0
                : (hover.hovered || editAction.visualFocus || copyAction.visualFocus ? 1 : 0)
            visible: !root.editing
            Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }

            IconButton {
                id: editAction
                width: 27; height: 27; iconSize: 12
                iconName: "edit"
                tooltip: "Edit and run again"
                onClicked: root.startEditing()
            }
            IconButton {
                id: copyAction
                width: 27; height: 27; iconSize: 12
                iconName: "copy"
                tooltip: "Copy"
                onClicked: if (bridge) bridge.copyText(root.body)
            }
        }
    }

    WMenu {
        id: messageMenu
        preferredEdge: "above"
        menuWidth: 210
        items: [
            { id: "edit", label: "Edit and run again", icon: "edit" },
            { id: "copy", label: "Copy message", icon: "copy" },
        ]
        onPicked: function(id) {
            if (id === "edit") root.startEditing();
            else if (id === "copy" && bridge) bridge.copyText(root.body);
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        propagateComposedEvents: true
        onClicked: function(mouse) {
            messageMenu.anchorX = mouse.x;
            messageMenu.open();
        }
    }

    HoverHandler { id: hover }
}
