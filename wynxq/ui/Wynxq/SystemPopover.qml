import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Machine state, stated plainly.

    Every figure here is measured — `/proc` for memory, Ollama's own `/api/ps`
    for what is resident and whether it is on the GPU. A row whose value this
    machine cannot answer is not shown at all. Nothing is estimated, and
    nothing is drawn as a gauge to look impressive: a status surface that
    invents a number is worse than one that admits it does not know.
*/
Popover {
    id: root
    width: 262
    preferredEdge: "below"

    readonly property var state: bridge ? bridge.systemState : ({})

    // The popover reads live values, so it refreshes only while it is open.
    Timer {
        running: root.opened
        interval: 2000
        repeat: true
        onTriggered: root.stateRefresh()
    }
    property int tick: 0
    function stateRefresh() { tick++; }

    height: column.implicitHeight + padding * 2

    ColumnLayout {
        id: column
        width: parent.width
        spacing: Theme.s3

        // --------------------------------------------------------- Ollama
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            StatusDot {
                width: 7; height: 7
                tone: root.state.online ? Theme.success
                    : root.state.connectionState === "connecting" ? Theme.warning : Theme.danger
                pulsing: root.state.connectionState === "connecting"
            }
            Text {
                text: "Ollama"
                color: Theme.textPrimary
                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                font.weight: Font.Medium
            }
            Item { Layout.fillWidth: true }
            Text {
                text: root.state.online ? "Online"
                    : root.state.connectionState === "connecting" ? "Connecting" : "Offline"
                color: root.state.online ? Theme.success : Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.topMargin: -Theme.s2
            text: root.state.endpoint || ""
            color: Theme.textDisabled
            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
            elide: Text.ElideMiddle
        }

        Divider { Layout.fillWidth: true }

        // ---------------------------------------------------- the readings
        Column {
            Layout.fillWidth: true
            spacing: Theme.s2

            component Reading: RowLayout {
                property string label: ""
                property string value: ""
                property color ink: Theme.textSecondary
                width: column.width
                spacing: Theme.s3
                Text {
                    text: parent.label
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Item { Layout.fillWidth: true; Layout.minimumWidth: Theme.s2 }
                Text {
                    text: parent.value
                    color: parent.ink
                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                    elide: Text.ElideMiddle
                    Layout.maximumWidth: column.width * 0.62
                    horizontalAlignment: Text.AlignRight
                }
            }

            Reading { label: "Model"; value: root.state.model || "—"; ink: Theme.textPrimary }
            Reading {
                label: "Agent"
                value: root.state.agentState || "Idle"
                ink: root.state.busy ? Theme.accent : Theme.textSecondary
            }
            Reading {
                visible: !!root.state.project
                label: "Workspace"
                value: root.state.project || ""
            }
            Reading {
                visible: (root.state.contextUsed || 0) > 0
                label: "Context"
                value: root.state.contextLabel || ""
            }
        }

        // A meter only where there is a real denominator to measure against.
        Meter {
            Layout.fillWidth: true
            Layout.topMargin: -Theme.s1
            visible: (root.state.contextUsed || 0) > 0
            value: root.state.contextTotal ? root.state.contextUsed / root.state.contextTotal : 0
        }

        Divider { Layout.fillWidth: true; visible: memory.visible || gpu.visible || resident.visible }

        Column {
            id: memory
            Layout.fillWidth: true
            spacing: Theme.s2
            visible: !!root.state.hasMemory || !!root.state.hasProcessMemory

            RowLayout {
                width: memory.width
                visible: !!root.state.hasMemory
                spacing: Theme.s3
                Text {
                    text: "Memory"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: (root.state.memoryUsed || "") + " / " + (root.state.memoryTotal || "")
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                }
            }
            Meter {
                width: memory.width
                visible: !!root.state.hasMemory
                value: root.state.memoryFraction || 0
                tone: Theme.info
            }
            RowLayout {
                width: memory.width
                visible: !!root.state.hasProcessMemory
                spacing: Theme.s3
                Text {
                    text: "Wynxq"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: root.state.processMemory || ""
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                }
            }
        }

        Column {
            id: gpu
            Layout.fillWidth: true
            spacing: Theme.s2
            visible: !!root.state.hasGpu

            RowLayout {
                width: gpu.width
                spacing: Theme.s3
                Text {
                    text: "VRAM"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: (root.state.gpuUsed || "") + " / " + (root.state.gpuTotal || "")
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                }
            }
            Meter { width: gpu.width; value: root.state.gpuFraction || 0; tone: Theme.info }
        }

        // ------------------------------------------------ what is resident
        Column {
            id: resident
            Layout.fillWidth: true
            spacing: Theme.s1
            visible: (root.state.resident || []).length > 0

            SectionLabel { text: "Loaded in memory" }

            Repeater {
                model: root.state.resident || []
                delegate: RowLayout {
                    required property var modelData
                    width: resident.width
                    spacing: Theme.s2
                    Text {
                        Layout.fillWidth: true
                        text: modelData.name
                        color: Theme.textSecondary
                        font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        elide: Text.ElideMiddle
                    }
                    Text {
                        visible: !!modelData.placement
                        text: modelData.placement
                        color: Theme.textDisabled
                        font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                    }
                    Text {
                        visible: !!modelData.sizeLabel
                        text: modelData.sizeLabel
                        color: Theme.textMuted
                        font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                    }
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.topMargin: Theme.s1
            visible: !root.state.hasMemory && !root.state.hasGpu
            text: "This system does not expose memory readings to Wynxq."
            color: Theme.textDisabled
            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
            wrapMode: Text.WordWrap
        }
    }
}
