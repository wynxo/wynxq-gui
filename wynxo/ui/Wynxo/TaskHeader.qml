import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A thin workspace title bar.

    Left: where you are — the panel toggle, the product, the project, the task.
    Right: what the machine is doing — run state, system, the dock toggle, and
    an overflow for everything that is not a per-second concern.

    Chat / Work is a one-time choice for a fresh Wynxq GUI task; once selected
    it disappears rather than becoming permanent navigation chrome.
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
    readonly property bool canChooseMode: root.homeMode && bridge && !bridge.taskModeLocked
    readonly property bool roomy: root.width > 820

    function requestMode(value) {
        if ((value !== "chat" && value !== "work") || !root.canChooseMode) return;
        if (!bridge || bridge.connecting || bridge.busy) return;
        root.modeRequested(value);
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
            visible: root.sidebarCollapsed && !root.drawerOpen
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

            Text {
                text: "Wynxq GUI"
                color: Theme.textSecondary
                font.family: Theme.sansFamily
                font.pixelSize: Theme.label
                font.weight: Font.DemiBold
            }

            Text {
                visible: bridge && bridge.projectName
                text: "/"
                color: Theme.textDisabled
                font.family: Theme.sansFamily
                font.pixelSize: Theme.caption
            }

            // The project is a button: it is where you are, and where you go
            // to change it.
            AbstractButton {
                id: projectButton
                visible: bridge && bridge.projectName
                readonly property real budget: Math.max(110, Math.min(230, root.width * 0.24))
                implicitHeight: 26
                implicitWidth: Math.min(projectRow.implicitWidth + Theme.s2 * 2, budget)
                Layout.maximumWidth: budget
                hoverEnabled: true
                Accessible.name: bridge ? "Project " + bridge.projectName : ""
                onClicked: projectMenu.opened ? projectMenu.close() : projectMenu.open()
                background: Rectangle {
                    radius: Theme.r1
                    color: projectButton.hovered || projectMenu.opened ? Theme.surfaceHover : "transparent"
                }
                contentItem: Row {
                    id: projectRow
                    spacing: Theme.s1
                    clip: true
                    Text {
                        id: projectLabel
                        anchors.verticalCenter: parent.verticalCenter
                        text: bridge ? bridge.projectName : ""
                        color: Theme.textMuted
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.caption
                        elide: Text.ElideMiddle
                        // The chevron's lane is reserved; the name gets the rest.
                        width: Math.min(implicitWidth, projectButton.budget - 22)
                    }
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "down"; ink: Theme.textDisabled
                        width: 9; height: 9
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }

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
                Layout.maximumWidth: Math.max(160, root.width * 0.38)
                implicitHeight: 26
                hoverEnabled: true
                Accessible.name: "Rename this task"
                onClicked: root.renameRequested()
                background: Rectangle {
                    radius: Theme.r1
                    color: titleButton.hovered && titleButton.enabled ? Theme.surfaceHover : "transparent"
                    border.width: titleButton.visualFocus ? 1 : 0
                    border.color: Theme.accentEdge
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

        // -------------------------------------------- one-time Chat / Work
        Row {
            id: modeChoice
            visible: root.canChooseMode
            spacing: 2

            Repeater {
                model: [
                    { id: "chat", label: "Chat", icon: "chat", hint: "Answers and explanations only. No commands, no screen, nothing on this computer is touched." },
                    { id: "work", label: "Work", icon: "cursor", hint: "Runs commands and, when allowed, drives the screen." },
                ]
                delegate: AbstractButton {
                    id: choice
                    required property var modelData
                    width: choiceRow.implicitWidth + Theme.s3 * 2
                    height: 30
                    hoverEnabled: true
                    readonly property bool chosen: root.resolvedMode === modelData.id
                    Accessible.name: modelData.label
                    Accessible.description: modelData.hint
                    Accessible.checked: chosen
                    onClicked: root.requestMode(modelData.id)
                    ToolTip.visible: hovered
                    ToolTip.text: modelData.hint
                    ToolTip.delay: 500
                    background: Rectangle {
                        radius: Theme.r2
                        color: choice.hovered ? Theme.surfaceHover
                             : choice.chosen ? Theme.surfaceSelected : "transparent"
                        border.width: choice.chosen || choice.visualFocus ? 1 : 0
                        border.color: choice.visualFocus ? Theme.accentEdge : Theme.borderSubtle
                    }
                    contentItem: Row {
                        id: choiceRow
                        anchors.centerIn: parent
                        spacing: Theme.s2
                        Icon {
                            name: choice.modelData.icon
                            ink: choice.chosen ? Theme.textPrimary : Theme.textMuted
                            width: 13; height: 13
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: choice.modelData.label
                            color: choice.chosen ? Theme.textPrimary : Theme.textSecondary
                            font.family: Theme.sansFamily
                            font.pixelSize: Theme.caption
                            font.weight: choice.chosen ? Font.Medium : Font.Normal
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                }
            }
        }

        // ------------------------------------------------------- run state
        Rectangle {
            visible: bridge && bridge.busy
            Layout.preferredWidth: runRow.implicitWidth + Theme.s3 + Theme.s2
            Layout.preferredHeight: 28
            Layout.maximumWidth: Math.max(110, root.width * 0.28)
            radius: Theme.r2
            color: Theme.surface
            border.width: 1
            border.color: Theme.borderSubtle

            RowLayout {
                id: runRow
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s1
                spacing: Theme.s2
                StatusDot {
                    tone: bridge && bridge.permissionPending ? Theme.warning : Theme.accent
                    pulsing: true
                    width: 7; height: 7
                }
                Text {
                    text: !bridge ? ""
                        : bridge.permissionPending ? "Waiting"
                        : root.resolvedMode === "work" ? "Working" : "Generating"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    elide: Text.ElideRight
                }
                Text {
                    visible: bridge && bridge.tokenRate !== "—" && root.width > 1080
                    text: bridge ? String(bridge.tokenRate).replace(" tok/s", " tokens/s") : ""
                    color: Theme.textMuted
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.micro
                }
                AbstractButton {
                    implicitWidth: 34
                    implicitHeight: 21
                    hoverEnabled: true
                    Accessible.name: "Stop"
                    onClicked: if (bridge) bridge.stop()
                    background: Rectangle {
                        radius: Theme.r1
                        color: parent.hovered ? Theme.dangerMuted : "transparent"
                    }
                    contentItem: Text {
                        text: "Stop"
                        color: Theme.danger
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.micro
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
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
            ToolTip.text: bridge ? "Permission mode: " + bridge.permissionModeLabel : ""
        }

        Chip {
            visible: !root.homeMode && bridge && bridge.projectName
                     && root.resolvedMode !== "chat" && bridge.projectInstructionsSummary && root.roomy
            text: "Project rules"
            iconName: "code"
            ToolTip.visible: hovered
            ToolTip.delay: 450
            ToolTip.text: bridge ? "Active repository guidance: " + bridge.projectInstructionsSummary
                                  + ". These files guide coding conventions but never grant permissions." : ""
        }

        // A Chat task cannot run anything. Saying so on the task itself is the
        // difference between "it refused" and "it was never able to".
        Chip {
            visible: !root.homeMode && bridge && root.resolvedMode === "chat" && root.roomy
            text: "Chat only"
            iconName: "chat"
            onClicked: root.openAgentSettings()
            ToolTip.visible: hovered
            ToolTip.text: "This task answers and explains. It has no shell, no screen control and no file access — start a Work task for those."
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

            // A dot instead of a badge: the connection is the only state worth
            // reporting from a 30-pixel button.
            Rectangle {
                visible: !!(bridge && !bridge.online)
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: 5
                width: 5; height: 5; radius: 2.5
                color: Theme.danger
            }
        }

        Divider { vertical: true; visible: root.dockAvailable; Layout.leftMargin: Theme.s1; Layout.rightMargin: Theme.s1 }

        IconButton {
            objectName: "headerDockToggle"
            visible: root.dockAvailable
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
