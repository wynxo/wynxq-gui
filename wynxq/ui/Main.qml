import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import Wynxq

/*!
    The application shell: three columns.

    Navigation on the left (where you are), the conversation in the middle
    (what you are doing), and the workspace dock on the right (what you are
    doing it with). The middle column is the only one that must always be
    there; both sides collapse to a rail and then out of the window entirely as
    it narrows, and the conversation keeps a reading measure rather than
    stretching to whatever is left.

    A fresh task can choose Chat or Work once in the header. Work owns the
    local project, command and desktop toolset; Chat is deliberately tool-free.
    Reopening a saved conversation never changes which kind of task it is.
*/
ApplicationWindow {
    id: window
    width: 1440; height: 920
    minimumWidth: 560; minimumHeight: 520
    visible: true
    title: (bridge ? bridge.taskTitle : "Wynxq GUI") + " — " + (bridge ? bridge.productName : "Wynxq GUI")
    color: bridge && bridge.solidBackground ? Theme.background : Theme.backgroundSoft

    // ------------------------------------------------------------ layout
    readonly property bool roomForSidebar: width >= 900
    readonly property bool roomForDock: width >= 1020
    onRoomForSidebarChanged: if (roomForSidebar && sidebarDrawer) sidebarDrawer.close()
    readonly property bool sidebarCollapsed: bridge ? bridge.sidebarCollapsed : false
    readonly property bool sidebarDocked: roomForSidebar
    readonly property bool homeMode: bridge && !bridge.hasMessages
    // Chat normally has no workspace tools. A persisted plan is the one
    // exception: it is presentation state, not a capability, and must remain
    // viewable after reopening a task even if that task currently says Chat.
    readonly property bool hasPresentablePlan: !!(bridge && bridge.planSteps && bridge.planSteps.length >= 2)
    readonly property bool workspaceAvailable: !!(bridge && (bridge.taskMode !== "chat" || hasPresentablePlan))
    property int sidebarUserWidth: 272
    // Collapsed means gone, not a permanent icon rail. The only affordance
    // left behind is the small restore button over the conversation.
    readonly property int sidebarWidth: sidebarCollapsed ? 0
        : Math.max(200, Math.min(sidebarUserWidth, Math.round(width * 0.3)))

    readonly property var dockState: bridge ? bridge.workspaceDock : null
    // The dock's own preference, clamped so it can never squeeze the
    // conversation below a readable width.
    property int dockUserWidth: 380
    readonly property int dockMaxWidth: Math.max(280, Math.round(width * 0.42))
    readonly property int dockWidth: Math.min(dockUserWidth, dockMaxWidth)
    readonly property bool dockOpen: workspaceAvailable && roomForDock
        && !!(dockState && dockState.visible)

    property bool closing: false

    onHomeModeChanged: {
        if (homeMode)
            Qt.callLater(function() { if (homeIntro) homeIntro.playEntrance(); });
    }

    // ------------------------------------------------------------- setup
    Binding { target: Theme; property: "bridge"; value: bridge }

    Component.onCompleted: {
        Theme.systemSans = window.font.family;
        if (bridge) {
            window.sidebarUserWidth = bridge.sidebarWidth;
            if (bridge.workspaceDock) {
                window.dockUserWidth = bridge.workspaceDock.width;
                bridge.workspaceDock.setTerminalPalette(Theme.terminalPalette);
            }
        }
        window.pushPalettes();
        if (bridge && !bridge.onboarded) onboarding.open();
    }

    function pushPalettes() {
        if (!Theme.bridge) return;
        Theme.bridge.setCodePalette(Theme.codePalette);
        Theme.bridge.setHtmlPalette({
            "text": Theme.textPrimary, "muted": Theme.textSecondary,
            "faint": Theme.textMuted, "accent": Theme.accent,
            "codeBackground": Theme.surfaceSunken, "border": Theme.borderStrong,
            "rule": Theme.borderSubtle
        });
        if (Theme.bridge.workspaceDock)
            Theme.bridge.workspaceDock.setTerminalPalette(Theme.terminalPalette);
    }

    Connections {
        target: Theme
        function onAccentChanged() { window.pushPalettes(); }
        function onBridgeChanged() { window.pushPalettes(); }
    }

    Connections {
        target: window.dockState
        function onChanged() {
            if (window.dockState && !dockResizing)
                window.dockUserWidth = window.dockState.width;
        }
    }
    property bool dockResizing: false

    onActiveChanged: if (bridge) bridge.setWindowActive(active)

    onClosing: function(close) {
        if (bridge && !bridge.canClose()) { close.accepted = false; closing = true; closeTimer.start(); }
    }
    Timer { id: closeTimer; interval: 150; repeat: true; onTriggered: { if (bridge && bridge.canClose()) { stop(); window.close(); } } }

    Connections {
        target: bridge
        function onChanged() {
            if (bridge && !bridge.onboarded && !onboarding.opened && window.previewOverlay === "")
                onboarding.open();
        }
        function onToast(text) { toast.show(text); }
        function onFocusComposer() { composer.focusInput(); }
        function onScrollToEnd() { taskView.jumpToEnd(); }
        function onQuickBarRequested() { window.openQuickBar(); }
    }

    // -------------------------------------------------------- shortcuts
    Shortcut {
        sequences: ["Ctrl+N"]
        onActivated: if (bridge) bridge.taskMode === "work" ? bridge.newTaskMode("work") : bridge.newTask()
    }
    Shortcut { sequences: ["Ctrl+,"]; onActivated: settings.show(settings.generalPage) }
    Shortcut { sequences: ["Ctrl+K"]; onActivated: window.focusSearch() }
    Shortcut { sequences: ["Ctrl+P"]; onActivated: palette.open() }
    Shortcut { sequences: ["Ctrl+M"]; onActivated: models.open() }
    Shortcut { sequences: ["Ctrl+B"]; onActivated: window.toggleSidebar() }
    Shortcut { sequences: ["Ctrl+Shift+P"]; onActivated: palette.open() }
    Shortcut { sequences: ["Ctrl+Space"]; onActivated: window.openQuickBar() }
    Shortcut { sequences: ["Ctrl+Shift+S"]; onActivated: if (bridge) bridge.stop() }
    Shortcut { sequences: ["Ctrl+R"]; onActivated: if (bridge) bridge.regenerate() }
    Shortcut { sequences: ["Ctrl+D"]; onActivated: if (bridge) bridge.duplicateTask() }
    Shortcut { sequences: ["Ctrl+Shift+V"]; onActivated: if (bridge) bridge.pasteImage() }
    Shortcut { sequences: ["Alt+Up"]; onActivated: if (bridge) bridge.openAdjacentTask(-1) }
    Shortcut { sequences: ["Alt+Down"]; onActivated: if (bridge) bridge.openAdjacentTask(1) }

    // The dock. One toggle, then one shortcut per tool.
    Shortcut { sequences: ["Ctrl+Shift+B"]; onActivated: window.toggleDock() }
    Shortcut { sequences: ["Ctrl+Shift+E"]; onActivated: window.openDock("files") }
    Shortcut { sequences: ["Ctrl+`"]; onActivated: window.openDock("terminal") }
    Shortcut { sequences: ["Ctrl+Shift+G"]; onActivated: window.openDock("changes") }
    Shortcut { sequences: ["Ctrl+Shift+K"]; onActivated: window.openDock("context") }
    Shortcut { sequences: ["Ctrl+Shift+M"]; onActivated: window.openDock("memory") }
    Shortcut { sequences: ["Ctrl+Shift+A"]; onActivated: window.openDock("activity") }
    Shortcut { sequences: ["Ctrl+Shift+W"]; onActivated: window.openDock("browser") }
    Shortcut { sequences: ["Ctrl+Shift+U"]; onActivated: window.openDock("preview") }
    Shortcut {
        sequences: ["Ctrl+L"]
        onActivated: if (window.dockOpen && window.dockState && window.dockState.tab === "browser")
                         dock.focusPanel()
    }

    Shortcut {
        sequences: ["Escape"]
        onActivated: {
            if (bridge && bridge.permissionPending) bridge.resolvePermission(false);
            else if (bridge && bridge.busy) bridge.stop();
        }
    }

    // ---------------------------------------------------------- the shell
    RowLayout {
        anchors.fill: parent
        spacing: 0

        WorkspaceSidebar {
            id: sidebar
            Layout.preferredWidth: window.sidebarWidth
            Layout.fillHeight: true
            visible: window.sidebarDocked
            collapsed: window.sidebarCollapsed
            onCollapseRequested: function(value) { if (bridge) bridge.setSidebarCollapsed(value); }
            onNewTask: if (bridge) bridge.newTask()
            onNewModeTask: function(mode) { if (bridge) bridge.newTaskMode(mode); }
            onOpenSettings: settings.show(settings.generalPage)
            onRenameRequested: function(id, title) { renameSheet.ask(id, title); }
            onDeleteRequested: function(id, title) { deleteSheet.ask(id, title); }
            Behavior on Layout.preferredWidth {
                enabled: !Theme.reducedMotion && !resizer.dragging
                NumberAnimation { duration: Theme.base; easing.type: Theme.easing }
            }
        }

        Item {
            id: resizer
            property bool dragging: drag.active
            visible: window.sidebarDocked && !window.sidebarCollapsed
            Layout.preferredWidth: visible ? 5 : 0
            Layout.fillHeight: true
            z: 2
            Rectangle {
                anchors.centerIn: parent
                width: 1; height: parent.height
                color: resizer.dragging || hover.hovered ? Theme.borderStrong : "transparent"
                Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
            }
            HoverHandler { id: hover; cursorShape: Qt.SizeHorCursor }
            DragHandler {
                id: drag
                target: null
                yAxis.enabled: false
                cursorShape: Qt.SizeHorCursor
                property real startWidth: 0
                onActiveChanged: {
                    if (active) startWidth = window.sidebarUserWidth;
                    else if (bridge) bridge.setSidebarWidth(window.sidebarUserWidth);
                }
                onTranslationChanged: if (active)
                    window.sidebarUserWidth = Math.max(200, Math.min(400, startWidth + translation.x))
            }
        }

        // -------------------------------------------------- the conversation
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 320
            spacing: 0

            TaskHeader {
                id: header
                Layout.fillWidth: true
                sidebarCollapsed: !window.sidebarDocked || window.sidebarCollapsed
                drawerOpen: sidebarDrawer.opened
                dockAvailable: window.workspaceAvailable
                dockOpen: window.roomForDock ? window.dockOpen : dockDrawer.opened
                onToggleSidebar: window.toggleSidebar()
                onToggleDock: window.toggleDock()
                onRenameRequested: if (bridge && bridge.taskId) renameSheet.ask(bridge.taskId, bridge.taskTitle)
                onOpenSettings: settings.show(settings.generalPage)
                onOpenAgentSettings: settings.show(settings.agentPage)
                onOpenCommandPalette: palette.open()
                onOpenShortcuts: shortcuts.open()
                onClearRequested: clearSheet.open()
                onModeRequested: function(mode) {
                    if (bridge && !bridge.connecting) bridge.setTaskMode(mode);
                }
            }

            ColumnLayout {
                id: contentColumn
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: Theme.gutter
                Layout.rightMargin: Theme.gutter
                Layout.bottomMargin: Theme.s4
                spacing: Theme.s3
                readonly property real centredReadingWidth: Math.min(Theme.readingWidth, width)

                // A fresh task centres one block — question, composer,
                // openings — rather than stranding a title above an empty page
                // with the composer pinned to the floor.
                Item {
                    Layout.fillHeight: true
                    Layout.verticalStretchFactor: 4
                    visible: window.homeMode
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? homeIntro.implicitHeight + Theme.s2 : 0
                    visible: window.homeMode

                    TaskStart {
                        id: homeIntro
                        showSculpture: window.height >= 720 && contentColumn.width >= 480
                        width: Math.min(Theme.readingWidth, parent.width)
                        anchors.horizontalCenter: parent.horizontalCenter
                    }
                }

                TaskView {
                    id: taskView
                    objectName: "conversationViewport"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: !window.homeMode
                    onLinkClicked: function(link) { linkSheet.ask(link); }
                }

                Item {
                    id: warningLane
                    Layout.fillWidth: true
                    visible: bridge && bridge.capabilityWarning.length > 0
                    Layout.preferredHeight: visible ? warningCard.height : 0

                    Rectangle {
                        id: warningCard
                        width: Math.min(Theme.readingWidth, parent.width)
                        height: warningText.implicitHeight + Theme.s3 * 2
                        anchors.horizontalCenter: parent.horizontalCenter
                        radius: Theme.r2
                        color: Theme.warningMuted
                        border.width: 1
                        border.color: Theme.alpha(Theme.warning, 0.3)
                        Accessible.role: Accessible.StaticText
                        Accessible.name: bridge ? bridge.capabilityWarning : ""
                        Row {
                            anchors.fill: parent
                            anchors.margins: Theme.s3
                            spacing: Theme.s3
                            Icon { name: "info"; ink: Theme.warning; width: 14; height: 14 }
                            Text {
                                id: warningText
                                width: parent.width - 14 - Theme.s3
                                text: bridge ? bridge.capabilityWarning : ""
                                color: Theme.textSecondary
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                        }
                    }
                }

                Item {
                    id: errorLane
                    Layout.fillWidth: true
                    visible: bridge && bridge.error.length > 0
                    Layout.preferredHeight: visible ? errorBanner.implicitHeight : 0

                    ErrorBanner {
                        id: errorBanner
                        width: Math.min(Theme.readingWidth, parent.width)
                        anchors.horizontalCenter: parent.horizontalCenter
                        onActionInvoked: function(action) { window.runCommand(action); }
                    }
                }

                Item {
                    id: composerLane
                    Layout.fillWidth: true
                    Layout.preferredHeight: composer.implicitHeight

                    Composer {
                        id: composer
                        objectName: "mainComposer"
                        width: Math.min(Theme.readingWidth, parent.width)
                        anchors.horizontalCenter: parent.horizontalCenter
                        // Leave room for the header, context and fresh-task
                        // starters in a short window. Use the window's budget;
                        // a layout can expand to fit its children's minimums.
                        maxHeight: Math.min(220, Math.max(64,
                            window.height - header.height - Theme.s4 - (window.homeMode
                                ? homeIntro.implicitHeight + homeStarters.implicitHeight
                                  + Theme.s2 + Theme.s1 + Theme.s3 * 4
                                : 100) - composer.chromeHeight
                            - (warningLane.visible ? warningLane.height + Theme.s3 : 0)
                            - (errorLane.visible ? errorLane.height + Theme.s3 : 0)))
                        onSubmitted: function(text) { if (bridge) bridge.send(text); }
                        onCommandInvoked: function(action) { window.runCommand(action); }
                        onOpenModelManager: models.open()
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? homeStarters.implicitHeight + Theme.s1 : 0
                    visible: window.homeMode

                    TaskStarters {
                        id: homeStarters
                        width: Math.min(Theme.readingWidth, parent.width)
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        anchors.topMargin: Theme.s1
                        onStarterChosen: function(prompt) { composer.insert(prompt); }
                        onCommandInvoked: function(action) { window.runCommand(action); }
                        onModeRequested: function(mode) {
                            if (bridge && !bridge.connecting) bridge.setTaskMode(mode);
                        }
                    }
                }

                Item {
                    Layout.fillHeight: true
                    Layout.verticalStretchFactor: 5
                    visible: window.homeMode
                }
            }
        }

        // -------------------------------------------------------- the dock
        WorkspaceDock {
            id: dock
            Layout.preferredWidth: implicitWidth
            Layout.fillHeight: true
            visible: window.roomForDock && window.workspaceAvailable
            panelOpen: window.dockOpen
            panelWidth: window.dockWidth
            onWidthChangeRequested: function(value) {
                window.dockResizing = true;
                window.dockUserWidth = value;
                window.dockResizing = false;
            }
            onFocusEditorRequested: editorFocus.open()
            Behavior on Layout.preferredWidth {
                enabled: !Theme.reducedMotion && !dock.resizing
                NumberAnimation { duration: Theme.base; easing.type: Theme.easing }
            }
        }
    }

    // ----------------------------------------------- collapsed affordances
    // A hidden side genuinely leaves the canvas. These two quiet controls are
    // the only restore affordances, keeping the window clean instead of
    // replacing full panels with permanent strips of icons.
    IconButton {
        id: sidebarRestore
        objectName: "sidebarRestoreButton"
        visible: (!window.sidebarDocked || window.sidebarCollapsed) && !sidebarDrawer.opened
        z: 40
        width: 32; height: 32; iconSize: 14
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: Theme.s3
        anchors.bottomMargin: Theme.s3
        iconName: "panelLeft"
        tooltip: "Show sidebar"
        shortcut: "Ctrl+B"
        scale: down ? 0.92 : hovered ? 1.035 : 1.0
        onClicked: window.toggleSidebar()
        background: GlassSurface {
            radius: Theme.r2
            solid: false
            glassEnabled: true
            tint: Theme.glassTintStrong
            fillOpacity: sidebarRestore.hovered ? 0.82 : 0.62
            outlineVisible: true
            strongEdge: sidebarRestore.hovered || sidebarRestore.visualFocus
            active: sidebarRestore.visualFocus
            sheen: sidebarRestore.hovered
            edgeColor: sidebarRestore.visualFocus ? Theme.accentEdge : Theme.glassEdge
        }
        Behavior on scale {
            enabled: !Theme.reducedMotion
            NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
        }
    }

    IconButton {
        id: dockRestore
        objectName: "dockRestoreButton"
        visible: window.workspaceAvailable
                 && (!window.roomForDock || !window.dockOpen)
                 && !dockDrawer.opened
        z: 40
        width: 32; height: 32; iconSize: 14
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: Theme.s3
        anchors.bottomMargin: Theme.s3
        iconName: "panelRight"
        tooltip: "Show workspace"
        shortcut: "Ctrl+Shift+B"
        scale: down ? 0.92 : hovered ? 1.035 : 1.0
        onClicked: window.toggleDock()
        background: GlassSurface {
            radius: Theme.r2
            solid: false
            glassEnabled: true
            tint: Theme.glassTintStrong
            fillOpacity: dockRestore.hovered ? 0.82 : 0.62
            outlineVisible: true
            strongEdge: dockRestore.hovered || dockRestore.visualFocus
            active: dockRestore.visualFocus
            sheen: dockRestore.hovered
            edgeColor: dockRestore.visualFocus ? Theme.accentEdge : Theme.glassEdge
        }
        Behavior on scale {
            enabled: !Theme.reducedMotion
            NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
        }
    }

    // --------------------------------------------------------- the drawer
    Drawer {
        id: sidebarDrawer
        edge: Qt.LeftEdge
        width: Math.min(300, window.width - 48)
        height: window.height
        dragMargin: 0
        background: Rectangle { color: Theme.backgroundSoft }
        property bool focusSearchWhenOpen: false
        onOpened: if (focusSearchWhenOpen) { focusSearchWhenOpen = false; drawerSidebar.focusSearch(); }
        onClosed: focusSearchWhenOpen = false
        WorkspaceSidebar {
            id: drawerSidebar
            anchors.fill: parent
            onNewTask: { if (bridge) bridge.newTask(); sidebarDrawer.close(); }
            onNewModeTask: function(mode) { if (bridge) bridge.newTaskMode(mode); sidebarDrawer.close(); }
            onOpenSettings: { sidebarDrawer.close(); settings.show(settings.generalPage); }
            onRenameRequested: function(id, title) { sidebarDrawer.close(); renameSheet.ask(id, title); }
            onDeleteRequested: function(id, title) { sidebarDrawer.close(); deleteSheet.ask(id, title); }
            onCollapseRequested: sidebarDrawer.close()
        }
    }

    // ---------------------------------------------- the dock, in a drawer
    // Below the three-column threshold the tools are still reachable; they
    // simply arrive over the conversation instead of beside it.
    Drawer {
        id: dockDrawer
        edge: Qt.RightEdge
        width: Math.min(420, window.width - 32)
        height: window.height
        dragMargin: 0
        enabled: window.workspaceAvailable
        background: Rectangle { color: Theme.background }
        WorkspaceDock {
            id: drawerDock
            anchors.fill: parent
            panelOpen: true
            panelWidth: dockDrawer.width - Theme.railWidth - 5
        }
    }

    // --------------------------------------------------------- overlays
    ModelManager { id: models }
    SettingsSheet {
        id: settings
        onOpenModelManager: models.open()
        onOpenMemoryPanel: window.openDock("memory")
    }
    ShortcutsSheet { id: shortcuts }
    CommandPalette { id: palette; onInvoked: function(action) { window.runCommand(action); } }
    FocusEditor {
        id: editorFocus
        onAskRequested: {
            close();
            composer.focusInput();
        }
    }
    PermissionPrompt { id: permission }
    Onboarding { id: onboarding; onOpenModelManager: models.open() }
    Toast { id: toast }
    RegionSelector { id: regionSelector }

    ConfirmSheet {
        id: renameSheet
        title: "Rename task"
        withInput: true
        confirmText: "Save"
        property string targetId: ""
        function ask(id, title) { targetId = id; inputText = title; show(); }
        onConfirmed: if (bridge) bridge.renameTaskById(targetId, inputText)
    }

    ConfirmSheet {
        id: deleteSheet
        title: "Delete this task?"
        confirmText: "Delete"
        confirmVariant: "danger"
        property string targetId: ""
        function ask(id, title) {
            targetId = id;
            message = "“" + title + "” and its messages will be removed from this computer.";
            show();
        }
        onConfirmed: if (bridge) bridge.deleteTask(targetId)
    }

    ConfirmSheet {
        id: clearSheet
        title: "Clear this task?"
        message: "The task stays in your list, but every message is removed from local history."
        confirmText: "Clear"
        confirmVariant: "danger"
        onConfirmed: if (bridge) bridge.clearTask()
    }

    ConfirmSheet {
        id: linkSheet
        title: "Open this link?"
        message: "Wynxq GUI can show it in the built-in browser, or hand it to your default browser."
        confirmText: "Open in browser"
        property string link: ""
        function ask(url) { link = url; detail = url; show(); }
        onConfirmed: {
            if (window.dockState && window.dockState.browserAvailable) {
                window.openDock("browser");
                window.dockState.navigate(link);
            } else {
                Qt.openUrlExternally(link);
            }
        }
    }

    // -------------------------------------------------------- quick bar
    property var quickBarWindow: quickBar

    Window {
        id: quickBar
        objectName: "quickBar"
        width: 620
        height: quickContent.implicitHeight
        flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog
        color: "transparent"
        title: "Wynxq GUI quick bar"

        QuickBarContent {
            id: quickContent
            width: parent.width
            onSubmitted: function(text) {
                window.show();
                window.raise();
                if (bridge) bridge.send(text);
                quickBar.close();
            }
            onExpandRequested: { quickBar.close(); window.show(); window.raise(); window.requestActivate(); }
            onDismissed: quickBar.close()
        }
    }

    function openQuickBar() {
        var screenWidth = Screen.width > 0 ? Screen.width : window.width;
        var screenHeight = Screen.height > 0 ? Screen.height : window.height;
        quickBar.x = Math.round((screenWidth - quickBar.width) / 2);
        quickBar.y = Math.round(screenHeight * 0.26);
        quickBar.show();
        quickBar.raise();
        quickBar.requestActivate();
        quickContent.focusInput();
    }

    // Preview hook: --snapshot drives the real UI into a named state so README
    // screenshots come from this renderer, not from a mock-up.
    property string previewOverlay: ""
    function closeOverlays() {
        settings.close(); models.close(); palette.close(); shortcuts.close();
        onboarding.close(); quickBar.close();
        renameSheet.close(); deleteSheet.close(); clearSheet.close(); linkSheet.close();
    }
    onPreviewOverlayChanged: {
        closeOverlays();
        if (previewOverlay === "welcome") onboarding.open();
        else if (previewOverlay === "settings") settings.show(settings.generalPage);
        else if (previewOverlay === "modelSettings") settings.show(settings.modelPage);
        else if (previewOverlay === "agentSettings") settings.show(settings.agentPage);
        else if (previewOverlay === "appearanceSettings") settings.show(settings.appearancePage);
        else if (previewOverlay === "usageSettings") settings.show(settings.usagePage);
        else if (previewOverlay === "advancedSettings") settings.show(settings.advancedPage);
        else if (previewOverlay === "workspaceSettings") settings.show(settings.workspacePage);
        else if (previewOverlay === "models") models.open();
        else if (previewOverlay === "modelPicker") composer.showModelPicker();
        else if (previewOverlay === "palette") palette.open();
        else if (previewOverlay === "shortcuts") shortcuts.open();
        else if (previewOverlay === "system") header.showSystem();
        else if (previewOverlay === "rename" && bridge) renameSheet.ask(bridge.taskId, bridge.taskTitle);
        else if (previewOverlay === "quickbar") window.openQuickBar();
    }

    // ---------------------------------------------------------- commands
    function toggleSidebar() {
        if (!window.sidebarDocked) {
            if (sidebarDrawer.opened) sidebarDrawer.close();
            else sidebarDrawer.open();
            return;
        }
        if (bridge) bridge.setSidebarCollapsed(!bridge.sidebarCollapsed);
    }

    function toggleDock() {
        if (!window.workspaceAvailable) return;
        if (!window.roomForDock) {
            drawerDock.userSelectedWorkspaceTab = true;
            if (dockDrawer.opened) dockDrawer.close();
            else dockDrawer.open();
            return;
        }
        dock.userSelectedWorkspaceTab = true;
        if (window.dockState) window.dockState.toggle();
    }

    function openDock(tab) {
        if (!window.workspaceAvailable || !window.dockState) return;
        if (!window.roomForDock) {
            drawerDock.userSelectedWorkspaceTab = true;
            drawerDock.planSelected = false;
            window.dockState.setTab(tab);
            if (!dockDrawer.opened) dockDrawer.open();
            return;
        }
        // Route through WorkspaceDock so leaving Plan cannot accidentally
        // toggle the underlying backend tab closed when it is the same tab.
        dock.pickWorkspaceTab(tab);
    }

    function focusSearch() {
        if (!window.sidebarDocked) {
            if (sidebarDrawer.opened) drawerSidebar.focusSearch();
            else { sidebarDrawer.focusSearchWhenOpen = true; sidebarDrawer.open(); }
            return;
        }
        if (bridge) bridge.setSidebarCollapsed(false);
        sidebar.focusSearch();
    }

    function runCommand(action) {
        if (!bridge) return;
        if (action.indexOf("task:") === 0) {
            bridge.openTask(action.substring(5));
            return;
        }
        if (action.indexOf("file:") === 0) {
            if (!window.dockState) return;
            var path = action.substring(5);
            if (window.dockState.openFile(path)) {
                window.dockState.revealFile(path);
                editorFocus.open();
            }
            return;
        }
        if (action === "mode-chat") { bridge.setTaskMode("chat"); return; }
        if (action === "mode-work") { bridge.setTaskMode("work"); return; }
        if (action === "palette") { palette.open(); return; }
        switch (action) {
        case "new": bridge.taskMode === "work" ? bridge.newTaskMode("work") : bridge.newTask(); break;
        case "newcode": case "newwork": bridge.newTaskMode("work"); break;
        case "search": window.focusSearch(); break;
        case "models": models.open(); break;
        case "settings": settings.show(settings.generalPage); break;
        case "shortcuts": shortcuts.open(); break;
        case "sidebar": window.toggleSidebar(); break;
        case "dock": window.toggleDock(); break;
        case "reset-dock-tools": if (window.dockState) window.dockState.resetTabLayout(); break;
        case "files": window.openDock("files"); break;
        case "focus-editor": if (window.dockState && window.dockState.filePath) editorFocus.open(); else window.openDock("files"); break;
        case "terminal-panel": window.openDock("terminal"); break;
        case "changes": window.openDock("changes"); break;
        case "context": window.openDock("context"); break;
        case "memory": window.openDock("memory"); break;
        case "activity": window.openDock("activity"); break;
        case "browser": window.openDock("browser"); break;
        case "preview": window.openDock("preview"); break;
        case "quickbar": window.openQuickBar(); break;
        case "screenshot": bridge.attachScreenshot(); break;
        case "window": bridge.attachWindow(); break;
        case "region": bridge.attachRegion(); break;
        case "file": bridge.attachFile(); break;
        case "folder": bridge.attachFolder(); break;
        case "clipboard": bridge.attachClipboard(); break;
        case "project": bridge.chooseProject(); break;
        case "reveal": bridge.revealPath(bridge.projectPath); break;
        case "copypath": bridge.copyProjectPath(); break;
        case "terminal": bridge.openTerminalHere(); break;
        case "desktop": bridge.toggleDesktop(); break;
        case "permission": settings.show(settings.agentPage); break;
        case "runtime": settings.show(settings.modelPage); break;
        case "compose": composer.focusInput(); break;
        case "regenerate": bridge.regenerate(); break;
        case "stop": bridge.stop(); break;
        case "export": bridge.exportTask(); break;
        case "duplicate": bridge.duplicateTask(); break;
        case "pin": if (bridge.taskId) bridge.togglePin(bridge.taskId); break;
        case "clear": if (bridge.taskId) clearSheet.open(); break;
        case "reconnect": case "retry": bridge.refreshModels(); break;
        case "previous": bridge.openAdjacentTask(-1); break;
        case "next": bridge.openAdjacentTask(1); break;
        }
    }
}
