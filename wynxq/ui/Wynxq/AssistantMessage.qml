import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Agent output is content first: no avatar, no decorative byline, no bubble.
    Only live state, optional reasoning and the result itself remain.
*/
Item {
    id: root
    property string body: ""
    property string thought: ""
    property var blocks: []
    property string tail: ""
    property string tailKind: "markdown"
    property string tailLanguage: ""
    property string tailLabel: ""
    property bool streaming: false
    property real thinkSeconds: 0
    property bool thinkDone: false
    property bool latest: false
    property int row: -1
    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property bool showGitSummary: latest && !streaming && bridge
        && bridge.taskMode === "work" && dock && dock.isRepository
        && dock.changes && dock.changes.length > 0
    signal linkClicked(string link)
    signal branched()

    // Keep the turn content-sized. A Loader/ListView must never stretch a
    // short response to the viewport and strand its actions at the bottom.
    implicitHeight: Math.ceil(column.implicitHeight)
    height: implicitHeight
    property bool thoughtOpen: false
    function resetTransientState() {
        thoughtOpen = false;
        responseMenu.close();
    }
    function retryWithPreset(name) {
        if (bridge && bridge.canRegenerate)
            bridge.regenerateWithPreset(name);
    }
    Accessible.role: Accessible.StaticText
    Accessible.name: (root.streaming ? "Agent is replying: " : "Agent said: ") + root.body

    Column {
        id: column
        width: parent.width
        spacing: Theme.s2

        Row {
            visible: root.streaming
            height: visible ? 18 : 0
            spacing: Theme.s2
            ActivityGlyph {
                running: root.streaming
                tone: Theme.success
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: root.body.length === 0
                    ? (bridge && bridge.taskMode === "work" ? "Thinking through the task" : "Thinking")
                    : (bridge && bridge.taskMode === "work" ? "Working" : "Writing")
                color: Theme.textMuted
                font.family: Theme.monoFamily
                font.pixelSize: Theme.micro
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Item {
            width: parent.width
            visible: root.thought.length > 0
            height: visible ? thoughtHeader.height + (root.thoughtOpen ? thoughtBody.height + Theme.s2 : 0) : 0

            AbstractButton {
                id: thoughtHeader
                width: Math.min(thoughtRow.implicitWidth + Theme.s2 * 2, parent.width)
                height: 23
                hoverEnabled: true
                Accessible.name: thoughtLabel.text
                onClicked: root.thoughtOpen = !root.thoughtOpen
                background: Rectangle {
                    radius: Theme.r1
                    color: thoughtHeader.hovered ? Theme.surfaceHover : "transparent"
                    border.width: thoughtHeader.visualFocus ? 1 : 0
                    border.color: Theme.accentEdge
                }
                contentItem: Row {
                    id: thoughtRow
                    spacing: Theme.s2
                    leftPadding: Theme.s2
                    Icon {
                        name: root.thoughtOpen ? "down" : "chevron"
                        ink: Theme.textMuted
                        width: 11; height: 11
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        id: thoughtLabel
                        anchors.verticalCenter: parent.verticalCenter
                        text: !root.thinkDone ? "Thinking…"
                            : root.thinkSeconds > 0 ? "Thought for " + root.thinkSeconds.toFixed(1) + "s"
                            : "Reasoning"
                        color: Theme.textMuted
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.micro
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
            }

            Rectangle {
                id: thoughtBody
                anchors.top: thoughtHeader.bottom
                anchors.topMargin: Theme.s2
                width: parent.width
                height: root.thoughtOpen ? thoughtText.implicitHeight + Theme.s3 * 2 : 0
                visible: root.thoughtOpen
                radius: Theme.r2
                color: Theme.surfaceSunken
                border.width: 1
                border.color: Theme.borderSubtle
                TextEdit {
                    id: thoughtText
                    anchors.fill: parent
                    anchors.margins: Theme.s3
                    text: root.thought
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    color: Theme.textMuted
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                }
            }
        }

        Repeater {
            model: root.blocks
            delegate: Loader {
                required property var modelData
                width: column.width
                // For prose, use the rendered document height directly. Qt's
                // TextEdit implicitHeight can lag a rich-text relayout; code
                // cards already expose a stable implicitHeight.
                height: item ? Math.ceil(modelData.kind === "code"
                    ? item.implicitHeight : item.contentHeight) : 0
                sourceComponent: modelData.kind === "code" ? codeBlock : proseBlock
                onLoaded: {
                    item.blockText = modelData.text;
                    if (modelData.kind === "code") {
                        item.blockLanguage = modelData.language;
                        item.blockLabel = modelData.label;
                        item.blockRunnable = modelData.runnable;
                    }
                }
            }
        }

        Loader {
            width: column.width
            active: root.tail.length > 0
            height: active && item ? Math.ceil(root.tailKind === "code"
                ? item.implicitHeight : item.contentHeight) : 0
            sourceComponent: root.tailKind === "code" ? codeBlock : proseBlock
            onLoaded: {
                item.blockText = Qt.binding(function() { return root.tail; });
                item.blockStreaming = Qt.binding(function() { return root.streaming; });
                if (root.tailKind === "code") {
                    item.blockLanguage = Qt.binding(function() { return root.tailLanguage; });
                    item.blockLabel = Qt.binding(function() { return root.tailLabel; });
                }
            }
        }

        AbstractButton {
            id: gitSummary
            width: Math.min(gitRow.implicitWidth + Theme.s3 * 2, parent.width)
            height: root.showGitSummary ? 28 : 0
            visible: root.showGitSummary
            hoverEnabled: true
            Accessible.name: "Open changed files: " + (root.dock ? root.dock.changesSummary : "")
            onClicked: if (root.dock) root.dock.openTab("changes")
            background: GlassSurface {
                radius: Theme.r2
                solid: false
                glassEnabled: gitSummary.hovered || gitSummary.visualFocus
                tint: Theme.glassTintHover
                fillOpacity: gitSummary.hovered ? 0.46 : 0.0
                outlineVisible: true
                edgeColor: gitSummary.visualFocus ? Theme.accentEdge : Theme.borderSubtle
                active: gitSummary.visualFocus
                sheen: gitSummary.hovered
            }
            contentItem: Row {
                id: gitRow
                spacing: Theme.s2
                leftPadding: Theme.s2
                Icon {
                    name: "branch"
                    ink: Theme.accent
                    width: 12; height: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: root.dock ? root.dock.changesSummary : ""
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.micro
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: root.dock && root.dock.branch ? "· " + root.dock.branch : ""
                    color: Theme.textMuted
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.micro
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        WButton {
            visible: root.latest && !root.streaming && bridge && bridge.canUndoRun
            width: Math.min(implicitWidth, parent.width)
            text: bridge && bridge.undoRunSummary ? bridge.undoRunSummary : "Undo this run"
            iconName: "retry"
            variant: "ghost"
            compactPadding: true
            ToolTip.visible: hovered
            ToolTip.text: "Restore only files changed by the last agent run. Refuses if a file changed afterward."
            onClicked: if (bridge) bridge.undoLastRun()
        }

        FocusScope {
            id: actions
            objectName: "responseActions"
            width: parent.width
            height: 22
            visible: !root.streaming && root.body.length > 0
            opacity: hover.hovered || activeFocus ? 1 : root.latest ? 0.56 : 0
            Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
            RowLayout {
                anchors.fill: parent
                spacing: 2
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26; iconSize: 12
                    iconName: "copy"; tooltip: "Copy response"
                    tint: root.latest ? Theme.textSecondary : Theme.textMuted
                    activeTint: Theme.textPrimary
                    onClicked: if (bridge) bridge.copyText(root.body)
                }
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26; iconSize: 12
                    iconName: "retry"; tooltip: "Regenerate"; shortcut: "Ctrl+R"
                    tint: root.latest ? Theme.textSecondary : Theme.textMuted
                    activeTint: Theme.textPrimary
                    enabled: bridge && bridge.canRegenerate
                    onClicked: if (bridge) bridge.regenerate()
                }
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26; iconSize: 12
                    iconName: "branch"; tooltip: "Branch from here"
                    tint: root.latest ? Theme.textSecondary : Theme.textMuted
                    activeTint: Theme.textPrimary
                    onClicked: root.branched()
                }
                Text {
                    Layout.fillWidth: true
                    leftPadding: Theme.s2
                    visible: root.latest && bridge && bridge.runMetrics.hasData
                    text: bridge ? bridge.runMetrics.rate.toFixed(1) + " tokens/s · "
                                 + bridge.runMetrics.tokens + " out · "
                                 + bridge.runMetrics.totalSeconds.toFixed(1) + "s" : ""
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.micro
                    elide: Text.ElideRight
                }
                Item {
                    Layout.fillWidth: true
                    visible: !root.latest || !(bridge && bridge.runMetrics.hasData)
                }
            }
        }
    }

    HoverHandler { id: hover }

    WMenu {
        id: responseMenu
        preferredEdge: "above"
        menuWidth: 238
        items: [
            { id: "copy", label: "Copy response", icon: "copy" },
            { separator: true },
            { id: "retry", label: "Retry", detail: bridge ? "Current " + bridge.runtimePreset + " runtime" : "", icon: "retry",
              disabled: !bridge || !bridge.canRegenerate },
            { id: "retry-fast", label: "Retry · Fast", detail: "Smaller context and action budget", icon: "bolt",
              disabled: !bridge || !bridge.canRegenerate },
            { id: "retry-balanced", label: "Retry · Balanced", detail: "Everyday runtime", icon: "sliders",
              disabled: !bridge || !bridge.canRegenerate },
            { id: "retry-deep", label: "Retry · Deep", detail: "More context and action budget", icon: "layers",
              disabled: !bridge || !bridge.canRegenerate },
            { separator: true },
            { id: "branch", label: "Branch from here", icon: "branch" },
            { id: "changes", label: "Review current changes", icon: "branch",
              hidden: !root.showGitSummary },
            { id: "undo-run", label: bridge && bridge.undoRunSummary ? bridge.undoRunSummary : "Undo this run",
              detail: "Restore only files changed by the last agent run", icon: "retry",
              hidden: !root.latest || !bridge || !bridge.canUndoRun },
        ]
        onPicked: function(id) {
            if (!bridge) return;
            if (id === "copy") bridge.copyText(root.body);
            else if (id === "retry") bridge.regenerate();
            else if (id === "retry-fast") root.retryWithPreset("Fast");
            else if (id === "retry-balanced") root.retryWithPreset("Balanced");
            else if (id === "retry-deep") root.retryWithPreset("Deep");
            else if (id === "branch") root.branched();
            else if (id === "changes" && root.dock) root.dock.openTab("changes");
            else if (id === "undo-run" && bridge) bridge.undoLastRun();
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        propagateComposedEvents: true
        cursorShape: Qt.ArrowCursor
        onClicked: function(mouse) {
            responseMenu.anchorX = mouse.x;
            responseMenu.open();
        }
    }

    Component {
        id: proseBlock
        Markdown {
            property string blockText: ""
            property string blockLanguage: ""
            property string blockLabel: ""
            property bool blockStreaming: false
            property bool blockRunnable: false
            source: blockText
            streaming: blockStreaming
            onLinkClicked: function(link) { root.linkClicked(link); }
        }
    }

    Component {
        id: codeBlock
        CodeBlock {
            property string blockText: ""
            property string blockLanguage: ""
            property string blockLabel: "Text"
            property bool blockStreaming: false
            property bool blockRunnable: false
            code: blockText
            language: blockLanguage
            label: blockLabel
            streaming: blockStreaming
            runnable: blockRunnable
        }
    }
}
