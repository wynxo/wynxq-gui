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
    signal commandInvoked(string action)
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
    readonly property bool hasPrompt: input.text.trim().length > 0
    readonly property bool queuePrompt: input.text.trim().toLowerCase().indexOf("/queue ") === 0
    readonly property bool canSend: root.hasPrompt && bridge && bridge.online && !bridge.connecting
    property int slashIndex: 0
    readonly property string slashQuery: input.text.length > 0 && input.text.charAt(0) === "/"
        && input.text.indexOf("\n") < 0 && input.text.indexOf(" ") < 0
        ? input.text.substring(1).toLowerCase() : ""
    readonly property var slashCommands: [
        { name: "model", action: "models", detail: "Choose or manage the local model", icon: "layers" },
        { name: "settings", action: "settings", detail: "Open settings", icon: "sliders" },
        { name: "project", action: "project", detail: "Choose a project folder", icon: "folder" },
        { name: "files", action: "files", detail: "Open project files", icon: "folderOpen", workOnly: true },
        { name: "terminal", action: "terminal-panel", detail: "Open the project shell", icon: "terminal", workOnly: true },
        { name: "changes", action: "changes", detail: "Review uncommitted work", icon: "branch", workOnly: true },
        { name: "screen", action: "screenshot", detail: "Attach a screenshot", icon: "camera" },
        { name: "work", action: "mode-work", detail: "Switch this blank task to Work", icon: "code" },
        { name: "chat", action: "mode-chat", detail: "Switch this blank task to Chat", icon: "chat" },
        { name: "clear", action: "clear", detail: "Clear this task", icon: "trash" },
        { name: "stop", action: "stop", detail: "Stop the current run", icon: "stop" },
    ]
    readonly property var slashMatches: {
        if (!root.slashQuery && input.text !== "/") return [];
        var out = [];
        for (var i = 0; i < slashCommands.length; i++) {
            var item = slashCommands[i];
            if (item.workOnly && !root.workMode) continue;
            if (!root.homeMode && (item.action === "mode-work" || item.action === "mode-chat")) continue;
            if (!root.slashQuery || item.name.indexOf(root.slashQuery) === 0) out.push(item);
        }
        return out.slice(0, 5);
    }

    function runSlash(index) {
        if (!slashMatches.length) return false;
        var at = Math.max(0, Math.min(slashMatches.length - 1, index));
        var action = slashMatches[at].action;
        input.text = "";
        slashIndex = 0;
        root.commandInvoked(action);
        return true;
    }

    function send() {
        if (!canSend) return;
        root.submitted(input.text);
        // clear() also resets any partial input-method state.
        input.clear();
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
        edgeColor: input.activeFocus ? Theme.accentEdge : Theme.border

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
                            readonly property bool included: modelData.enabled !== false
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
                                interactive: true
                                selected: attachment.included
                                tone: attachment.included ? Theme.accent : Theme.textDisabled
                                ToolTip.visible: hovered
                                ToolTip.text: (attachment.included ? "Included in the next message" : "Held for a later message")
                                    + (modelData.subtitle ? " · " + modelData.subtitle : "")
                                    + (modelData.tokens ? " · ≈" + modelData.tokens + " tokens" : "")
                                onClicked: if (bridge) bridge.setAttachmentEnabled(modelData.id, !attachment.included)
                                onRemoved: if (bridge) bridge.removeAttachment(modelData.id)
                            }

                            Rectangle {
                                visible: attachment.isImage
                                anchors.fill: parent
                                radius: Theme.r2
                                color: Theme.surfaceSunken
                                opacity: attachment.included ? 1.0 : 0.46
                                Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
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
                                    id: imagePreviewHit
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: preview.open()
                                }
                            }

                            AbstractButton {
                                id: includeImage
                                visible: attachment.isImage
                                z: 4
                                width: Theme.controlSmall; height: Theme.controlSmall
                                anchors.left: parent.left
                                anchors.bottom: parent.bottom
                                anchors.margins: Theme.s1
                                hoverEnabled: true
                                focusPolicy: Qt.StrongFocus
                                Accessible.name: attachment.included ? "Hold image for a later message" : "Include image in next message"
                                onClicked: if (bridge) bridge.setAttachmentEnabled(modelData.id, !attachment.included)
                                background: Item {
                                    GlassSurface {
                                        anchors.centerIn: parent
                                        width: Theme.s5; height: Theme.s5
                                        radius: Theme.rPill
                                        tint: attachment.included ? Theme.accent : Theme.glassTintStrong
                                        fillOpacity: attachment.included ? 0.84 : 0.76
                                        strongEdge: true
                                        active: includeImage.visualFocus
                                        edgeColor: includeImage.visualFocus ? Theme.accentEdge : Theme.glassEdgeStrong
                                    }
                                }
                                contentItem: Icon {
                                    anchors.centerIn: parent
                                    width: 10; height: 10
                                    name: attachment.included ? "check" : "plus"
                                    ink: attachment.included ? Theme.onAccent : Theme.textSecondary
                                }
                                ToolTip.visible: hovered
                                ToolTip.text: attachment.included ? "Included now" : "Held for later"
                            }

                            AbstractButton {
                                id: removeImage
                                visible: attachment.isImage
                                z: 4
                                width: Theme.controlSmall; height: Theme.controlSmall
                                anchors.top: parent.top
                                anchors.right: parent.right
                                anchors.margins: Theme.s1
                                hoverEnabled: true
                                focusPolicy: Qt.StrongFocus
                                opacity: imagePreviewHit.containsMouse || hovered || visualFocus ? 1 : 0
                                Accessible.name: "Remove " + modelData.title
                                onClicked: if (bridge) bridge.removeAttachment(modelData.id)
                                background: Item {
                                    GlassSurface {
                                        anchors.centerIn: parent
                                        width: Theme.s5; height: Theme.s5
                                        radius: Theme.rPill
                                        tint: removeImage.hovered ? Theme.textPrimary : Theme.glassTintStrong
                                        fillOpacity: removeImage.hovered ? 0.94 : 0.82
                                        strongEdge: true
                                        active: removeImage.visualFocus
                                        edgeColor: removeImage.visualFocus ? Theme.accentEdge : Theme.glassEdgeStrong
                                    }
                                }
                                contentItem: Icon {
                                    anchors.centerIn: parent
                                    width: 10; height: 10
                                    name: "close"
                                    ink: removeImage.hovered ? Theme.textInverse : Theme.textPrimary
                                }
                                Behavior on opacity {
                                    enabled: !Theme.reducedMotion
                                    NumberAnimation { duration: Theme.fast }
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
                    onTextChanged: {
                        root.slashIndex = 0;
                        if (bridge) bridge.setDraft(text);
                    }
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

                    Keys.priority: Keys.BeforeItem
                    Keys.onPressed: function(event) {
                        // Consume plain Enter before TextArea can turn it into a newline.
                        // Shift+Enter is intentionally left to TextArea for multiline input.
                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            if (event.modifiers & Qt.ShiftModifier) {
                                event.accepted = false;
                                return;
                            }
                            // Some Linux input-method stacks can report a
                            // composing state beyond an actual preedit. Only
                            // defer Enter while there is real partial IME text
                            // that still needs to be committed.
                            if (input.preeditText.length > 0) {
                                event.accepted = false;
                                return;
                            }
                            if (root.slashMatches.length) root.runSlash(root.slashIndex);
                            else root.send();
                            event.accepted = true;
                            return;
                        }
                        if (root.slashMatches.length && event.key === Qt.Key_Down) {
                            root.slashIndex = Math.min(root.slashMatches.length - 1, root.slashIndex + 1);
                            event.accepted = true;
                        } else if (root.slashMatches.length && event.key === Qt.Key_Up) {
                            root.slashIndex = Math.max(0, root.slashIndex - 1);
                            event.accepted = true;
                        } else if (event.key === Qt.Key_V
                                && (event.modifiers & Qt.ControlModifier)
                                && !(event.modifiers & Qt.ShiftModifier)) {
                            // Normal Ctrl+V remains normal text paste unless
                            // the clipboard currently holds an image.
                            event.accepted = !!(bridge && bridge.pasteImage());
                        } else if (event.key === Qt.Key_V
                                && (event.modifiers & Qt.ControlModifier)
                                && (event.modifiers & Qt.ShiftModifier)) {
                            event.accepted = !!(bridge && bridge.pasteImage());
                        }
                    }
                }
            }


            GlassSurface {
                id: slashSurface
                Layout.fillWidth: true
                Layout.preferredHeight: visible ? slashColumn.implicitHeight + Theme.s2 : 0
                visible: root.slashMatches.length > 0
                radius: Theme.r2
                tint: Theme.glassTintStrong
                fillOpacity: 0.82
                strongEdge: true
                sheen: true

                Column {
                    id: slashColumn
                    width: parent.width
                    topPadding: Theme.s1
                    bottomPadding: Theme.s1
                    Repeater {
                        model: root.slashMatches
                        delegate: AbstractButton {
                            id: slashRow
                            required property var modelData
                            required property int index
                            width: slashColumn.width
                            height: 34
                            hoverEnabled: true
                            onClicked: root.runSlash(index)
                            background: Rectangle {
                                radius: Theme.r1
                                color: slashRow.index === root.slashIndex || slashRow.hovered
                                    ? Theme.surfaceSelected : "transparent"
                            }
                            contentItem: RowLayout {
                                spacing: Theme.s2
                                Icon {
                                    Layout.leftMargin: Theme.s3
                                    Layout.preferredWidth: 13; Layout.preferredHeight: 13
                                    name: slashRow.modelData.icon
                                    ink: slashRow.index === root.slashIndex ? Theme.accent : Theme.textMuted
                                }
                                Text {
                                    text: "/" + slashRow.modelData.name
                                    color: Theme.textPrimary
                                    font.family: Theme.monoFamily
                                    font.pixelSize: Theme.caption
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: slashRow.modelData.detail
                                    color: Theme.textMuted
                                    font.family: Theme.sansFamily
                                    font.pixelSize: Theme.micro
                                    elide: Text.ElideRight
                                }
                            }
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
                    readonly property bool stopping: !!(bridge && bridge.busy && !root.hasPrompt)
                    iconName: stopping ? "stop" : "arrow"
                    Layout.preferredWidth: Theme.control
                    Layout.preferredHeight: Theme.control
                    iconSize: 14
                    tint: stopping ? Theme.textPrimary
                        : sendButton.enabled ? Theme.onAccent : Theme.textMuted
                    activeTint: tint
                    tooltip: bridge && bridge.busy
                        ? (stopping ? "Stop" : (root.queuePrompt ? "Queue after this turn" : "Steer current turn"))
                        : "Send"
                    shortcut: stopping ? "Esc" : "Enter"
                    enabled: stopping || root.canSend
                    scale: down ? 0.90 : hovered && enabled ? 1.025 : 1.0
                    onClicked: stopping ? bridge.stop() : root.send()
                    Behavior on scale {
                        enabled: !Theme.reducedMotion
                        NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
                    }
                    background: Rectangle {
                        radius: width / 2
                        color: sendButton.stopping
                            ? (sendButton.hovered ? Theme.surfacePressed : Theme.surfaceSelected)
                            : sendButton.enabled
                                ? (sendButton.hovered ? Theme.accentHover : Theme.accent)
                                : Theme.surfaceRaised
                        border.width: sendButton.visualFocus ? 2 : 1
                        border.color: sendButton.visualFocus ? Theme.accentEdge
                            : sendButton.enabled ? Theme.borderStrong : Theme.borderSubtle
                        Behavior on color {
                            enabled: !Theme.reducedMotion
                            ColorAnimation { duration: Theme.fast }
                        }
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
