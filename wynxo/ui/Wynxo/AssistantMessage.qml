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
    signal linkClicked(string link)
    signal branched()

    implicitHeight: column.implicitHeight
    property bool thoughtOpen: false
    function resetTransientState() { thoughtOpen = false; }
    Accessible.role: Accessible.StaticText
    Accessible.name: (root.streaming ? "Agent is replying: " : "Agent said: ") + root.body

    Column {
        id: column
        width: parent.width
        spacing: Theme.s3

        Row {
            visible: root.streaming
            height: visible ? 16 : 0
            spacing: Theme.s2
            StatusDot {
                width: 6; height: 6
                tone: Theme.accent
                pulsing: true
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: bridge && bridge.taskMode === "work" ? "Agent is working" : "Wynxo is replying"
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

        FocusScope {
            id: actions
            objectName: "responseActions"
            width: parent.width
            height: 26
            visible: !root.streaming && root.body.length > 0
            opacity: hover.hovered || activeFocus ? 1 : root.latest ? 0.86 : 0
            Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
            RowLayout {
                anchors.fill: parent
                spacing: 0
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
