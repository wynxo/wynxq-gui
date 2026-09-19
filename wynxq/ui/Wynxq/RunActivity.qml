import QtQuick
import QtQuick.Controls

/*!
    What Wynxq actually did, inline with the task that asked for it.

    One row per action on a single rail: what it was, whether it worked, how
    long it took. Output is one line unless you ask for more, and the run ends
    with a line you can read in a second. No box, no dashboard — a run is part
    of the conversation, not a widget beside it.
*/
Item {
    id: root
    property var steps: []
    property bool live: false
    property bool detailsVisible: false

    implicitHeight: column.implicitHeight
    Accessible.role: Accessible.List
    Accessible.name: {
        var parts = [];
        for (var i = 0; i < steps.length; i++)
            parts.push((steps[i].summary || steps[i].label) + ", " + steps[i].state);
        return "Activity: " + parts.join("; ");
    }

    readonly property int failures: {
        var count = 0;
        for (var i = 0; i < steps.length; i++)
            if (steps[i].state === "failed" || steps[i].state === "declined") count++;
        return count;
    }
    readonly property bool settled: {
        for (var i = 0; i < steps.length; i++)
            if (steps[i].state === "running" || steps[i].state === "waiting") return false;
        return !live;
    }
    readonly property real totalMs: {
        var total = 0;
        for (var i = 0; i < steps.length; i++) total += steps[i].ms || 0;
        return total;
    }

    readonly property bool collapsedSummary: settled && failures === 0
        && steps.length > 3 && !detailsVisible

    function duration(ms) {
        return ms >= 1000 ? (ms / 1000).toFixed(1) + "s" : Math.round(ms) + "ms";
    }

    Column {
        id: column
        width: parent.width
        spacing: 0

        Repeater {
            model: root.collapsedSummary ? [] : root.steps
            delegate: Item {
                id: step
                required property var modelData
                required property int index
                width: column.width
                height: stepColumn.implicitHeight + Theme.s2
                property bool expanded: false
                property color tone: Theme.stateColor(modelData.state)
                readonly property bool isCommand: modelData.name === "run_command"

                // The rail runs the full height of every row but the last, so
                // the steps read as one sequence rather than separate cards.
                Rectangle {
                    x: 4
                    y: 15
                    width: 1
                    height: step.height - 10
                    color: Theme.borderStrong
                    visible: step.index < root.steps.length - 1 || !root.settled
                }

                StatusDot {
                    x: 0; y: 8
                    width: 9; height: 9
                    tone: step.tone
                    pulsing: modelData.state === "running" || modelData.state === "waiting"
                }

                Column {
                    id: stepColumn
                    x: 22
                    width: parent.width - 22
                    spacing: 3
                    topPadding: Theme.s1

                    Row {
                        width: parent.width
                        spacing: Theme.s2
                        Icon {
                            name: modelData.icon || "bolt"
                            ink: modelData.state === "done" ? Theme.textMuted : step.tone
                            width: 13; height: 13
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            text: modelData.summary || modelData.label
                            color: Theme.textPrimary
                            font.family: step.isCommand ? Theme.monoFamily : Theme.sansFamily
                            font.pixelSize: step.isCommand ? Theme.code : Theme.label
                            width: Math.min(implicitWidth, stepColumn.width - 150)
                            elide: Text.ElideRight
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            visible: modelData.state === "waiting"
                            text: "waiting for you"
                            color: Theme.warning
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            visible: modelData.state === "declined"
                            text: "declined"
                            color: Theme.warning
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            visible: modelData.state === "failed"
                            text: "failed"
                            color: Theme.danger
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            visible: modelData.ms > 0
                            text: root.duration(modelData.ms)
                            color: Theme.textMuted
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    // A command's output is terminal output: monospaced, on
                    // the sunken surface, with the same ink the panel uses.
                    // Everything else is prose and stays prose.
                    Rectangle {
                        width: parent.width
                        visible: step.isCommand && !!modelData.output
                        height: visible ? commandOutput.implicitHeight + Theme.s2 * 2 : 0
                        radius: Theme.r1
                        color: Theme.surfaceSunken
                        Text {
                            id: commandOutput
                            anchors.fill: parent
                            anchors.margins: Theme.s2
                            text: modelData.output || ""
                            textFormat: Text.PlainText
                            color: modelData.state === "failed" ? Theme.danger : Theme.textSecondary
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                            wrapMode: Text.WrapAnywhere
                            maximumLineCount: step.expanded ? 24 : 3
                            elide: Text.ElideRight
                            lineHeight: 1.45
                        }
                    }

                    Text {
                        width: parent.width
                        visible: !step.isCommand && text !== ""
                        text: modelData.output || ""
                        textFormat: Text.PlainText
                        color: modelData.state === "failed" ? Theme.danger : Theme.textMuted
                        font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                        wrapMode: Text.WordWrap
                        maximumLineCount: step.expanded ? 20 : 1
                        elide: Text.ElideRight
                        lineHeight: 1.4
                    }

                    Text {
                        width: parent.width
                        visible: step.expanded && !!modelData.detail
                        text: modelData.detail || ""
                        textFormat: Text.PlainText
                        color: Theme.textMuted
                        font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        wrapMode: Text.WrapAnywhere
                        maximumLineCount: 8
                        elide: Text.ElideRight
                        bottomPadding: Theme.s1
                    }
                }

                MouseArea {
                    id: stepArea
                    anchors.fill: parent
                    anchors.rightMargin: 30
                    hoverEnabled: true
                    enabled: !!modelData.detail || !!modelData.output
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: step.expanded = !step.expanded
                    ToolTip.visible: containsMouse && enabled && !step.expanded
                    ToolTip.text: "Show details"
                    ToolTip.delay: 700
                }

                IconButton {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 2
                    width: 26; height: 26; iconSize: 12
                    visible: step.isCommand && !!bridge && !!bridge.workspaceDock
                    opacity: stepArea.containsMouse || hovered ? 1 : 0
                    iconName: "terminal"
                    tooltip: "Open the terminal here"
                    onClicked: if (bridge && bridge.workspaceDock) bridge.workspaceDock.openTab("terminal")
                    Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                }
            }
        }

        // ------------------------------------------------------- the result
        AbstractButton {
            id: summaryButton
            width: column.width
            height: root.settled && root.steps.length > 1 ? 26 : 0
            visible: height > 0
            hoverEnabled: root.steps.length > 3
            enabled: root.steps.length > 3
            Accessible.name: root.collapsedSummary ? "Show action details" : "Hide action details"
            onClicked: root.detailsVisible = !root.detailsVisible
            background: GlassSurface {
                radius: Theme.r1
                solid: false
                glassEnabled: summaryButton.hovered || summaryButton.visualFocus
                tint: Theme.glassTintHover
                fillOpacity: summaryButton.hovered ? 0.40 : 0.0
                outlineVisible: summaryButton.visualFocus
                active: summaryButton.visualFocus
            }

            Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.s2
                Icon {
                    name: root.failures ? "warning" : "check"
                    ink: root.failures ? Theme.warning : Theme.success
                    width: 11; height: 11
                    x: -1
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    leftPadding: 8
                    text: {
                        var actions = root.steps.length + (root.steps.length === 1 ? " action" : " actions");
                        var timing = root.totalMs >= 100 ? " · " + root.duration(root.totalMs) : "";
                        return root.failures
                               ? root.failures + " of " + actions + " did not run" + timing
                               : actions + timing;
                    }
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Icon {
                    visible: root.steps.length > 3
                    name: root.collapsedSummary ? "chevron" : "down"
                    ink: Theme.textDisabled
                    width: 10; height: 10
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }
}
