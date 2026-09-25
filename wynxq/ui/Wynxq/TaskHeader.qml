import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A thin workspace title bar.

    Left: where you are — the panel toggle, product, project and task.
    Right: what Work may do — Chat / Work, Work autonomy, run state,
    system status, workspace dock and the overflow menu.

    Chat / Work is live task state rather than a one-time onboarding choice.
    An idle task can move between conversation-only Chat and local Work without
    starting over. Work autonomy is visible beside the mode so there is no
    hidden difference between Manual, Safe, Auto and Full.
*/
Item {
    id: root
    property bool sidebarCollapsed: false
    property bool drawerOpen: false
    property bool dockAvailable: true
    property bool dockOpen: false
    signal toggleSidebar()
    signal toggleDock()
    signal renameRequested()
    signal openSettings()
    signal openCommandPalette()
    signal openAgentSettings()
    signal openShortcuts()
    signal clearRequested()
    signal modeRequested(string mode)

    implicitHeight: Theme.headerHeight

    function showSystem() { system.open(); }

    readonly property bool homeMode: bridge && !bridge.hasMessages
    readonly property bool needsAttention: bridge && !bridge.online
    readonly property bool connecting: bridge && bridge.connectionState === "connecting"
    readonly property string resolvedMode: bridge ? bridge.taskMode : "chat"
    readonly property bool canChooseMode: !!(bridge && !bridge.busy && !bridge.connecting)
    readonly property bool roomy: root.width > 820

    function requestMode(value) {
        if ((value !== "chat" && value !== "work") || !root.canChooseMode) return;
        root.modeRequested(value);
    }

    function permissionLabel(mode) {
        if (mode === "manual") return "Ask";
        if (mode === "safe") return "Safe";
        if (mode === "auto") return "Auto";
        if (mode === "full") return "Full";
        return "Safe";
    }

    function permissionDetail(mode) {
        if (mode === "manual") return "Ask before every command and desktop action.";
        if (mode === "safe") return "Read and inspect freely; ask before commands and input that change state.";
        if (mode === "auto") return "Code, run and test unattended; ask only before destructive commands.";
        if (mode === "full") return "Full autopilot. Never ask, including for destructive commands.";
        return "";
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.background
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.borderSubtle
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.s2
        anchors.rightMargin: Theme.s2
        spacing: Theme.s1

        IconButton {
            objectName: "headerSidebarToggle"
            visible: false // Collapsed navigation is restored from the lower-left affordance.
            Layout.preferredWidth: 30
            Layout.preferredHeight: 30
            iconSize: 14
            iconName: "panelLeft"
            tooltip: "Show sidebar"
            shortcut: "Ctrl+B"
            onClicked: root.toggleSidebar()
        }

        // ---------------------------------------------------- task context
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: root.sidebarCollapsed && !root.drawerOpen ? Theme.s1 : Theme.s2
            spacing: Theme.s2

            AbstractButton {
                id: projectButton
                objectName: "projectButton"
                leftPadding: 10
                rightPadding: 10
                topPadding: 0
                bottomPadding: 0
                visible: bridge && bridge.projectName
                readonly property real budget: Math.max(110, Math.min(230, root.width * 0.24))
                implicitHeight: 30
                implicitWidth: Math.min(projectLabel.implicitWidth + 9 + Theme.s1 + leftPadding + rightPadding, budget)
                Layout.maximumWidth: budget
                hoverEnabled: true
                Accessible.name: bridge ? "Project " + bridge.projectName : ""
                onClicked: projectMenu.opened ? projectMenu.close() : projectMenu.open()
                background: GlassSurface {
                    radius: Theme.r1
                    solid: false
                    glassEnabled: projectButton.hovered || projectMenu.opened || projectButton.visualFocus
                    tint: Theme.glassTintHover
                    fillOpacity: projectButton.hovered || projectMenu.opened ? 0.46 : 0.0
                    outlineVisible: projectButton.hovered || projectMenu.opened || projectButton.visualFocus
                    strongEdge: projectMenu.opened || projectButton.visualFocus
                    active: projectButton.visualFocus
                    sheen: projectButton.hovered || projectMenu.opened
                    edgeColor: projectButton.visualFocus ? Theme.accentEdge : Theme.glassEdgeStrong
                }
                contentItem: Row {
                    id: projectRow
                    spacing: Theme.s1
                    clip: true
                    Text {
                        id: projectLabel
                        objectName: "projectButtonLabel"
                        anchors.verticalCenter: parent.verticalCenter
                        text: bridge ? bridge.projectName : ""
                        color: Theme.textMuted
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.caption
                        elide: Text.ElideMiddle
                        width: Math.max(0, projectButton.availableWidth - 9 - projectRow.spacing)
                    }
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "down"
                        ink: Theme.textDisabled
                        width: 9
                        height: 9
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    cursorShape: Qt.PointingHandCursor
                }

                WMenu {
                    id: projectMenu
                    menuWidth: 250
                    property var recents: bridge ? bridge.recentProjects : []
                    onAboutToShow: recents = bridge ? bridge.recentProjects : []
                    items: {
                        var list = [{ id: "choose", label: "Open folder…", icon: "folder" }];
                        if (recents.length) {
                            list.push({ separator: true });
                            for (var i = 0; i < Math.min(recents.length, 5); i++)
                                list.push({ id: "recent:" + recents[i].path, label: recents[i].name, icon: "clock" });
                        }
                        list.push({ separator: true });
                        list.push({ id: "files", label: "Show files", icon: "folderOpen", shortcut: "Ctrl+Shift+E" });
                        list.push({ id: "reveal", label: "Reveal in file manager", icon: "launch" });
                        list.push({ id: "copy", label: "Copy path", icon: "copy" });
                        list.push({ id: "clear", label: "Close project", icon: "close" });
                        return list;
                    }
                    onPicked: function(id) {
                        if (!bridge) return;
                        if (id === "choose") bridge.chooseProject();
                        else if (id === "files" && bridge.workspaceDock) bridge.workspaceDock.openTab("files");
                        else if (id === "reveal") bridge.revealPath(bridge.projectPath);
                        else if (id === "copy") bridge.copyProjectPath();
                        else if (id === "clear") bridge.clearProject();
                        else if (id.indexOf("recent:") === 0) bridge.openProject(id.substring(7));
                    }
                }
            }

            Text {
                visible: !root.homeMode && bridge && bridge.taskId
                text: "/"
                color: Theme.textDisabled
                font.family: Theme.sansFamily
                font.pixelSize: Theme.caption
            }

            AbstractButton {
                id: titleButton
                visible: !root.homeMode
                enabled: !!(bridge && bridge.taskId)
                Layout.fillWidth: true
                Layout.maximumWidth: Math.max(130, root.width * 0.34)
                implicitHeight: 26
                hoverEnabled: true
                Accessible.name: "Rename this task"
                onClicked: root.renameRequested()
                background: GlassSurface {
                    radius: Theme.r1
                    solid: false
                    glassEnabled: (titleButton.hovered && titleButton.enabled) || titleButton.visualFocus
                    tint: Theme.glassTintHover
                    fillOpacity: titleButton.hovered && titleButton.enabled ? 0.44 : 0.0
                    outlineVisible: (titleButton.hovered && titleButton.enabled) || titleButton.visualFocus
                    strongEdge: titleButton.visualFocus
                    active: titleButton.visualFocus
                    sheen: titleButton.hovered && titleButton.enabled
                    edgeColor: titleButton.visualFocus ? Theme.accentEdge : Theme.glassEdgeStrong
                }
                contentItem: Text {
                    leftPadding: Theme.s1
                    rightPadding: Theme.s1
                    text: bridge ? bridge.taskTitle : ""
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.label
                    font.weight: Font.Medium
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    cursorShape: titleButton.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                }
            }

            Item { Layout.fillWidth: true }
        }

        // ------------------------------------------------ Chat / Work mode
        Rectangle {
            id: modeSurface
            objectName: "modeSurface"
            Layout.preferredHeight: 30
            Layout.preferredWidth: modeRow.implicitWidth + 6
            radius: Theme.r2
            color: Theme.surfaceSunken
            border.width: 1
            border.color: Theme.borderSubtle

            Row {
                id: modeRow
                anchors.centerIn: parent
                spacing: 2

                Repeater {
                    model: [
                        { id: "chat", label: "Chat", icon: "chat", hint: "Conversation only. No commands, project tools or desktop actions." },
                        { id: "work", label: "Work", icon: "code", hint: "Coding and local tools. Autonomy is controlled separately." },
                    ]
                    delegate: AbstractButton {
                        id: choice
                        required property var modelData
                        objectName: "modeChoice_" + modelData.id
                        width: 68
                        height: 24
                        padding: 0
                        enabled: root.canChooseMode
                        hoverEnabled: true
                        readonly property bool chosen: root.resolvedMode === modelData.id
                        Accessible.name: modelData.label + " mode"
                        Accessible.description: modelData.hint
                        Accessible.checked: chosen
                        onClicked: root.requestMode(modelData.id)
                        ToolTip.visible: hovered
                        ToolTip.text: modelData.hint
                        ToolTip.delay: Theme.tooltipDelay
                        background: GlassSurface {
                            radius: Theme.r1
                            solid: choice.chosen
                            autoGlass: false
                            glassEnabled: choice.hovered || choice.visualFocus
                            sheen: choice.hovered
                            strongEdge: choice.visualFocus
                            tint: choice.chosen ? Theme.surfaceSelected : Theme.glassTintHover
                            fillOpacity: choice.chosen ? 1 : choice.hovered && choice.enabled ? 0.42 : 0
                            outlineVisible: choice.chosen || choice.visualFocus
                            edgeColor: choice.visualFocus ? Theme.accentEdge : Theme.borderSubtle
                        }
                        contentItem: Item {
                            Row {
                                id: choiceContent
                                anchors.centerIn: parent
                                spacing: Theme.s1
                                Icon {
                                    name: choice.modelData.icon
                                    ink: choice.chosen ? Theme.textPrimary : Theme.textMuted
                                    width: 12
                                    height: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: choice.modelData.label
                                    color: choice.chosen ? Theme.textPrimary : Theme.textSecondary
                                    font.family: Theme.sansFamily
                                    font.pixelSize: Theme.caption
                                    font.weight: choice.chosen ? Font.DemiBold : Font.Normal
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.NoButton
                            cursorShape: choice.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        }
                    }
                }
            }
        }

        // Work autonomy is intentionally adjacent to Work mode. It is not a
        // hidden setting because it changes what the next command may do.
        AbstractButton {
            id: autonomyButton
            visible: root.resolvedMode === "work"
            enabled: !!(bridge && !bridge.connecting)
            Layout.preferredHeight: 28
            Layout.preferredWidth: autonomyRow.implicitWidth + Theme.s2 * 2
            hoverEnabled: true
            Accessible.name: bridge ? "Work autonomy " + root.permissionLabel(bridge.permissionMode) : "Work autonomy"
            Accessible.description: bridge ? root.permissionDetail(bridge.permissionMode) : ""
            onClicked: autonomyMenu.opened ? autonomyMenu.close() : autonomyMenu.open()
            ToolTip.visible: hovered
            ToolTip.text: bridge ? root.permissionDetail(bridge.permissionMode) : ""
            ToolTip.delay: Theme.tooltipDelay
            background: GlassSurface {
                radius: Theme.r2
                solid: false
                glassEnabled: autonomyButton.hovered || autonomyMenu.opened || autonomyButton.visualFocus
                tint: Theme.glassTintHover
                fillOpacity: autonomyButton.hovered || autonomyMenu.opened ? 0.48 : 0.0
                outlineVisible: autonomyButton.hovered || autonomyMenu.opened || autonomyButton.visualFocus
                strongEdge: autonomyButton.hovered || autonomyMenu.opened || autonomyButton.visualFocus
                active: autonomyButton.visualFocus
                sheen: autonomyButton.hovered || autonomyMenu.opened
                edgeColor: autonomyButton.visualFocus || autonomyMenu.opened
                         ? Theme.accentEdge
                         : autonomyButton.hovered ? Theme.glassEdgeStrong : Theme.borderSubtle
            }
            contentItem: Item {
                Row {
                    id: autonomyRow
                    anchors.centerIn: parent
                    spacing: Theme.s1
                    StatusDot {
                        width: 6
                        height: 6
                        tone: bridge && bridge.permissionMode === "full" ? Theme.warning : Theme.accent
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: bridge ? root.permissionLabel(bridge.permissionMode) : "Auto-approve"
                        color: Theme.textSecondary
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.micro
                        font.weight: Font.Medium
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Icon {
                        name: "down"
                        ink: Theme.textMuted
                        width: 9
                        height: 9
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                cursorShape: Qt.PointingHandCursor
            }

            WMenu {
                id: autonomyMenu
                anchorX: -menuWidth + autonomyButton.width
                menuWidth: 310
                items: [
                    { id: "manual", label: bridge && bridge.permissionMode === "manual" ? "Ask every time  • current" : "Ask every time", icon: "cursor" },
                    { id: "safe", label: bridge && bridge.permissionMode === "safe" ? "Auto-approve  • current" : "Auto-approve", icon: "shield" },
                    { id: "auto", label: bridge && bridge.permissionMode === "auto" ? "Autopilot  • current" : "Autopilot", icon: "bolt" },
                    { id: "full", label: bridge && bridge.permissionMode === "full" ? "Full access  • current" : "Full access", icon: "warning" },
                    { separator: true },
                    { id: "settings", label: "Agent settings…", icon: "sliders" },
                ]
                onPicked: function(id) {
                    if (id === "settings") {
                        root.openAgentSettings();
                        return;
                    }
                    if (bridge && (id === "manual" || id === "safe" || id === "auto" || id === "full"))
                        bridge.setPermissionMode(id);
                }
            }
        }

        // ------------------------------------------------------- run state
        Item {
            id: runState
            visible: bridge && bridge.busy
            Layout.preferredWidth: Math.min(runRow.implicitWidth, Math.max(120, root.width * 0.22))
            Layout.preferredHeight: 28
            Layout.maximumWidth: Math.max(120, root.width * 0.22)

            RowLayout {
                id: runRow
                anchors.fill: parent
                spacing: Theme.s1
                ActivityGlyph {
                    running: true
                    tone: bridge && bridge.permissionPending ? Theme.warning : Theme.success
                    Layout.preferredWidth: implicitWidth
                    Layout.preferredHeight: implicitHeight
                }
                Text {
                    Layout.fillWidth: true
                    text: !bridge ? ""
                        : bridge.permissionPending ? "Waiting for approval"
                        : (bridge.status && bridge.status !== "Ready when you are"
                            ? bridge.status
                            : root.resolvedMode === "work" ? "Working" : "Generating")
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    elide: Text.ElideRight
                }
                Text {
                    visible: bridge && bridge.tokenRate !== "—" && root.width > 1180
                    text: bridge ? String(bridge.tokenRate).replace(" tok/s", " t/s") : ""
                    color: Theme.textMuted
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.micro
                }
                IconButton {
                    Layout.preferredWidth: 24
                    Layout.preferredHeight: 24
                    iconSize: 10
                    iconName: "stop"
                    tooltip: "Stop"
                    tint: Theme.danger
                    activeTint: Theme.danger
                    onClicked: if (bridge) bridge.stop()
                }
            }
        }

        Chip {
            visible: !root.homeMode && bridge && root.resolvedMode === "work"
                     && bridge.desktopEnabled && !bridge.busy && root.roomy
            text: "Screen"
            iconName: "cursor"
            selected: true
            onClicked: root.openAgentSettings()
            ToolTip.visible: hovered
            ToolTip.text: bridge ? "Desktop control is on · " + root.permissionLabel(bridge.permissionMode) : ""
        }

        Chip {
            visible: !root.homeMode && bridge && bridge.projectName
                     && root.resolvedMode === "work" && bridge.projectInstructionsSummary && root.roomy
            text: "Project rules"
            iconName: "code"
            ToolTip.visible: hovered
            ToolTip.delay: Theme.tooltipDelay
            ToolTip.text: bridge ? "Active repository guidance: " + bridge.projectInstructionsSummary
                                  + ". These files guide coding conventions but never grant permissions." : ""
        }

        Chip {
            visible: root.needsAttention || root.connecting
            text: root.connecting ? "Connecting" : "Ollama offline"
            iconName: root.connecting ? "clock" : "warning"
            tone: root.connecting ? Theme.textMuted : Theme.danger
            onClicked: if (bridge) bridge.refreshModels()
            ToolTip.visible: hovered
            ToolTip.text: bridge ? bridge.endpoint + " — click to reconnect" : ""
        }

        // ------------------------------------------------------ the system
        IconButton {
            id: systemButton
            objectName: "systemButton"
            iconName: "cpu"
            iconSize: 14
            tooltip: "System"
            active: system.opened
            onClicked: system.opened ? system.close() : system.open()

            SystemPopover { id: system; anchorX: -width + systemButton.width }

            Rectangle {
                visible: !!(bridge && !bridge.online)
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: 5
                width: 5
                height: 5
                radius: 2.5
                color: Theme.danger
            }
        }

        Divider {
            vertical: true
            visible: root.dockAvailable && root.dockOpen
            Layout.leftMargin: Theme.s1
            Layout.rightMargin: Theme.s1
        }

        IconButton {
            objectName: "headerDockToggle"
            visible: root.dockAvailable && root.dockOpen
            iconSize: 14
            iconName: "panel"
            tooltip: root.dockOpen ? "Hide the workspace dock" : "Show the workspace dock"
            shortcut: "Ctrl+Shift+B"
            active: root.dockOpen
            onClicked: root.toggleDock()
        }

        IconButton {
            iconName: "more"
            tooltip: "More"
            active: overflow.opened
            onClicked: overflow.opened ? overflow.close() : overflow.open()

            WMenu {
                id: overflow
                anchorX: -menuWidth + parent.width
                menuWidth: 258
                items: [
                    { id: "palette", label: "Command palette", icon: "command", shortcut: "Ctrl+Shift+P" },
                    { id: "shortcuts", label: "Keyboard shortcuts", icon: "keyboard" },
                    { separator: true },
                    { id: "rename", label: "Rename task", icon: "edit", disabled: !(bridge && bridge.taskId) },
                    { id: "pin", label: bridge && bridge.taskPinned ? "Unpin task" : "Pin task", icon: "pin", disabled: !(bridge && bridge.taskId) },
                    { id: "duplicate", label: "Duplicate task", icon: "duplicate", shortcut: "Ctrl+D", disabled: !(bridge && bridge.taskId) },
                    { id: "export", label: "Export Markdown", icon: "download", disabled: !(bridge && bridge.hasMessages) },
                    { separator: true },
                    { id: "regenerate", label: "Regenerate", icon: "retry", shortcut: "Ctrl+R", disabled: !(bridge && bridge.canRegenerate) },
                    { id: "clear", label: "Clear messages", icon: "trash", disabled: !(bridge && bridge.hasMessages) },
                    { separator: true },
                    { id: "settings", label: "Settings", icon: "sliders", shortcut: "Ctrl+," },
                ]
                onPicked: function(id) {
                    if (id === "palette") root.openCommandPalette();
                    else if (id === "shortcuts") root.openShortcuts();
                    else if (id === "rename") root.renameRequested();
                    else if (id === "settings") root.openSettings();
                    else if (!bridge) return;
                    else if (id === "pin") bridge.togglePin(bridge.taskId);
                    else if (id === "duplicate") bridge.duplicateTask();
                    else if (id === "export") bridge.exportTask();
                    else if (id === "regenerate") bridge.regenerate();
                    else if (id === "clear") root.clearRequested();
                }
            }
        }
    }
}
