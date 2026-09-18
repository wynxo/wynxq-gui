import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Where you are: the app, the mode, the project, and every task you have had.

    The top strip holds the things you reach for constantly — current mode,
    new task, search and collapse. Chat and Work are task modes, not separate
    products; choosing the other mode starts a fresh task so saved history never
    changes capabilities underneath you. Everything below is history.
*/
Item {
    id: root
    property bool collapsed: false
    signal newTask()
    signal newModeTask(string mode)
    signal openSettings()
    signal renameRequested(string id, string title)
    signal deleteRequested(string id, string title)
    signal collapseRequested(bool value)

    readonly property bool inWork: bridge && bridge.taskMode === "work"
    function focusSearch() { search.forceActiveFocus(); search.selectAll(); }

    GlassSurface {
        anchors.fill: parent
        tint: Theme.backgroundSoft
        fillOpacity: 0.82
        outlineVisible: false
        sheen: true
    }
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.glassEdge }

    // ------------------------------------------------------------ expanded
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.s2
        anchors.topMargin: Theme.s2
        anchors.bottomMargin: Theme.s2
        spacing: Theme.s2
        visible: !root.collapsed

        // ------------------------------------------------------- identity
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.s1
            Layout.preferredHeight: 30
            spacing: Theme.s2

            Mark { Layout.preferredWidth: 18; Layout.preferredHeight: 18 }

            // Mode is a task boundary. Picking the other entry starts a fresh
            // task rather than mutating the capabilities of the current one.
            AbstractButton {
                id: productButton
                Layout.fillWidth: true
                implicitHeight: 28
                hoverEnabled: true
                Accessible.name: "Wynxq GUI. Current mode " + (root.inWork ? "Work" : "Chat") + ". Start another mode"
                onClicked: productMenu.opened ? productMenu.close() : productMenu.open()
                background: GlassSurface {
                    radius: Theme.r2
                    tint: Theme.glassTintHover
                    fillOpacity: productButton.hovered || productMenu.opened ? 0.44 : 0.0
                    outlineVisible: productButton.hovered || productMenu.opened || productButton.visualFocus
                    active: productButton.visualFocus
                    sheen: productButton.hovered || productMenu.opened
                }
                contentItem: Row {
                    leftPadding: Theme.s1
                    spacing: Theme.s1
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Wynxq GUI · " + (root.inWork ? "Work" : "Chat")
                        color: Theme.textPrimary
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.heading
                        font.weight: Font.DemiBold
                    }
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "down"; ink: Theme.textDisabled
                        width: 11; height: 11
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }

                WMenu {
                    id: productMenu
                    menuWidth: 250
                    items: [
                        { id: "chat", label: "Chat", detail: "Answers and explanations, no local tools",
                          icon: "chat", checked: !root.inWork },
                        { id: "work", label: "Work", detail: "Project, command and desktop tools",
                          icon: "cursor", checked: root.inWork },
                    ]
                    onPicked: function(id) {
                        if (id === "chat" && root.inWork) root.newModeTask("chat");
                        else if (id === "work" && !root.inWork) root.newModeTask("work");
                    }
                }
            }

            IconButton {
                Layout.preferredWidth: 28; Layout.preferredHeight: 28
                objectName: "sidebarCollapseButton"
                iconName: "panelLeft"; iconSize: 13
                tooltip: "Collapse sidebar"; shortcut: "Ctrl+B"
                onClicked: root.collapseRequested(true)
            }
        }

        // ---------------------------------------------- the two constants
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.s1
            spacing: Theme.s1

            WButton {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.control
                text: root.inWork ? "New work task" : "New task"
                iconName: "plus"
                variant: "secondary"
                onClicked: root.inWork ? root.newModeTask("work") : root.newTask()
                ToolTip.visible: hovered
                ToolTip.text: "Ctrl+N"
            }
            IconButton {
                Layout.preferredWidth: Theme.control
                Layout.preferredHeight: Theme.control
                iconName: "search"
                iconSize: 14
                tooltip: "Search tasks"
                shortcut: "Ctrl+K"
                active: searchRow.visible
                onClicked: {
                    searchRow.visible = !searchRow.visible;
                    if (searchRow.visible) Qt.callLater(root.focusSearch);
                    else if (bridge) { search.text = ""; }
                }
            }
        }

        Item {
            id: searchRow
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? Theme.control : 0
            visible: !!(bridge && bridge.searchQuery)
            Field {
                id: search
                anchors.fill: parent
                iconName: "search"
                placeholderText: "Search tasks"
                font.pixelSize: Theme.caption
                Component.onCompleted: text = bridge ? bridge.searchQuery : ""
                onTextChanged: if (bridge) bridge.setSearch(text)
                Keys.onEscapePressed: function(event) {
                    if (text.length) { text = ""; event.accepted = true; }
                    else { searchRow.visible = false; event.accepted = true; }
                }
            }
        }

        // -------------------------------------------------------- project
        AbstractButton {
            id: projectButton
            Layout.fillWidth: true
            Layout.topMargin: Theme.s1
            implicitHeight: 40
            hoverEnabled: true
            Accessible.name: bridge && bridge.projectName
                ? "Project " + bridge.projectName + ". Change project"
                : "Choose a project folder"
            onClicked: projectMenu.opened ? projectMenu.close() : projectMenu.open()

            background: GlassSurface {
                radius: Theme.r2
                tint: projectButton.hovered || projectMenu.opened ? Theme.glassTintHover : Theme.glassTint
                fillOpacity: projectButton.hovered || projectMenu.opened ? 0.64 : Theme.glassThinOpacity
                strongEdge: projectButton.hovered || projectMenu.opened
                active: projectButton.visualFocus
                edgeColor: projectButton.visualFocus ? Theme.accentEdge
                         : projectButton.hovered || projectMenu.opened ? Theme.glassEdgeStrong : Theme.glassEdge
            }

            contentItem: RowLayout {
                spacing: Theme.s2
                Icon {
                    Layout.leftMargin: Theme.s3
                    Layout.preferredWidth: 14; Layout.preferredHeight: 14
                    name: bridge && bridge.projectPath ? "folderOpen" : "folder"
                    ink: bridge && bridge.projectPath ? Theme.textSecondary : Theme.textMuted
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    spacing: 0
                    Text {
                        Layout.fillWidth: true
                        text: bridge && bridge.projectName ? bridge.projectName : "Open project"
                        color: bridge && bridge.projectPath ? Theme.textPrimary : Theme.textSecondary
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.caption
                        font.weight: Font.Medium
                        elide: Text.ElideMiddle
                    }
                    Text {
                        Layout.fillWidth: true
                        text: bridge && bridge.projectPath
                              ? (bridge.workspaceDock && bridge.workspaceDock.branch
                                 ? bridge.workspaceDock.branch : bridge.projectParentLabel)
                              : "Files, terminal and changes live in it"
                        color: Theme.textMuted
                        font.family: bridge && bridge.projectPath ? Theme.monoFamily : Theme.sansFamily
                        font.pixelSize: Theme.micro
                        elide: bridge && bridge.workspaceDock && bridge.workspaceDock.branch
                               ? Text.ElideRight : Text.ElideLeft
                    }
                }
                Icon {
                    Layout.rightMargin: Theme.s3
                    Layout.preferredWidth: 10; Layout.preferredHeight: 10
                    name: "chevron"
                    ink: Theme.textDisabled
                }
            }

            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }

            WMenu {
                id: projectMenu
                menuWidth: Math.max(240, projectButton.width)
                property var recents: bridge ? bridge.recentProjects : []
                onAboutToShow: recents = bridge ? bridge.recentProjects : []
                items: {
                    var list = [{ id: "choose", label: "Open folder…", icon: "folder" }];
                    if (recents.length) {
                        list.push({ separator: true });
                        for (var i = 0; i < Math.min(recents.length, 5); i++)
                            list.push({ id: "recent:" + recents[i].path,
                                        label: recents[i].name, icon: "clock" });
                    }
                    var has = !!(bridge && bridge.projectPath);
                    list.push({ separator: true, hidden: !has });
                    list.push({ id: "files", label: "Show files", icon: "folderOpen",
                                shortcut: "Ctrl+Shift+E", hidden: !has });
                    list.push({ id: "reveal", label: "Reveal in file manager", icon: "launch", hidden: !has });
                    list.push({ id: "terminal", label: "Open terminal here", icon: "terminal", hidden: !has });
                    list.push({ id: "copy", label: "Copy path", icon: "copy", hidden: !has });
                    list.push({ id: "clear", label: "Close project", icon: "close", hidden: !has });
                    return list;
                }
                onPicked: function(id) {
                    if (!bridge) return;
                    if (id === "choose") bridge.chooseProject();
                    else if (id === "files" && bridge.workspaceDock) bridge.workspaceDock.openTab("files");
                    else if (id === "reveal") bridge.revealPath(bridge.projectPath);
                    else if (id === "terminal") bridge.openTerminalHere();
                    else if (id === "copy") bridge.copyProjectPath();
                    else if (id === "clear") bridge.clearProject();
                    else if (id.indexOf("recent:") === 0) bridge.openProject(id.substring(7));
                }
            }
        }

        // --------------------------------------------------------- history
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.s2
            Layout.rightMargin: Theme.s2
            Layout.topMargin: Theme.s2
            SectionLabel { text: bridge && bridge.searchQuery ? "Results" : "Tasks" }
            Item { Layout.fillWidth: true }
            Text {
                text: bridge && bridge.taskGroups
                      ? String(bridge.taskGroups.reduce(function(total, group) { return total + group.items.length; }, 0))
                      : ""
                color: Theme.textDisabled
                font.family: Theme.monoFamily
                font.pixelSize: Theme.micro
            }
        }

        ListView {
            id: groups
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: Theme.s2
            model: bridge ? bridge.taskGroups : []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: WScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Column {
                required property var modelData
                width: groups.width
                spacing: 1

                SectionLabel {
                    width: parent.width
                    text: modelData.title
                    color: Theme.textDisabled
                    font.pixelSize: Theme.micro
                    leftPadding: Theme.s2
                    topPadding: Theme.s1
                    bottomPadding: Theme.s1
                }

                Repeater {
                    model: modelData.items
                    delegate: TaskRow {
                        required property var modelData
                        width: groups.width
                        entry: modelData
                        onRenameRequested: root.renameRequested(entry.id, entry.title)
                        onDeleteRequested: root.deleteRequested(entry.id, entry.title)
                    }
                }
            }

            Column {
                anchors.top: parent.top
                anchors.topMargin: Theme.s3
                x: Theme.s2
                width: parent.width - Theme.s4
                spacing: Theme.s2
                visible: groups.count === 0
                Text {
                    width: parent.width
                    text: bridge && bridge.searchQuery ? "No matching tasks" : "No tasks yet"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Text {
                    width: parent.width
                    text: bridge && bridge.searchQuery ? "Try a different search."
                                                       : "New tasks are saved here automatically."
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                    wrapMode: Text.WordWrap; lineHeight: 1.35
                }
            }
        }

        Divider { Layout.fillWidth: true }

        AbstractButton {
            id: settingsButton
            Layout.fillWidth: true
            Layout.preferredHeight: 32
            hoverEnabled: true
            Accessible.name: "Settings"
            onClicked: root.openSettings()
            background: GlassSurface {
                radius: Theme.r2
                tint: Theme.glassTintHover
                fillOpacity: settingsButton.hovered ? 0.46 : 0.0
                outlineVisible: settingsButton.hovered || settingsButton.visualFocus
                active: settingsButton.visualFocus
                sheen: settingsButton.hovered
            }
            contentItem: RowLayout {
                spacing: Theme.s3
                Icon {
                    Layout.leftMargin: Theme.s3
                    Layout.preferredWidth: 14; Layout.preferredHeight: 14
                    name: "sliders"; ink: Theme.textMuted
                }
                Text {
                    text: "Settings"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Item { Layout.fillWidth: true }
                KeyHint { Layout.rightMargin: Theme.s2; keys: "Ctrl+," }
            }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
        }
    }

    // ---------------------------------------------------------- collapsed
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.s2
        anchors.topMargin: Theme.s2
        spacing: Theme.s1
        visible: root.collapsed

        Item { Layout.alignment: Qt.AlignHCenter; Layout.preferredHeight: 30; Layout.preferredWidth: 30
            Mark { anchors.centerIn: parent; width: 18; height: 18 }
        }

        IconButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: "plus"
            tooltip: root.inWork ? "New work task" : "New task"
            shortcut: "Ctrl+N"
            onClicked: root.inWork ? root.newModeTask("work") : root.newTask()
        }
        IconButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: "search"; tooltip: "Search tasks"; shortcut: "Ctrl+K"
            onClicked: { root.collapseRequested(false); Qt.callLater(root.focusSearch); }
        }

        Divider { Layout.fillWidth: true; Layout.topMargin: Theme.s1; Layout.bottomMargin: Theme.s1 }

        IconButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: root.inWork ? "cursor" : "chat"
            tooltip: "Wynxq GUI · " + (root.inWork ? "Work" : "Chat")
            active: true
            onClicked: root.collapseRequested(false)
        }
        IconButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: bridge && bridge.projectPath ? "folderOpen" : "folder"
            tooltip: bridge && bridge.projectLabel ? "Project · " + bridge.projectLabel : "Open project"
            onClicked: root.collapseRequested(false)
        }

        Item { Layout.fillHeight: true }

        IconButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: "panel"; tooltip: "Show sidebar"; shortcut: "Ctrl+B"
            onClicked: root.collapseRequested(false)
        }
        IconButton {
            Layout.alignment: Qt.AlignHCenter
            iconName: "sliders"; tooltip: "Settings"; shortcut: "Ctrl+,"
            onClicked: root.openSettings()
        }
    }
}
