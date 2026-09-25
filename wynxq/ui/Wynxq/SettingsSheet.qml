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
    property var appBridge: bridge
    objectName: "settingsSheet"
    title: "Settings"
    background: Rectangle {
        color: Theme.background
        radius: Theme.r4
        border.color: Theme.border
        border.width: 1
    }
    width: Math.min(page === usagePage ? 980 : 860, parent ? parent.width - Theme.s6 : 860)
    height: Math.min(page === usagePage ? 760 : page === appearancePage ? 700 : 560, parent ? parent.height - Theme.s6 : 560)
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
    function showAgentMemory() {
        page = agentPage;
        open();
        memoryScrollTimer.restart();
    }
    Timer {
        id: memoryScrollTimer
        interval: 160
        repeat: false
        onTriggered: {
            var flick = settingsScroll.contentItem;
            if (flick)
                flick.contentY = Math.max(0, flick.contentHeight - settingsScroll.availableHeight);
        }
    }

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
        generalSettingsPage.prepare();
        modelSettingsPage.prepare();
        appearanceSettingsPage.prepare();
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 176
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

                        scale: down ? Theme.pressScale : 1
                        Behavior on scale {
                            enabled: !Theme.reducedMotion
                            NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
                        }
                        background: Rectangle {
                            radius: Theme.r1
                            color: sheet.page === index ? Theme.surfaceRaised
                                 : pageButton.down ? Theme.surfacePressed
                                 : pageButton.hovered ? Theme.surfaceHover : "transparent"
                            border.width: pageButton.visualFocus ? 1 : 0
                            border.color: Theme.accentEdge
                            Behavior on color {
                                enabled: !Theme.reducedMotion
                                ColorAnimation { duration: Theme.fast }
                            }
                        }
                        contentItem: Row {
                            leftPadding: Theme.s2
                            spacing: Theme.s2
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
                    text: bridge && bridge.appVersion ? "v" + bridge.appVersion : ""
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                }
            }
        }

        ScrollView {
            id: settingsScroll
            objectName: "settingsScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: WScrollBar {}

            Item {
                width: sheet.width - 176
                readonly property Item current: stack.children[sheet.page] || null
                implicitHeight: (current ? current.implicitHeight : 0) + Theme.s5 + Theme.s6

                StackLayout {
                    id: stack
                    width: parent.width - Theme.s5 * 2
                    x: Theme.s5
                    y: Theme.s5
                    currentIndex: sheet.page

                    // ------------------------------------------------ GENERAL
                    SettingsGeneralPage {
                        id: generalSettingsPage
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }

                    // ----------------------------------------- MODEL & RUNTIME
                    SettingsModelPage {
                        id: modelSettingsPage
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }

                    // -------------------------------------------------- AGENT
                    SettingsAgentPage {
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }

                    // ---------------------------------------------- WORKSPACE
                    SettingsWorkspacePage {
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }


                    // --------------------------------------------------- USAGE
                    SettingsUsagePage {
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }

                    // --------------------------------------------- APPEARANCE
                    SettingsAppearancePage {
                        id: appearanceSettingsPage
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }

                    // ----------------------------------------------- ADVANCED
                    SettingsAdvancedPage {
                        bridge: sheet.appBridge
                        hostSheet: sheet
                    }
                }
            }
        }
    }

}
