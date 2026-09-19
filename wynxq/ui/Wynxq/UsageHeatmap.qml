import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    readonly property var days: bridge ? bridge.tokenUsageDays : []
    readonly property int maxTokens: {
        var maximum = 0
        for (var i = 0; i < days.length; i++)
            maximum = Math.max(maximum, Number(days[i].tokens || 0))
        return maximum
    }
    readonly property int totalTokens: {
        var total = 0
        for (var i = 0; i < days.length; i++)
            total += Number(days[i].tokens || 0)
        return total
    }

    function formatTokens(value) {
        value = Math.max(0, Number(value || 0))
        if (value >= 1000000) return (value / 1000000).toFixed(value >= 10000000 ? 1 : 2) + "M"
        if (value >= 1000) return (value / 1000).toFixed(value >= 10000 ? 1 : 2) + "K"
        return String(Math.round(value))
    }

    implicitHeight: content.implicitHeight
    visible: days.length > 0

    ColumnLayout {
        id: content
        width: parent.width
        spacing: Theme.s2

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "30-day usage"
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
            }
            Item { Layout.fillWidth: true }
            Text {
                text: root.formatTokens(root.totalTokens) + " tokens"
                color: Theme.textDisabled
                font.family: Theme.monoFamily
                font.pixelSize: Theme.micro
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 4

            Repeater {
                model: root.days
                delegate: Rectangle {
                    id: cell
                    required property var modelData
                    readonly property real strength: root.maxTokens > 0
                        ? Math.sqrt(Number(modelData.tokens || 0) / root.maxTokens) : 0

                    width: 10
                    height: 10
                    radius: 2
                    color: Number(modelData.tokens || 0) > 0
                        ? Theme.alpha(Theme.success, 0.24 + strength * 0.70)
                        : Theme.surfaceHover
                    border.width: 1
                    border.color: Number(modelData.tokens || 0) > 0
                        ? Theme.alpha(Theme.success, 0.22) : Theme.borderSubtle

                    HoverHandler { id: hover }
                    ToolTip.visible: hover.hovered
                    ToolTip.delay: 250
                    ToolTip.text: modelData.date + " · "
                        + root.formatTokens(modelData.tokens) + " tokens"
                        + (modelData.runs ? " · " + modelData.runs + " run"
                            + (modelData.runs === 1 ? "" : "s") : "")
                }
            }
        }
    }
}
