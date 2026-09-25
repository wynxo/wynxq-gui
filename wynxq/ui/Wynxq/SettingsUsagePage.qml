import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    required property var bridge
    required property var hostSheet
    readonly property var overview: bridge ? bridge.tokenUsageOverview : ({})
    readonly property var lifetime: hostSheet.usageBucket("allTime")
    spacing: 20

    function count(value) { return hostSheet.formatUsageCount(value || 0) }
    function streak(value) { return (value || 0) + (value === 1 ? " day" : " days") }
    function duration(ms) {
        var minutes = Math.floor(Number(ms || 0) / 60000)
        if (ms > 0 && minutes === 0) return "<1m"
        return minutes >= 60 ? Math.floor(minutes / 60) + "h " + minutes % 60 + "m" : minutes + "m"
    }

    Column {
        width: parent.width
        spacing: 6
        Text { text: "Your activity"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: 26; font.weight: Font.DemiBold }
        Text { text: "A year of conversations, one day at a time."; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.body }
    }

    Rectangle {
        width: parent.width
        height: 80
        radius: Theme.r2
        color: Theme.surfaceSunken
        border.color: Theme.borderSubtle
        Row {
            anchors.fill: parent
            anchors.margins: 12
            Repeater {
                model: [
                    {label: "Lifetime tokens", value: root.count(root.lifetime.tokens)},
                    {label: "Peak day", value: root.count(root.overview.peakDayTokens)},
                    {label: "Longest generation¹", value: root.duration(root.overview.longestGenerationMs)},
                    {label: "Current streak", value: root.streak(root.overview.currentStreak)},
                    {label: "Longest streak", value: root.streak(root.overview.longestStreak)}
                ]
                delegate: Item {
                    required property var modelData
                    required property int index
                    width: parent.width / 5
                    height: parent.height
                    Rectangle { visible: index > 0; width: 1; height: 30; anchors.verticalCenter: parent.verticalCenter; color: Theme.borderSubtle }
                    Column {
                        anchors.centerIn: parent
                        spacing: 7
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.value; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: 19; font.weight: Font.DemiBold }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: modelData.label; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: 10 }
                    }
                }
            }
        }
    }

    UsageActivityGrid { width: parent.width; days: root.overview.year || [] }

    Rectangle { width: parent.width; height: 1; color: Theme.borderSubtle }

    RowLayout {
        width: parent.width
        spacing: 36
        Column {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 13
            Text { text: "Activity insights"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
            Repeater {
                model: [
                    {label: "Active days", value: root.count(root.overview.activeDays)},
                    {label: "Recorded chats", value: root.count(root.overview.totalChats)},
                    {label: "Completed runs", value: root.count(root.lifetime.runs)},
                    {label: "Input tokens", value: root.count(root.lifetime.promptTokens)},
                    {label: "Output tokens", value: root.count(root.lifetime.outputTokens)},
                    {label: "Average generation", value: Number(root.lifetime.averageRate || 0).toFixed(1) + " tok/s"}
                ]
                delegate: RowLayout {
                    required property var modelData
                    width: parent.width
                    Text { Layout.fillWidth: true; text: modelData.label; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
                    Text { text: modelData.value; color: Theme.textPrimary; font.family: Theme.monoFamily; font.pixelSize: Theme.caption }
                }
            }
        }
        Column {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 13
            Text { text: "Most used models"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
            Text { text: "Last 30 days · ranked by tokens"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
            Repeater {
                model: root.bridge ? root.bridge.tokenUsageModels : []
                delegate: RowLayout {
                    required property var modelData
                    width: parent.width
                    spacing: 10
                    Rectangle { width: 7; height: 7; radius: 3.5; color: Theme.accent }
                    Text { Layout.fillWidth: true; text: modelData.name; elide: Text.ElideMiddle; color: Theme.textSecondary; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
                    Text { text: modelData.runs + " runs"; color: Theme.textMuted; font.family: Theme.monoFamily; font.pixelSize: Theme.micro }
                    ToolTip.text: root.count(modelData.tokens) + " tokens"
                    ToolTip.visible: modelHover.hovered
                    HoverHandler { id: modelHover }
                }
            }
            Text { visible: !root.bridge || !root.bridge.tokenUsageModels.length; text: "Your models will appear after a completed run."; width: parent.width; wrapMode: Text.WordWrap; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
        }
    }
    Column {
        width: parent.width
        spacing: 12
        Button {
            id: details
            text: checked ? "Hide period details" : "Show period details"
            checkable: true
            flat: true
            implicitHeight: 28
            implicitWidth: contentItem.implicitWidth + 16
            background: Rectangle { radius: Theme.r1; color: details.hovered ? Theme.surfaceHover : "transparent"; border.width: details.activeFocus ? 1 : 0; border.color: Theme.accent }
            contentItem: Text { text: details.text; color: Theme.textSecondary; font.family: Theme.sansFamily; font.pixelSize: Theme.caption; verticalAlignment: Text.AlignVCenter }
        }
        Column {
            width: parent.width
            visible: details.checked
            spacing: 12
            Repeater {
                model: [{key: "today", label: "TODAY"}, {key: "week", label: "THIS WEEK"},
                        {key: "month", label: "THIS MONTH"}, {key: "allTime", label: "ALL TIME"}]
                delegate: RowLayout {
                    required property var modelData
                    readonly property var bucket: root.hostSheet.usageBucket(modelData.key)
                    width: parent.width
                    Text { Layout.fillWidth: true; text: modelData.label; color: Theme.textMuted; font.pixelSize: Theme.micro }
                    Text { text: root.count(bucket.promptTokens) + " input · " + root.count(bucket.outputTokens) + " output · " + root.count(bucket.tokens) + " total"; color: Theme.textSecondary; font.pixelSize: Theme.caption }
                }
            }
            Text { text: "Current chat · " + root.count(root.bridge ? root.bridge.conversationTokens : 0) + " tokens"; color: Theme.textSecondary; font.pixelSize: Theme.caption }
        }
    }
    Text {
        width: parent.width
        text: "Exact recorded input + output tokens; cached input is already part of input and is never counted twice.\n¹ Longest total model generation time in one chat, excluding time between messages."
        color: Theme.textDisabled
        font.family: Theme.sansFamily
        font.pixelSize: Theme.micro
        wrapMode: Text.WordWrap
        lineHeight: 1.5
    }
}
