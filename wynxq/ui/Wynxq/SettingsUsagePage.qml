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
    spacing: 18
    function count(value) { return hostSheet.formatUsageCount(value || 0) }

    RowLayout {
        width: parent.width
        spacing: Theme.s3
        Column {
            Layout.fillWidth: true
            spacing: 4
            Text { text: "Usage"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: 22; font.weight: Font.DemiBold }
            Text { text: "Local token activity and model usage."; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
        }
        Text { text: root.periods.find(function(item) { return item.key === root.period; }).detail; color: Theme.textDisabled; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
    }

    Rectangle {
        width: parent.width
        height: 40
        radius: Theme.r2
        color: Theme.surfaceSunken
        border.width: 1
        border.color: Theme.borderSubtle

        Row {
            anchors.fill: parent
            anchors.margins: 3
            spacing: 2

            Repeater {
                model: root.periods
                delegate: AbstractButton {
                    id: periodButton
                    required property var modelData
                    readonly property bool chosen: root.period === modelData.key
                    readonly property var bucket: root.hostSheet.usageBucket(modelData.key)
                    objectName: "usagePeriod_" + modelData.key
                    width: (parent.width - 8) / 5
                    height: parent.height
                    hoverEnabled: true
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: modelData.label + ": " + root.count(bucket.tokens) + " tokens"
                    Accessible.checked: chosen
                    onClicked: root.period = modelData.key
                    ToolTip.visible: hovered
                    ToolTip.delay: Theme.tooltipDelay
                    ToolTip.text: modelData.detail

                    background: Rectangle {
                        radius: Theme.r1
                        color: periodButton.chosen ? Theme.surfaceRaised
                             : periodButton.down ? Theme.surfacePressed
                             : periodButton.hovered ? Theme.surfaceHover : "transparent"
                        border.width: periodButton.visualFocus ? 1 : 0
                        border.color: Theme.accentEdge
                    }
                    contentItem: Text {
                        text: modelData.label
                        color: periodButton.chosen ? Theme.textPrimary : Theme.textMuted
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.caption
                        font.weight: periodButton.chosen ? Font.DemiBold : Font.Normal
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    Column {
        width: parent.width
        spacing: 10

        RowLayout {
            width: parent.width
            spacing: Theme.s2
            Text { text: root.count(root.selected.tokens); color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: 34; font.weight: Font.DemiBold }
            Text { text: "tokens"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption; Layout.alignment: Qt.AlignBottom; Layout.bottomMargin: 6 }
            Item { Layout.fillWidth: true }
            Rectangle { width: 6; height: 6; radius: 3; color: Theme.success }
            Text { text: (root.overview.currentStreak || 0) + " day streak"; color: Theme.textSecondary; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
        }

        RowLayout {
            width: parent.width
            spacing: Theme.s5
            Repeater {
                model: [
                    {label: "Input", value: root.count(root.selected.promptTokens)},
                    {label: "Output", value: root.count(root.selected.outputTokens)},
                    {label: "Runs", value: root.count(root.selected.runs)},
                    {label: "Speed", value: Number(root.selected.averageRate || 0).toFixed(1) + " tok/s"}
                ]
                delegate: Column {
                    required property var modelData
                    spacing: 3
                    Text { text: modelData.label; color: Theme.textDisabled; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
                    Text { text: modelData.value; color: Theme.textSecondary; font.family: Theme.monoFamily; font.pixelSize: Theme.caption }
                }
            }
            Item { Layout.fillWidth: true }
        }
    }

    Rectangle { width: parent.width; height: 1; color: Theme.borderSubtle }

    UsageActivityGrid {
        width: parent.width
        days: root.overview.year || []
    }

    RowLayout {
        width: parent.width
        Text { text: (root.overview.activeDays || 0) + " active days · all time"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption }
        Item { Layout.fillWidth: true }
        Text { text: "Stored on this device"; color: Theme.textDisabled; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
    }

    Rectangle { width: parent.width; height: 1; color: Theme.borderSubtle }

    Column {
        width: parent.width
        spacing: 8

        RowLayout {
            width: parent.width
            Text { Layout.fillWidth: true; text: "Models"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
            Text { text: "Last 30 days"; color: Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
        }

        Repeater {
            model: root.bridge ? root.bridge.tokenUsageModels : []
            delegate: Column {
                required property var modelData
                width: parent.width
                spacing: 7

                RowLayout {
                    width: parent.width
                    height: 28
                    spacing: Theme.s2
                    Rectangle { width: 6; height: 6; radius: 3; color: Theme.success }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.name
                        elide: Text.ElideMiddle
                        color: Theme.textSecondary
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.caption
                    }
                    Text {
                        text: root.count(modelData.tokens)
                        color: Theme.textSecondary
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.caption
                    }
                    Text {
                        Layout.preferredWidth: 58
                        horizontalAlignment: Text.AlignRight
                        text: modelData.runs + " runs"
                        color: Theme.textDisabled
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.micro
                    }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.borderSubtle }
            }
        }

        Text {
            visible: !root.bridge || !root.bridge.tokenUsageModels.length
            text: "Complete a conversation to see model usage here."
            width: parent.width
            wrapMode: Text.WordWrap
            color: Theme.textMuted
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
        }
    }

    Text {
        width: parent.width
        text: "Input + output tokens · Current chat: " + root.count(root.bridge ? root.bridge.conversationTokens : 0)
        color: Theme.textDisabled
        font.family: Theme.sansFamily
        font.pixelSize: Theme.micro
        wrapMode: Text.WordWrap
        ToolTip.visible: accountingHover.hovered
        ToolTip.text: "Cached input is already part of input and is never counted twice."
        HoverHandler { id: accountingHover }
    }
}
