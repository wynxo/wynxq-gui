import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* Usage settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    spacing: Theme.s6
    SettingsGroup {
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
                readonly property var bucketData: hostSheet.usageBucket(modelData.key)
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
                            text: hostSheet.formatUsageCount(bucketData.tokens || 0) + " tokens"
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
                            text: hostSheet.formatUsageCount(bucketData.promptTokens || 0) + " input · "
                                  + hostSheet.formatUsageCount(bucketData.outputTokens || 0) + " output"
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

    SettingsGroup {
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
                                   / hostSheet.maxUsage(bridge ? bridge.tokenUsageDays : [])))
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
                        text: hostSheet.formatUsageCount(modelData.tokens || 0)
                        color: Theme.textSecondary
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.micro
                    }
                }
            }
        }
    }

    SettingsGroup {
        title: "Models · last 30 days"
        description: "Which local models handled the work, ranked by exact input + output tokens."
        visible: bridge && bridge.tokenUsageModels && bridge.tokenUsageModels.length > 0
        readonly property real maximum: hostSheet.maxUsage(bridge ? bridge.tokenUsageModels : [])

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
                        text: hostSheet.formatUsageCount(modelData.tokens || 0)
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

    SettingsGroup {
        title: "Current chat"
        description: "Completed runs recorded for the conversation that is open now. A run is added only after Ollama reports exact token metrics."
        RowLayout {
            width: parent.width
            Text {
                text: bridge ? hostSheet.formatUsageCount(bridge.conversationTokens) + " tokens" : "0 tokens"
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
