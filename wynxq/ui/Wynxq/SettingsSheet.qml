import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Seven sections, each answering one question.

    Anything with a home in the interface itself is not repeated here: models
    are chosen in the composer, the project is chosen in the sidebar, and
    shortcuts are a reference sheet rather than a settings page.
*/
Sheet {
    id: sheet
    objectName: "settingsSheet"
    title: "Settings"
    width: Math.min(900, parent ? parent.width - Theme.s6 : 900)
    height: Math.min(580, parent ? parent.height - Theme.s6 : 580)
    signal openModelManager()
    signal openMemoryPanel()

    readonly property int generalPage: 0
    readonly property int modelPage: 1
    readonly property int agentPage: 2
    readonly property int workspacePage: 3
    readonly property int usagePage: 4
    readonly property int appearancePage: 5
    readonly property int advancedPage: 6

    property int page: 0
    property string settingsQuery: ""
    readonly property var pages: [
        { label: "General", icon: "sliders", keywords: "ollama server connection notification startup tray" },
        { label: "Model & runtime", icon: "layers", keywords: "model context tokens temperature keep alive speed fast balanced deep runtime" },
        { label: "Agent", icon: "cursor", keywords: "agent screen desktop control permission ask auto autopilot memory stop" },
        { label: "Workspace", icon: "panel", keywords: "workspace dock project files terminal browser panel sidebar" },
        { label: "Usage", icon: "bolt", keywords: "usage tokens speed throughput input output runs statistics" },
        { label: "Appearance", icon: "sun", keywords: "appearance theme accent glass density compact motion font" },
        { label: "Advanced", icon: "shield", keywords: "advanced endpoint privacy debug reset system" },
    ]

    function pageMatches(entry) {
        var q = settingsQuery.toLowerCase().trim();
        if (!q) return true;
        return (entry.label + " " + (entry.keywords || "")).toLowerCase().indexOf(q) >= 0;
    }
    function applySettingsSearch() {
        var q = settingsQuery.trim();
        if (!q || pageMatches(pages[page])) return;
        for (var i = 0; i < pages.length; i++) {
            if (pageMatches(pages[i])) {
                page = i;
                return;
            }
        }
    }
    function show(index) { page = index; open(); }

    function formatUsageCount(value) {
        var count = Math.max(0, Math.round(Number(value) || 0));
        if (count >= 1000000000) return (count / 1000000000).toFixed(count >= 10000000000 ? 1 : 2) + "B";
        if (count >= 1000000) return (count / 1000000).toFixed(count >= 10000000 ? 1 : 2) + "M";
        if (count >= 1000) return (count / 1000).toFixed(count >= 10000 ? 1 : 2) + "K";
        return String(count);
    }

    function usageBucket(name) {
        if (!bridge || !bridge.tokenUsage) return ({ tokens: 0, outputTokens: 0, promptTokens: 0, runs: 0, averageRate: 0 });
        return bridge.tokenUsage[name] || ({ tokens: 0, outputTokens: 0, promptTokens: 0, runs: 0, averageRate: 0 });
    }

    function maxUsage(rows) {
        var maximum = 1;
        rows = rows || [];
        for (var i = 0; i < rows.length; i++)
            maximum = Math.max(maximum, Number(rows[i].tokens || 0));
        return maximum;
    }

    onPageChanged: if (visible && page === usagePage && bridge) bridge.refreshTokenUsage()

    onOpened: {
        settingsQuery = "";
        settingsSearch.text = "";
        if (bridge) bridge.refreshTokenUsage();
        endpointNameField.text = "";
        endpointField.text = "";
        accentField.text = bridge ? bridge.accentColor : "";
        ctxField.text = bridge ? bridge.numCtx : "";
        tempField.text = bridge ? bridge.temperature : "";
        keepField.text = bridge ? bridge.keepAlive : "";
        stepsField.text = bridge ? bridge.maxSteps : "";
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 186
            Layout.fillHeight: true
            color: Theme.backgroundSoft
            bottomLeftRadius: Theme.r4
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.borderSubtle }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.s2
                spacing: 1

                Field {
                    id: settingsSearch
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.controlSmall
                    Layout.bottomMargin: Theme.s2
                    iconName: "search"
                    placeholderText: "Find settings"
                    font.pixelSize: Theme.caption
                    onTextChanged: {
                        sheet.settingsQuery = text;
                        sheet.applySettingsSearch();
                    }
                    Keys.onEscapePressed: function(event) {
                        if (text.length) { text = ""; event.accepted = true; }
                        else event.accepted = false;
                    }
                }

                Repeater {
                    model: sheet.pages
                    delegate: AbstractButton {
                        id: pageButton
                        required property var modelData
                        required property int index
                        readonly property bool matchesSearch: sheet.pageMatches(modelData)
                        Layout.fillWidth: true
                        Layout.preferredHeight: matchesSearch ? Theme.rowHeight : 0
                        visible: matchesSearch
                        hoverEnabled: true
                        Accessible.name: modelData.label
                        Accessible.checked: sheet.page === index
                        onClicked: sheet.page = index

                        background: Rectangle {
                            radius: Theme.r2
                            color: sheet.page === index ? Theme.surfaceSelected
                                 : pageButton.hovered ? Theme.surfaceHover : "transparent"
                            border.width: pageButton.visualFocus ? 2 : 0
                            border.color: Theme.accentEdge
                            Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                        }
                        contentItem: Row {
                            leftPadding: Theme.s3
                            spacing: Theme.s3
                            Icon {
                                name: modelData.icon
                                ink: sheet.page === index ? Theme.accent : Theme.textMuted
                                width: 14; height: 14
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: modelData.label
                                color: sheet.page === index ? Theme.textPrimary : Theme.textSecondary
                                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                    }
                }
                Item { Layout.fillHeight: true }
                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.s3
                    Layout.bottomMargin: Theme.s2
                    text: "Wynxq " + (bridge ? bridge.appVersion : "")
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: WScrollBar {}

            Item {
                width: sheet.width - 186
                readonly property Item current: stack.children[sheet.page] || null
                implicitHeight: (current ? current.implicitHeight : 0) + Theme.s5 + Theme.s7

                StackLayout {
                    id: stack
                    width: parent.width - Theme.s6 * 2
                    x: Theme.s6
                    y: Theme.s5
                    currentIndex: sheet.page

                    // ------------------------------------------------ GENERAL
                    Column {
                        spacing: Theme.s6
                        Group {
                            title: "Ollama servers"
                            description: "Keep several Ollama machines. The default starts new chats; each existing chat remembers its own server and model."

                            Repeater {
                                model: bridge ? bridge.endpointProfiles : []
                                delegate: Rectangle {
                                    id: endpointRow
                                    required property var modelData
                                    width: parent.width
                                    implicitHeight: 48
                                    radius: Theme.r2
                                    color: modelData.selected ? Theme.surfaceSelected : "transparent"
                                    border.width: 1
                                    border.color: modelData.selected ? Theme.borderStrong : Theme.borderSubtle

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: Theme.s3
                                        anchors.rightMargin: Theme.s2
                                        spacing: Theme.s2
                                        StatusDot {
                                            tone: modelData.selected && bridge && bridge.online
                                                ? Theme.success : Theme.textDisabled
                                            Layout.preferredWidth: 7; Layout.preferredHeight: 7
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 1
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: Theme.s2
                                                Text {
                                                    text: modelData.name
                                                    color: Theme.textPrimary
                                                    font.family: Theme.sansFamily
                                                    font.pixelSize: Theme.label
                                                    font.weight: Font.Medium
                                                }
                                                Text {
                                                    visible: modelData.default
                                                    text: "DEFAULT"
                                                    color: Theme.textMuted
                                                    font.family: Theme.monoFamily
                                                    font.pixelSize: Theme.micro
                                                }
                                                Text {
                                                    visible: modelData.selected
                                                    text: "THIS CHAT"
                                                    color: Theme.success
                                                    font.family: Theme.monoFamily
                                                    font.pixelSize: Theme.micro
                                                }
                                                Item { Layout.fillWidth: true }
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: modelData.url
                                                color: Theme.textMuted
                                                font.family: Theme.monoFamily
                                                font.pixelSize: Theme.micro
                                                elide: Text.ElideMiddle
                                            }
                                        }
                                        WButton {
                                            visible: !modelData.selected
                                            text: "Use"
                                            variant: "ghost"
                                            compactPadding: true
                                            enabled: bridge && !bridge.busy
                                            onClicked: if (bridge) bridge.selectEndpoint(modelData.url)
                                        }
                                        WButton {
                                            visible: !modelData.default
                                            text: "Default"
                                            variant: "ghost"
                                            compactPadding: true
                                            onClicked: if (bridge) bridge.setDefaultEndpoint(modelData.url)
                                        }
                                        IconButton {
                                            visible: !modelData.default && !modelData.selected
                                            width: 28; height: 28; iconSize: 12
                                            iconName: "close"
                                            tooltip: "Remove server"
                                            onClicked: if (bridge) bridge.removeEndpointProfile(modelData.url)
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                width: parent.width
                                spacing: Theme.s2
                                Field {
                                    id: endpointNameField
                                    Layout.preferredWidth: 120
                                    placeholderText: "Server name"
                                    Accessible.name: "Ollama server name"
                                }
                                Field {
                                    id: endpointField
                                    Layout.fillWidth: true
                                    mono: true
                                    placeholderText: "http://192.168.178.29:11434"
                                    Accessible.name: "Ollama server URL"
                                    onAccepted: addEndpoint.clicked()
                                }
                                WButton {
                                    id: addEndpoint
                                    text: "Add"
                                    variant: "primary"
                                    onClicked: if (bridge && bridge.addEndpointProfile(
                                        endpointNameField.text, endpointField.text)) {
                                        endpointNameField.text = "";
                                        endpointField.text = "";
                                    }
                                }
                            }

                            RowLayout {
                                width: parent.width
                                spacing: Theme.s2
                                StatusDot {
                                    tone: bridge && bridge.online ? Theme.success : Theme.danger
                                    Layout.preferredWidth: 7; Layout.preferredHeight: 7
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: !bridge ? ""
                                        : bridge.online
                                            ? bridge.endpointProfileName + " · " + bridge.models.length
                                              + " model" + (bridge.models.length === 1 ? "" : "s")
                                            : bridge.endpointProfileName + " · not connected"
                                    color: bridge && bridge.online ? Theme.textSecondary : Theme.textMuted
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                }
                                WButton {
                                    text: "Reconnect"
                                    iconName: "retry"
                                    variant: "ghost"
                                    compactPadding: true
                                    onClicked: if (bridge) bridge.refreshModels()
                                }
                            }

                            Text {
                                width: parent.width
                                text: bridge ? bridge.endpointPrivacyHint : ""
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                            Rectangle {
                                width: parent.width
                                visible: bridge && bridge.endpointScope === "remote"
                                         && String(bridge.endpoint).indexOf("http://") === 0
                                implicitHeight: insecureText.implicitHeight + Theme.s3 * 2
                                radius: Theme.r2
                                color: Theme.warningMuted
                                border.width: 1
                                border.color: Theme.alpha(Theme.warning, 0.35)
                                Text {
                                    id: insecureText
                                    anchors.fill: parent
                                    anchors.margins: Theme.s3
                                    text: "This remote server uses plain HTTP. Prefer HTTPS or a trusted private tunnel before sending screenshots or sensitive files."
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                    wrapMode: Text.WordWrap; lineHeight: 1.45
                                }
                            }
                        }
                        Group {
                            title: "Behaviour"
                            Toggle {
                                width: parent.width
                                text: "Desktop notifications"
                                description: "Tell me when a long task finishes and Wynxq is not focused."
                                checked: bridge ? bridge.notificationsEnabled : true
                                onSwitched: function(value) { if (bridge) bridge.setFlag("notifications", value); }
                            }
                            Toggle {
                                width: parent.width
                                text: "System tray icon"
                                description: "Keep Wynxq reachable from the tray. Takes effect on restart."
                                checked: bridge ? bridge.trayEnabled : false
                                onSwitched: function(value) { if (bridge) bridge.setFlag("tray", value); }
                            }
                        }
                    }

                    // ----------------------------------------- MODEL & RUNTIME
                    Column {
                        spacing: Theme.s6
                        Group {
                            title: "Current chat model"
                            description: "This chat's model. Server + model switching lives together in the composer picker; the server default for new chats is managed under General."
                            Row {
                                spacing: Theme.s3
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: bridge ? bridge.model : ""
                                    color: Theme.textPrimary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                    font.weight: Font.Medium
                                }
                                WButton {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "Manage models"
                                    iconName: "layers"
                                    onClicked: { sheet.close(); sheet.openModelManager(); }
                                }
                            }
                            Text {
                                width: parent.width
                                text: bridge ? bridge.modelCapabilityHint : ""
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                        }
                        Group {
                            title: "Speed"
                            description: bridge ? bridge.runtimeHint : ""
                            Segmented {
                                width: Math.min(parent.width, 400)
                                options: [
                                    { id: "Fast", label: "Fast", detail: "Low latency" },
                                    { id: "Balanced", label: "Balanced", detail: "Everyday default" },
                                    { id: "Deep", label: "Deep", detail: "More context and reasoning" },
                                    { id: "Custom", label: "Custom", detail: "Your own values" },
                                ]
                                current: bridge ? bridge.runtimePreset : "Balanced"
                                onSelected: function(value) {
                                    if (value === "Custom" || !bridge) return;
                                    bridge.applyRuntimePreset(value);
                                    ctxField.text = bridge.numCtx; tempField.text = bridge.temperature;
                                    keepField.text = bridge.keepAlive; stepsField.text = bridge.maxSteps;
                                }
                            }
                            Toggle {
                                width: parent.width
                                text: "Let the model think before answering"
                                description: "Uses the model's reasoning mode where Ollama reports support for it."
                                checked: bridge ? bridge.thinking : false
                                onSwitched: function(value) { if (bridge) bridge.setFlag("think", value); }
                            }
                        }
                        Disclosure {
                            width: parent.width
                            title: "Advanced generation options"
                            hint: "Ollama options. Saving these switches the preset to Custom."
                            Grid {
                                id: advancedGrid
                                width: parent.width
                                columns: width > 460 ? 2 : 1
                                columnSpacing: Theme.s3
                                rowSpacing: Theme.s3
                                property real cellWidth: columns === 2 ? (width - columnSpacing) / 2 : width

                                Column {
                                    width: advancedGrid.cellWidth
                                    spacing: Theme.s2
                                    FieldLabel { text: "Context tokens" }
                                    Field { id: ctxField; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly }
                                }
                                Column {
                                    width: advancedGrid.cellWidth
                                    spacing: Theme.s2
                                    FieldLabel { text: "Temperature" }
                                    Field { id: tempField; width: parent.width }
                                }
                                Column {
                                    width: advancedGrid.cellWidth
                                    spacing: Theme.s2
                                    FieldLabel { text: "Keep model loaded" }
                                    Field { id: keepField; width: parent.width; placeholderText: "5m" }
                                }
                                Column {
                                    width: advancedGrid.cellWidth
                                    spacing: Theme.s2
                                    FieldLabel { text: "Desktop action budget" }
                                    Field { id: stepsField; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly }
                                }
                            }
                            WButton {
                                text: "Save runtime settings"
                                variant: "primary"
                                enabled: bridge && !bridge.busy
                                onClicked: if (bridge) bridge.saveRuntimeSettings(ctxField.text, tempField.text,
                                                                                 keepField.text, stepsField.text)
                            }
                        }
                    }

                    // -------------------------------------------------- AGENT
                    Column {
                        spacing: Theme.s6
                        Group {
                            title: "Local copilot"
                            description: "Ask Wynxq to open apps, run commands, inspect files or help with code. Tools execute on this computer even when Ollama inference runs on another server. Commands run in your workspace folder, or your home folder when none is selected."
                        }
                        Group {
                            title: "Screen control"
                            description: "Wynxq can see your screen and use your mouse and keyboard. It starts off every time Wynxq opens."
                            Row {
                                spacing: Theme.s3
                                WButton {
                                    text: !(bridge && bridge.desktopAvailable) ? "Unavailable here"
                                        : bridge && bridge.desktopEnabled ? "Turn off screen control"
                                        : "Turn on screen control"
                                    iconName: "cursor"
                                    variant: bridge && bridge.desktopEnabled ? "secondary" : "primary"
                                    enabled: bridge && !bridge.connecting && bridge.desktopAvailable
                                    onClicked: if (bridge) bridge.toggleDesktop()
                                }
                                Row {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: Theme.s2
                                    StatusDot {
                                        anchors.verticalCenter: parent.verticalCenter
                                        tone: bridge && bridge.desktopEnabled ? Theme.accent : Theme.textMuted
                                        pulsing: bridge && bridge.desktopEnabled && bridge.busy
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: bridge && bridge.desktopEnabled ? "On" : "Off"
                                        color: Theme.textSecondary
                                        font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                    }
                                }
                            }
                            Text {
                                width: parent.width
                                text: bridge ? bridge.desktopBackend + " — " + bridge.desktopDetail : ""
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                visible: bridge && bridge.desktopRemembered
                                Icon { name: "check"; ink: Theme.success; width: 13; height: 13
                                       anchors.verticalCenter: parent.verticalCenter }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "Your desktop remembered this permission, so it did not ask again."
                                    color: Theme.textMuted
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                }
                            }
                        }

                        Group {
                            title: "Stopping a run"
                            description: "Escape stops generation and desktop actions whenever Wynxq has focus. While a model is driving another window, Wynxq does not — so it also asks your desktop for a shortcut that works from anywhere."
                            Row {
                                spacing: Theme.s2
                                visible: !!(bridge && bridge.desktopStopShortcut)
                                Icon { name: "keyboard"; ink: Theme.textMuted; width: 14; height: 14
                                       anchors.verticalCenter: parent.verticalCenter }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "Stop from anywhere"
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                }
                                KeyHint {
                                    anchors.verticalCenter: parent.verticalCenter
                                    keys: bridge ? bridge.desktopStopShortcut : ""
                                }
                            }
                            Text {
                                width: parent.width
                                visible: !!(bridge && bridge.desktopStopDetail) && !(bridge && bridge.desktopStopShortcut)
                                text: bridge ? bridge.desktopStopDetail : ""
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                            Text {
                                width: parent.width
                                visible: !(bridge && bridge.desktopEnabled)
                                text: "Turn screen control on to see which key your desktop assigned."
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                        }
                        Group {
                            title: "Permission"
                            description: "How much Wynxq may do — commands as well as the desktop — without asking first. It applies to Work and Wynxi tasks. A Chat task has no tools at all, so nothing there is ever approved."
                            Repeater {
                                model: bridge ? bridge.permissionModes : []
                                delegate: AbstractButton {
                                    id: mode
                                    required property var modelData
                                    readonly property bool current: bridge && bridge.permissionMode === modelData.id
                                    width: parent.width
                                    implicitHeight: 54
                                    hoverEnabled: true
                                    Accessible.name: modelData.label
                                    Accessible.description: modelData.detail
                                    Accessible.checked: current
                                    onClicked: if (bridge) bridge.setPermissionMode(modelData.id)

                                    background: Rectangle {
                                        radius: Theme.r2
                                        color: mode.current ? Theme.surfaceSelected
                                             : mode.hovered ? Theme.surfaceHover : "transparent"
                                        border.width: mode.current || mode.visualFocus ? 1 : 0
                                        border.color: Theme.accentEdge
                                        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                                    }
                                    contentItem: Row {
                                        leftPadding: Theme.s4
                                        spacing: Theme.s3
                                        Icon {
                                            name: mode.current ? "check" : "shield"
                                            ink: mode.current ? Theme.accent : Theme.textMuted
                                            width: 16; height: 16
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Column {
                                            anchors.verticalCenter: parent.verticalCenter
                                            spacing: 2
                                            Text {
                                                text: modelData.label; color: Theme.textPrimary
                                                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                                font.weight: Font.Medium
                                            }
                                            Text {
                                                text: modelData.detail; color: Theme.textMuted
                                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                            }
                                        }
                                    }
                                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                                }
                            }
                            Text {
                                width: parent.width
                                text: "Reading the screen and moving the pointer never prompt — they change nothing. Every run also has an action budget, set under Model & runtime."
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                        }

                        Group {
                            title: "Memory"
                            description: "One Markdown file Wynxq reads at the start of every task, in Wynxq and Wynxi alike, so what you tell it once does not have to be told again. Read it, correct it and delete from it in the Memory panel — Ctrl+Shift+M."

                            Row {
                                width: parent.width
                                spacing: Theme.s3
                                Toggle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: !!(bridge && bridge.memoryEnabled)
                                    Accessible.name: "Remember things between tasks"
                                    onSwitched: function(value) { if (bridge) bridge.setMemoryEnabled(value); }
                                }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1
                                    FieldLabel { text: "Remember things between tasks" }
                                    Text {
                                        text: bridge ? bridge.memorySummary : ""
                                        color: Theme.textMuted
                                        font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                        width: sheet.width - 420
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                WButton {
                                    text: "Open the Memory panel"
                                    variant: "secondary"
                                    onClicked: { sheet.close(); sheet.openMemoryPanel(); }
                                }
                                WButton {
                                    text: "Show memory.md"
                                    variant: "ghost"
                                    onClicked: if (bridge) bridge.revealMemory()
                                }
                            }
                            Text {
                                width: parent.width
                                text: "Notes are kept in " + (bridge ? bridge.memoryPath : "memory.md")
                                     + ", readable only by you. Wynxq is told never to save secrets or credentials there;"
                                     + " anything you would rather it forgot can be deleted in the panel."
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                        }
                    }

                    // ---------------------------------------------- WORKSPACE
                    Column {
                        spacing: Theme.s6

                        Group {
                            title: "The dock"
                            description: "Files, Terminal, Changes, Context, Memory, Activity, Browser and Preview live on the right. Closing the workspace removes the panel and rail together; restore it from the lower-right button or Ctrl+Shift+B."

                            Row {
                                width: parent.width
                                spacing: Theme.s3
                                Toggle {
                                    id: dockToggle
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: !!(bridge && bridge.workspaceDock && bridge.workspaceDock.visible)
                                    Accessible.name: "Open the workspace dock"
                                    onToggled: if (bridge && bridge.workspaceDock)
                                                   bridge.workspaceDock.setVisible(checked)
                                }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1
                                    FieldLabel { text: "Open the dock panel" }
                                    Text {
                                        text: "Remembered between sessions, along with its width and the tab you left open."
                                        color: Theme.textMuted
                                        font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                        width: sheet.width - 420
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: Theme.s3
                                Toggle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: !!(bridge && bridge.workspaceDock && bridge.workspaceDock.showHidden)
                                    Accessible.name: "Show hidden files in the tree"
                                    onToggled: if (bridge && bridge.workspaceDock)
                                                   bridge.workspaceDock.setShowHidden(checked)
                                }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 1
                                    FieldLabel { text: "Show dotfiles in the file tree" }
                                    Text {
                                        text: "Build folders and caches stay hidden either way."
                                        color: Theme.textMuted
                                        font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                    }
                                }
                            }
                        }

                        Group {
                            title: "Terminal"
                            description: "The Terminal panel runs a real shell in the project folder, with your own environment. It starts when you first open the panel and stays open for the session."

                            Row {
                                width: parent.width
                                spacing: Theme.s3
                                Column {
                                    spacing: 2
                                    FieldLabel { text: "Shell" }
                                    Text {
                                        text: bridge && bridge.workspaceDock && bridge.workspaceDock.terminalShell
                                              ? bridge.workspaceDock.terminalShell : "Your login shell ($SHELL)"
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                                    }
                                }
                                Item { width: Theme.s5; height: 1 }
                                Column {
                                    spacing: 2
                                    FieldLabel { text: "Working directory" }
                                    Text {
                                        text: bridge && bridge.workspaceDock && bridge.workspaceDock.terminalDirectoryLabel
                                              ? bridge.workspaceDock.terminalDirectoryLabel : "The project folder, or home"
                                        color: Theme.textSecondary
                                        font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                                    }
                                }
                            }

                            WButton {
                                text: "Restart the shell"
                                iconName: "retry"
                                compactPadding: true
                                enabled: !!(bridge && bridge.workspaceDock)
                                onClicked: if (bridge && bridge.workspaceDock) bridge.workspaceDock.restartTerminal()
                            }
                        }

                        Group {
                            title: "Browser"
                            description: "A page opens beside the conversation instead of pulling you out of Wynxq. Nothing on it reaches the model until you attach it."

                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                StatusDot {
                                    anchors.verticalCenter: parent.verticalCenter
                                    tone: bridge && bridge.workspaceDock && bridge.workspaceDock.browserAvailable
                                          ? Theme.success : Theme.textMuted
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - Theme.s5
                                    text: bridge && bridge.workspaceDock && bridge.workspaceDock.browserAvailable
                                          ? "Qt WebEngine is available on this system."
                                          : (bridge && bridge.workspaceDock ? bridge.workspaceDock.browserUnavailableReason : "")
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Text {
                                width: parent.width
                                text: "Pop-ups, screen capture and permission requests are refused; only http and https addresses are opened."
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.45
                            }
                        }

                        Group {
                            title: "Changes"
                            description: "Uncommitted work is read from Git in the project folder. Discarding a file's changes always asks first."

                            Row {
                                width: parent.width
                                spacing: Theme.s2
                                StatusDot {
                                    anchors.verticalCenter: parent.verticalCenter
                                    tone: bridge && bridge.workspaceDock && bridge.workspaceDock.isRepository
                                          ? Theme.success : Theme.textMuted
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: !bridge || !bridge.workspaceDock ? ""
                                        : !bridge.projectPath ? "No project is open."
                                        : bridge.workspaceDock.isRepository
                                          ? "Tracking " + bridge.workspaceDock.branch
                                          : "The project folder is not a Git repository."
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                }
                            }
                        }
                    }


                    // --------------------------------------------------- USAGE
                    Column {
                        spacing: Theme.s6
                        Group {
                            title: "Recorded token usage"
                            description: "Exact completed Ollama accounting. Total is input + output; cached input is already part of input and is never counted twice."

                            Repeater {
                                model: [
                                    { key: "today", label: "TODAY" },
                                    { key: "week", label: "THIS WEEK" },
                                    { key: "month", label: "THIS MONTH" },
                                    { key: "allTime", label: "ALL TIME" },
                                ]
                                delegate: Column {
                                    required property var modelData
                                    required property int index
                                    readonly property var bucketData: sheet.usageBucket(modelData.key)
                                    width: parent ? parent.width : 0
                                    spacing: Theme.s2

                                    RowLayout {
                                        width: parent.width
                                        spacing: Theme.s4
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2
                                            Text {
                                                text: modelData.label
                                                color: Theme.textMuted
                                                font.family: Theme.sansFamily
                                                font.pixelSize: Theme.micro
                                                font.weight: Font.DemiBold
                                            }
                                            Text {
                                                text: sheet.formatUsageCount(bucketData.tokens || 0) + " tokens"
                                                color: Theme.textPrimary
                                                font.family: Theme.monoFamily
                                                font.pixelSize: Theme.heading
                                                font.weight: Font.DemiBold
                                            }
                                        }
                                        ColumnLayout {
                                            Layout.alignment: Qt.AlignRight
                                            spacing: 2
                                            Text {
                                                Layout.alignment: Qt.AlignRight
                                                text: sheet.formatUsageCount(bucketData.promptTokens || 0) + " input · "
                                                      + sheet.formatUsageCount(bucketData.outputTokens || 0) + " output"
                                                color: Theme.textSecondary
                                                font.family: Theme.monoFamily
                                                font.pixelSize: Theme.caption
                                            }
                                            Text {
                                                Layout.alignment: Qt.AlignRight
                                                text: (bucketData.runs || 0) + " run" + ((bucketData.runs || 0) === 1 ? "" : "s")
                                                      + ((bucketData.averageRate || 0) > 0
                                                         ? " · " + Number(bucketData.averageRate).toFixed(1) + " tok/s avg"
                                                         : "")
                                                color: Theme.textMuted
                                                font.family: Theme.monoFamily
                                                font.pixelSize: Theme.micro
                                            }
                                        }
                                    }
                                    Rectangle {
                                        visible: index < 3
                                        width: parent.width
                                        height: 1
                                        color: Theme.borderSubtle
                                    }
                                }
                            }
                        }

                        Group {
                            title: "Last 7 days"
                            description: "A quiet local trend from exact completed runs — no cloud analytics."
                            visible: bridge && bridge.tokenUsageDays && bridge.tokenUsageDays.length > 0

                            RowLayout {
                                width: parent.width
                                spacing: Theme.s3
                                Repeater {
                                    model: bridge ? bridge.tokenUsageDays : []
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: Theme.s1

                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 48
                                            Rectangle {
                                                anchors.bottom: parent.bottom
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                width: Math.max(8, parent.width * 0.48)
                                                height: Math.max(2, parent.height
                                                    * (Number(modelData.tokens || 0)
                                                       / sheet.maxUsage(bridge ? bridge.tokenUsageDays : [])))
                                                radius: Theme.r1
                                                color: Number(modelData.tokens || 0) > 0 ? Theme.accent : Theme.surfaceHover
                                            }
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: modelData.label || ""
                                            color: Theme.textMuted
                                            font.family: Theme.monoFamily
                                            font.pixelSize: Theme.micro
                                        }
                                        Text {
                                            Layout.alignment: Qt.AlignHCenter
                                            text: sheet.formatUsageCount(modelData.tokens || 0)
                                            color: Theme.textSecondary
                                            font.family: Theme.monoFamily
                                            font.pixelSize: Theme.micro
                                        }
                                    }
                                }
                            }
                        }

                        Group {
                            title: "Models · last 30 days"
                            description: "Which local models handled the work, ranked by exact input + output tokens."
                            visible: bridge && bridge.tokenUsageModels && bridge.tokenUsageModels.length > 0
                            readonly property real maximum: sheet.maxUsage(bridge ? bridge.tokenUsageModels : [])

                            Repeater {
                                model: bridge ? bridge.tokenUsageModels : []
                                delegate: Column {
                                    required property var modelData
                                    width: parent ? parent.width : 0
                                    spacing: Theme.s1

                                    RowLayout {
                                        width: parent.width
                                        spacing: Theme.s3
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.name || "Unknown model"
                                            color: Theme.textSecondary
                                            font.family: Theme.monoFamily
                                            font.pixelSize: Theme.caption
                                            elide: Text.ElideMiddle
                                        }
                                        Text {
                                            text: sheet.formatUsageCount(modelData.tokens || 0)
                                                  + ((modelData.averageRate || 0) > 0
                                                     ? " · " + Number(modelData.averageRate).toFixed(1) + " tok/s" : "")
                                            color: Theme.textMuted
                                            font.family: Theme.monoFamily
                                            font.pixelSize: Theme.micro
                                        }
                                    }
                                    Rectangle {
                                        width: parent.width
                                        height: 4
                                        radius: 2
                                        color: Theme.surfaceSunken
                                        Rectangle {
                                            width: Math.max(parent.height, parent.width
                                                * (Number(modelData.tokens || 0)
                                                   / Math.max(1, parent.parent.parent.maximum)))
                                            height: parent.height
                                            radius: parent.radius
                                            color: Theme.accent
                                        }
                                    }
                                }
                            }
                        }

                        Group {
                            title: "Current chat"
                            description: "Completed runs recorded for the conversation that is open now. A run is added only after Ollama reports exact token metrics."
                            RowLayout {
                                width: parent.width
                                Text {
                                    text: bridge ? sheet.formatUsageCount(bridge.conversationTokens) + " tokens" : "0 tokens"
                                    color: Theme.textPrimary
                                    font.family: Theme.monoFamily
                                    font.pixelSize: Theme.heading
                                    font.weight: Font.DemiBold
                                }
                                Item { Layout.fillWidth: true }
                                Text {
                                    text: "input + output"
                                    color: Theme.textMuted
                                    font.family: Theme.sansFamily
                                    font.pixelSize: Theme.caption
                                }
                            }
                        }
                    }

                    // --------------------------------------------- APPEARANCE
                    Column {
                        spacing: Theme.s6
                        Group {
                            title: "Accent"
                            description: "One restrained highlight colour, used sparingly across the app."
                            Flow {
                                width: parent.width
                                spacing: Theme.s2
                                Repeater {
                                    model: bridge ? bridge.themes : []
                                    delegate: AbstractButton {
                                        id: swatch
                                        required property var modelData
                                        readonly property bool current: bridge && bridge.theme === modelData.name
                                        width: 96; height: 52
                                        hoverEnabled: true
                                        Accessible.name: modelData.name
                                        Accessible.checked: current
                                        onClicked: { if (bridge) bridge.setTheme(modelData.name); accentField.text = modelData.color; }
                                        background: Rectangle {
                                            radius: Theme.r2
                                            color: swatch.hovered ? Theme.surfaceHover : Theme.surface
                                            border.width: 1
                                            border.color: swatch.current || swatch.visualFocus ? Theme.accentEdge : Theme.borderSubtle
                                            Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                                        }
                                        contentItem: Column {
                                            spacing: Theme.s2
                                            topPadding: Theme.s2
                                            Rectangle {
                                                width: 22; height: 22; radius: 11
                                                color: modelData.color
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                Icon {
                                                    anchors.centerIn: parent
                                                    visible: swatch.current
                                                    name: "check"; ink: Theme.textInverse
                                                    width: 13; height: 13
                                                }
                                            }
                                            Text {
                                                text: modelData.name
                                                color: swatch.current ? Theme.textPrimary : Theme.textSecondary
                                                font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                                                anchors.horizontalCenter: parent.horizontalCenter
                                            }
                                        }
                                        MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                                    }
                                }
                            }
                            Row {
                                spacing: Theme.s2
                                width: parent.width
                                Field {
                                    id: accentField
                                    width: Math.min(200, parent.width - 100)
                                    mono: true
                                    placeholderText: "#e9e3d6"
                                    onAccepted: if (bridge) bridge.setAccent(text)
                                }
                                WButton { text: "Apply"; onClicked: if (bridge) bridge.setAccent(accentField.text) }
                            }
                        }
                        Group {
                            title: "Density and motion"
                            Segmented {
                                width: 240
                                options: [{ id: "Comfortable", label: "Comfortable" }, { id: "Compact", label: "Compact" }]
                                current: bridge ? bridge.density : "Comfortable"
                                onSelected: function(value) { if (bridge) bridge.setDensity(value); }
                            }
                            Toggle {
                                width: parent.width
                                text: "Reduce motion"
                                description: "Turn off transitions and looping animations."
                                checked: bridge ? bridge.reducedMotion : false
                                onSwitched: function(value) { if (bridge) bridge.setFlag("reduced_motion", value); }
                            }
                            Toggle {
                                width: parent.width
                                text: "Use the system font"
                                description: "Match your desktop's interface font instead of the bundled Inter."
                                checked: bridge ? bridge.systemFont : false
                                onSwitched: function(value) { if (bridge) bridge.setFlag("system_font", value); }
                            }
                            Toggle {
                                width: parent.width
                                text: "Solid dark canvas"
                                description: "A flat background instead of the layered one."
                                checked: bridge ? bridge.solidBackground : true
                                onSwitched: function(value) { if (bridge) bridge.setFlag("solid_background", value); }
                            }
                        }
                    }

                    // ----------------------------------------------- ADVANCED
                    Column {
                        spacing: Theme.s6
                        Group {
                            title: "Privacy & data path"
                            description: bridge ? bridge.endpointPrivacyHint : ""
                            Repeater {
                                model: [
                                    { icon: "layers", line: "Inference is sent only to the Ollama server URL you configure above." },
                                    { icon: "chat", line: "Task history stays in Wynxq's private SQLite database on this computer." },
                                    { icon: "camera", line: "Screenshots are not written to chat history, but a model request can send them to your configured Ollama server." },
                                    { icon: "lock", line: "Wynxq has no account, API key requirement, telemetry service, or hosted backend of its own." },
                                    { icon: "shield", line: "Server redirects and environment proxy settings are refused by the Ollama transport." },
                                ]
                                delegate: RowLayout {
                                    required property var modelData
                                    width: parent.width
                                    spacing: Theme.s3
                                    Icon { name: modelData.icon; ink: Theme.textMuted; width: 14; height: 14; Layout.alignment: Qt.AlignTop }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.line; color: Theme.textSecondary
                                        font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                        wrapMode: Text.WordWrap; lineHeight: 1.45
                                    }
                                }
                            }
                        }
                        Group {
                            title: "Local data"
                            Text {
                                width: parent.width
                                text: bridge ? bridge.dataLocation : ""
                                color: Theme.textSecondary
                                font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WrapAnywhere
                            }
                            Row {
                                spacing: Theme.s2
                                WButton {
                                    text: "Open data folder"
                                    iconName: "folder"
                                    onClicked: if (bridge) bridge.revealPath(bridge.dataLocation.replace(/\/[^/]*$/, ""))
                                }
                                WButton {
                                    text: "Replay the welcome"
                                    iconName: "retry"
                                    variant: "ghost"
                                    onClicked: { if (bridge) bridge.resetOnboarding(); sheet.close(); }
                                }
                            }
                        }
                        Group {
                            title: "Global quick bar"
                            description: "Linux gives applications no system-wide hotkey. Bind your desktop's custom shortcut to this command and the quick bar will open from anywhere."
                            Rectangle {
                                width: parent.width; height: 38; radius: Theme.r2
                                color: Theme.surfaceSunken
                                border.width: 1; border.color: Theme.borderSubtle
                                Text {
                                    anchors.left: parent.left; anchors.leftMargin: Theme.s3
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "wynxq --quick"
                                    color: Theme.textSecondary
                                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                                }
                                IconButton {
                                    anchors.right: parent.right; anchors.rightMargin: Theme.s1
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 30; height: 30; iconSize: 14
                                    iconName: "copy"; tooltip: "Copy command"
                                    onClicked: if (bridge) bridge.copyText("wynxq --quick")
                                }
                            }
                        }
                        Group {
                            title: "About"
                            Text {
                                width: parent.width
                                text: "Wynxq " + (bridge ? bridge.appVersion : "") + " — an Ollama-powered copilot for the Linux desktop. "
                                      + "Inference can run locally or on a server you choose. Desktop backend: " + (bridge ? bridge.desktopBackend : "") + ".\n\n"
                                      + "Interface type is Inter; code is set in JetBrains Mono, both under the SIL Open Font "
                                      + "License. Wynxq is an independent project and is not affiliated with Ollama or any AI vendor."
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                                wrapMode: Text.WordWrap; lineHeight: 1.5
                            }
                        }
                    }
                }
            }
        }
    }

    component Group: Column {
        property string title: ""
        property string description: ""
        default property alias groupBody: holder.data
        width: parent ? parent.width : 400
        spacing: Theme.s3
        Text {
            text: parent.title
            color: Theme.textPrimary
            font.family: Theme.sansFamily; font.pixelSize: Theme.heading
            font.weight: Font.DemiBold
        }
        Text {
            width: parent.width
            visible: parent.description !== ""
            text: parent.description
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.5
            bottomPadding: Theme.s1
        }
        Column {
            id: holder
            width: parent.width
            spacing: Theme.s3
        }
    }

    component Disclosure: Column {
        id: disclosure
        property string title: ""
        property string hint: ""
        property bool expanded: false
        default property alias disclosureBody: inner.data
        width: parent ? parent.width : 400
        spacing: Theme.s3

        AbstractButton {
            id: toggle
            width: parent.width
            implicitHeight: Theme.control
            hoverEnabled: true
            Accessible.name: disclosure.title
            onClicked: disclosure.expanded = !disclosure.expanded
            background: Rectangle {
                radius: Theme.r2
                color: toggle.hovered ? Theme.surfaceHover : "transparent"
                border.width: toggle.visualFocus ? 2 : 0
                border.color: Theme.accentEdge
            }
            contentItem: Row {
                spacing: Theme.s2
                Icon {
                    name: disclosure.expanded ? "down" : "chevron"
                    ink: Theme.textSecondary; width: 13; height: 13
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: disclosure.title
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.heading
                    font.weight: Font.DemiBold
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
        }
        Text {
            width: parent.width
            visible: disclosure.expanded && disclosure.hint !== ""
            text: disclosure.hint
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.5
        }
        Column {
            id: inner
            width: parent.width
            spacing: Theme.s3
            visible: disclosure.expanded
            height: visible ? implicitHeight : 0
        }
    }

    component FieldLabel: Text {
        color: Theme.textSecondary
        font.family: Theme.sansFamily
        font.pixelSize: Theme.caption
    }
}