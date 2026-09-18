import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    One command box for Chat and Work.

    The prompt gets the space. Context, project, model and run controls live on
    one quiet toolbar underneath it. The fresh-task surface has a satin glass
    reflection over an opaque base. In conversations the material appears on
    focus, keeping long reading sessions quiet.
*/
Item {
    id: root
    signal submitted(string text)
    signal openModelManager()

    property alias text: input.text
    property int maxHeight: 220
    readonly property real chromeHeight: Theme.s3 * 2 + toolbar.implicitHeight + content.spacing
        + (hasAttachments ? attachmentScroll.Layout.preferredHeight + content.spacing : 0)
    implicitHeight: shell.height

    function focusInput() { input.forceActiveFocus(); }
    function showModelPicker() { modelButton.showPicker(); }
    function insert(prompt) {
        input.text = prompt;
        input.cursorPosition = input.length;
        input.forceActiveFocus();
    }

    Connections {
        target: bridge
        function onDraftChanged() { input.text = bridge.draftText; }
    }
    Component.onCompleted: if (bridge) input.text = bridge.draftText

    readonly property string mode: bridge ? bridge.taskMode : "chat"
    readonly property bool workMode: root.mode === "work"
    readonly property bool homeMode: bridge && !bridge.hasMessages
    readonly property bool hasAttachments: bridge && bridge.attachmentCount > 0
    readonly property bool tight: root.width < 560
    readonly property bool veryTight: root.width < 430
    readonly property bool canSend: input.text.trim().length > 0 && bridge && bridge.online && !bridge.connecting

    function send() {
        if (!canSend || (bridge && bridge.busy)) return;
        root.submitted(input.text);
        input.text = "";
    }

    GlassSurface {
        id: shell
        width: parent.width
        height: content.implicitHeight + Theme.s3 * 2
        radius: Theme.r4
        tint: input.activeFocus ? Theme.glassTintStrong : Theme.surfaceRaised
        fillOpacity: input.activeFocus ? Theme.glassStrongOpacity : 1.0
        solid: true
        autoGlass: false
        glassEnabled: root.homeMode || input.activeFocus
        elevated: input.activeFocus
        strongEdge: input.activeFocus
        active: input.activeFocus
        sheen: root.homeMode || input.activeFocus
        edgeColor: input.activeFocus ? Theme.accentEdge : Theme.borderStrong

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: Theme.s3
            spacing: Theme.s2

            ScrollView {
                id: attachmentScroll
                objectName: "composerAttachments"
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(88, attachmentFlow.implicitHeight)
                visible: root.hasAttachments
                contentWidth: availableWidth
                contentHeight: attachmentFlow.implicitHeight
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: WScrollBar {}

                Flow {
                    id: attachmentFlow
                    width: attachmentScroll.availableWidth
                    spacing: Theme.s2

                    Repeater {
                        model: bridge ? bridge.attachments : []
                        delegate: Item {
                            id: attachment
                            required property var modelData
                            readonly property bool isImage: !!modelData.image
                            width: isImage ? 70 : Math.min(fileChip.implicitWidth, attachmentFlow.width)
                            height: isImage ? 70 : fileChip.implicitHeight

                            Chip {
                                id: fileChip
                                visible: !attachment.isImage
                                width: parent.width
                                text: modelData.title
                                subtitle: modelData.subtitle
                                iconName: ContextKinds.icon(modelData.kind)
                                removable: true
                                onRemoved: if (bridge) bridge.removeAttachment(modelData.id)
                            }

                            Rectangle {
                                visible: attachment.isImage
                                anchors.fill: parent
                                radius: Theme.r2
                                color: Theme.surfaceSunken
                                border.width: 1
                                border.color: Theme.borderSubtle
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    anchors.margins: 1
                                    source: attachment.isImage ? "data:image/png;base64," + modelData.image : ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    smooth: true
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: preview.open()
                                }
                            }

                            AbstractButton {
                                id: removeImage
                                visible: attachment.isImage
                                z: 4
                                width: 18; height: 18
                                anchors.top: parent.top
                                anchors.right: parent.right
                                anchors.margins: 4
                                hoverEnabled: true
                                Accessible.name: "Remove " + modelData.title
                                onClicked: if (bridge) bridge.removeAttachment(modelData.id)
                                background: GlassSurface {
                                    radius: Theme.rPill
                                    tint: removeImage.hovered ? Theme.textPrimary : Theme.glassTintStrong
                                    fillOpacity: removeImage.hovered ? 0.94 : 0.82
                                    strongEdge: true
                                }
                                contentItem: Text {
                                    text: "×"
                                    color: removeImage.hovered ? Theme.textInverse : Theme.textPrimary
                                    font.family: Theme.sansFamily
                                    font.pixelSize: 13
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                            }

                            Popover {
                                id: preview
                                width: 320
                                height: 238
                                preferredEdge: "above"
                                title: modelData.subtitle || modelData.title
                                Rectangle {
                                    anchors.fill: parent
                                    radius: Theme.r2
                                    color: Theme.surfaceSunken
                                    border.width: 1
                                    border.color: Theme.borderSubtle
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        anchors.margins: 1
                                        source: attachment.isImage ? "data:image/png;base64," + modelData.image : ""
                                        fillMode: Image.PreserveAspectFit
                                        asynchronous: true
                                        smooth: true
                                    }
                                }
                            }
                        }
                    }
                }
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.minimumHeight: root.homeMode ? 48 : 38
                Layout.preferredHeight: Math.min(root.maxHeight,
                    Math.max(root.homeMode ? 48 : 38, input.implicitHeight + Theme.s1))
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical: WScrollBar {}

                TextArea {
                    id: input
                    objectName: "composer"
                    onTextChanged: if (bridge) bridge.setDraft(text)
                    placeholderText: root.workMode
                        ? (bridge && bridge.projectPath
                            ? "Describe what you want done in this project or on the desktop…"
                            : "Describe what you want done on this computer…")
                        : "Ask a question, explain, or brainstorm…"
                    placeholderTextColor: Theme.textMuted
                    color: Theme.textPrimary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.body
                    leftPadding: 2
                    rightPadding: 2
                    topPadding: Theme.s1
                    bottomPadding: Theme.s1
                    background: Item {}
                    Accessible.role: Accessible.EditableText
                    Accessible.name: root.workMode ? "Work request" : "Message to Wynxq GUI"
                    Accessible.description: placeholderText

                    Keys.onReturnPressed: function(event) {
                        if (input.inputMethodComposing) { event.accepted = false; return; }
                        if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return; }
                        root.send(); event.accepted = true;
                    }
                    Keys.onEnterPressed: function(event) {
                        if (input.inputMethodComposing) { event.accepted = false; return; }
                        if (event.modifiers & Qt.ShiftModifier) { event.accepted = false; return; }
                        root.send(); event.accepted = true;
                    }
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_V && (event.modifiers & Qt.ControlModifier)
                                && (event.modifiers & Qt.ShiftModifier)) {
                            if (bridge) bridge.pasteImage();
                            event.accepted = true;
                        }
                    }
                }
            }

            RowLayout {
                id: toolbar
                Layout.fillWidth: true
                spacing: Theme.s1

                AbstractButton {
                    id: addContext
                    Layout.preferredWidth: 30
                    Layout.preferredHeight: 30
                    hoverEnabled: true
                    Accessible.name: "Add context"
                    onClicked: contextMenu.opened ? contextMenu.close() : contextMenu.open()
                    ToolTip.visible: hovered
                    ToolTip.text: "Add files, folders, screenshots or clipboard context"
                    ToolTip.delay: 550
                    background: GlassSurface {
                        radius: Theme.r2
                        tint: Theme.glassTintHover
                        fillOpacity: addContext.hovered || contextMenu.opened ? 0.50 : 0.0
                        outlineVisible: addContext.hovered || contextMenu.opened || addContext.visualFocus
                        active: addContext.visualFocus
                        sheen: addContext.hovered || contextMenu.opened
                    }
                    contentItem: Icon {
                        anchors.centerIn: parent
                        name: "plus"
                        ink: addContext.hovered ? Theme.textPrimary : Theme.textSecondary
                        width: 14; height: 14
                    }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }

                    WMenu {
                        id: contextMenu
                        preferredEdge: "above"
                        menuWidth: 262
                        property string windowTitle: ""
                        onAboutToShow: windowTitle = bridge ? bridge.activeWindowTitle() : ""
                        items: [
                            { id: "file", label: "File…", icon: "file" },
                            { id: "folder", label: "Folder…", icon: "folder" },
                            { id: "clipboard", label: "Clipboard", icon: "clipboard" },
                            { separator: true },
                            { id: "screen", label: "Screenshot", icon: "camera" },
                            { id: "region", label: "Screen region…", icon: "crop" },
                            { id: "window",
                              label: contextMenu.windowTitle
                                     ? "Window: " + contextMenu.windowTitle.substring(0, 22)
                                     : "Active window",
                              icon: "window" },
                            { separator: true, hidden: !(bridge && bridge.attachmentCount > 1) },
                            { id: "clear", label: "Remove all context", icon: "close",
                              hidden: !(bridge && bridge.attachmentCount > 1) },
                        ]
                        onPicked: function(id) {
                            if (!bridge) return;
                            if (id === "file") bridge.attachFile();
                            else if (id === "folder") bridge.attachFolder();
                            else if (id === "clipboard") bridge.attachClipboard();
                            else if (id === "screen") bridge.attachScreenshot();
                            else if (id === "region") bridge.attachRegion();
                            else if (id === "window") bridge.attachWindow();
                            else if (id === "clear") bridge.clearAttachments();
                        }
                    }
                }

                Chip {
                    visible: root.workMode && bridge && bridge.projectPath && !root.veryTight
                    Layout.maximumWidth: root.tight ? 150 : 220
                    text: bridge ? bridge.projectName : ""
                    iconName: "folderOpen"
                    onClicked: if (bridge) bridge.chooseProject()
                    ToolTip.visible: hovered
                    ToolTip.text: bridge ? bridge.projectLabel + " — click to change" : ""
                }

                IconButton {
                    visible: root.workMode && bridge && bridge.projectPath && !root.tight
                    Layout.preferredWidth: 30; Layout.preferredHeight: 30
                    iconSize: 14
                    iconName: "terminal"
                    tooltip: "Terminal"
                    shortcut: "Ctrl+`"
                    active: !!(bridge && bridge.workspaceDock && bridge.workspaceDock.visible
                               && bridge.workspaceDock.tab === "terminal")
                    onClicked: if (bridge && bridge.workspaceDock) bridge.workspaceDock.openTab("terminal")
                }

                Chip {
                    visible: root.workMode && !root.veryTight
                    text: bridge && bridge.desktopEnabled ? "Screen on" : "Screen off"
                    iconName: "cursor"
                    selected: !!(bridge && bridge.desktopEnabled)
                    ToolTip.visible: hovered
                    ToolTip.text: "Screen control is managed in Agent settings"
                }

                Item { Layout.fillWidth: true }

                TokenUsage {
                    id: tokenUsage
                    Layout.maximumWidth: Math.max(100, root.width * 0.4)
                    Layout.rightMargin: Theme.s3
                    Layout.preferredHeight: 30
                    compact: root.tight
                }

                ModelPicker {
                    id: modelButton
                    compact: true
                    onOpenModelManager: root.openModelManager()
                }

                IconButton {
                    id: sendButton
                    objectName: "sendButton"
                    iconName: bridge && bridge.busy ? "stop" : "arrow"
                    Layout.preferredWidth: 30
                    Layout.preferredHeight: 30
                    iconSize: 14
                    tint: bridge && bridge.busy ? Theme.textPrimary
                        : sendButton.enabled ? Theme.onAccent : Theme.textMuted
                    activeTint: tint
                    tooltip: bridge && bridge.busy ? "Stop" : "Send"
                    shortcut: bridge && bridge.busy ? "Esc" : "Enter"
                    enabled: (bridge && bridge.busy) || root.canSend
                    onClicked: bridge && bridge.busy ? bridge.stop() : root.send()
                    background: GlassSurface {
                        radius: Theme.r2
                        glassEnabled: sendButton.enabled
                        tint: bridge && bridge.busy ? Theme.glassTintStrong
                             : sendButton.enabled
                               ? (sendButton.hovered ? Theme.accentHover : Theme.accent)
                               : Theme.glassTint
                        fillOpacity: bridge && bridge.busy ? 0.76
                                   : sendButton.enabled ? 0.94 : 0.38
                        outlineVisible: true
                        active: sendButton.visualFocus
                        strongEdge: sendButton.enabled
                        elevated: sendButton.enabled && sendButton.hovered
                        edgeColor: sendButton.visualFocus ? Theme.accentEdge
                                 : sendButton.enabled ? Theme.alpha(Theme.textPrimary, 0.15)
                                 : Theme.glassEdge
                    }
                }
            }
        }
    }

    DropArea {
        anchors.fill: parent
        onEntered: function(drag) { if (drag.hasUrls) drag.accept(); }
        onDropped: function(drop) {
            if (!bridge || !drop.hasUrls) return;
            for (var i = 0; i < drop.urls.length; i++)
                bridge.attachPath(drop.urls[i].toString());
            drop.accept();
        }
        GlassSurface {
            anchors.fill: parent
            visible: parent.containsDrag
            radius: shell.radius
            tint: Theme.accent
            fillOpacity: 0.13
            strongEdge: true
            edgeColor: Theme.accentEdge
            Text {
                anchors.centerIn: parent
                text: "Drop to attach"
                color: Theme.textPrimary
                font.family: Theme.sansFamily
                font.pixelSize: Theme.label
            }
        }
    }
}
