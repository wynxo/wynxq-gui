import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "usageOverview"
    required property var bridge
    required property var hostSheet
    property string period: "today"
    readonly property var overview: bridge ? bridge.tokenUsageOverview : ({})
    readonly property var selected: hostSheet.usageBucket(period)
    readonly property var periods: [
        {key: "today", label: "Today usage", detail: "Since midnight"},
        {key: "week", label: "Weekly", detail: "This week · Monday to today"},
        {key: "month", label: "Monthly", detail: "This calendar month"},
        {key: "year", label: "Yearly", detail: "This calendar year"},
        {key: "allTime", label: "All time", detail: "All recorded usage"}
    ]
    spacing: 24
    function count(value) { return hostSheet.formatUsageCount(value || 0) }

    Column {
        width: parent.width
        spacing: 8
        Text { text: "Usage"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: 28; font.weight: Font.DemiBold }
        Text { text: "Your conversations, at a glance."; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.body }
    }

    Row {
        width: parent.width
        spacing: 8
        Repeater {
            model: root.periods
            delegate: AbstractButton {
                id: periodButton
                required property var modelData
                readonly property bool chosen: root.period === modelData.key
                readonly property var bucket: root.hostSheet.usageBucket(modelData.key)
                objectName: "usagePeriod_" + modelData.key
                width: (parent.width - 32) / 5
                height: 94
                hoverEnabled: true
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.label + ": " + root.count(bucket.tokens) + " tokens"
                Accessible.checked: chosen
                onClicked: root.period = modelData.key
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: modelData.detail
                background: Rectangle {
                    radius: Theme.r2
                    color: periodButton.chosen ? Theme.surfaceRaised : periodButton.hovered ? Theme.surface : "transparent"
                    border.width: 1
                    border.color: periodButton.visualFocus ? Theme.accent : periodButton.chosen ? Theme.borderStrong : Theme.borderSubtle
                }
                contentItem: Column {
                    leftPadding: 14
                    topPadding: 14
                    spacing: 8
                    Text { text: modelData.label; color: periodButton.chosen ? Theme.textPrimary : Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
                    Text { text: root.count(periodButton.bucket.tokens); color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: 23; font.weight: Font.DemiBold }
                    Text { text: "tokens"; color: Theme.textDisabled; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
                }
            }
        }
    }

    RowLayout {
        width: parent.width
        spacing: 16
        Repeater {
            model: [
                {label: "Input", value: root.count(root.selected.promptTokens)},
                {label: "Output", value: root.count(root.selected.outputTokens)},
                {label: "Runs", value: root.count(root.selected.runs)}
            ]
            delegate: Row {
                required property var modelData
                spacing: 7
                Text { text: modelData.label; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
                Text { text: modelData.value; color: Theme.textSecondary; font.family: Theme.monoFamily; font.pixelSize: Theme.caption }
            }
        }
        Item { Layout.fillWidth: true }
        Text { text: Number(root.selected.averageRate || 0).toFixed(1) + " tok/s"; color: Theme.textMuted; font.family: Theme.monoFamily; font.pixelSize: Theme.caption }
    }

    Rectangle { width: parent.width; height: 1; color: Theme.borderSubtle }
    UsageActivityGrid { width: parent.width; days: root.overview.year || [] }
    RowLayout {
        width: parent.width
        Text { text: (root.overview.activeDays || 0) + " active days · all time"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
        Item { Layout.fillWidth: true }
        Rectangle { width: 6; height: 6; radius: 3; color: Theme.success }
        Text { text: (root.overview.currentStreak || 0) + " day streak"; color: Theme.textSecondary; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
    }
    Rectangle { width: parent.width; height: 1; color: Theme.borderSubtle }

    Column {
        width: parent.width
        spacing: 14
        RowLayout {
            width: parent.width
            Text { Layout.fillWidth: true; text: "Your models"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
            Text { text: "Last 30 days"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
        }
        Repeater {
            model: root.bridge ? root.bridge.tokenUsageModels : []
            delegate: RowLayout {
                required property var modelData
                width: parent.width
                spacing: 12
                Rectangle { width: 7; height: 7; radius: 3.5; color: Theme.success }
                Text { Layout.fillWidth: true; text: modelData.name; elide: Text.ElideMiddle; color: Theme.textSecondary; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
                Text { text: root.count(modelData.tokens) + " tokens"; color: Theme.textSecondary; font.family: Theme.monoFamily; font.pixelSize: Theme.caption }
                Text { Layout.preferredWidth: 65; horizontalAlignment: Text.AlignRight; text: modelData.runs + " runs"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
            }
        }
        Text { visible: !root.bridge || !root.bridge.tokenUsageModels.length; text: "Complete a conversation to see your models here."; width: parent.width; wrapMode: Text.WordWrap; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
    }
    Text {
        width: parent.width
        text: "Recorded locally · Input + output tokens · Current chat: " + root.count(root.bridge ? root.bridge.conversationTokens : 0)
        color: Theme.textDisabled
        font.family: Theme.sansFamily
        font.pixelSize: Theme.micro
        wrapMode: Text.WordWrap
        ToolTip.visible: accountingHover.hovered
        ToolTip.text: "Cached input is already part of input and is never counted twice."
        HoverHandler { id: accountingHover }
    }
}
