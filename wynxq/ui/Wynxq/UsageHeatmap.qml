import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Thirty days of local model activity, arranged like a compact contribution
    graph: seven weekday rows and week columns. It is data, not decoration;
    green intensity is proportional to token usage and every cell has a tooltip.
*/
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
                text: "30-day activity"
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

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Theme.s2

            Column {
                spacing: 3
                Repeater {
                    model: 7
                    delegate: Text {
                        required property int index
                        width: 20
                        height: 9
                        text: index === 1 ? "M" : index === 3 ? "W" : index === 5 ? "F" : ""
                        color: Theme.textDisabled
                        font.family: Theme.monoFamily
                        font.pixelSize: Math.max(8, Theme.micro - 1)
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            Grid {
                id: contributionGrid
                rows: 7
                flow: Grid.TopToBottom
                rowSpacing: 3
                columnSpacing: 3

                Repeater {
                    model: root.days
                    delegate: Rectangle {
                        id: cell
                        required property var modelData
                        required property int index
                        readonly property real strength: root.maxTokens > 0
                            ? Math.sqrt(Number(modelData.tokens || 0) / root.maxTokens) : 0

                        width: 9
                        height: 9
                        radius: 2
                        color: Number(modelData.tokens || 0) > 0
                            ? Theme.alpha(Theme.success, 0.20 + strength * 0.76)
                            : Theme.surfaceHover
                        border.width: 1
                        border.color: Number(modelData.tokens || 0) > 0
                            ? Theme.alpha(Theme.success, 0.24 + strength * 0.18)
                            : Theme.borderSubtle
                        opacity: 1

                        SequentialAnimation {
                            running: !Theme.reducedMotion
                            PauseAnimation { duration: cell.index * 14 }
                            NumberAnimation {
                                target: cell; property: "opacity"
                                from: 0; to: 1; duration: 130; easing.type: Theme.easing
                            }
                        }

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

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: 4
            Text {
                text: "Less"
                color: Theme.textDisabled
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
            }
            Repeater {
                model: [0.20, 0.40, 0.64, 0.92]
                delegate: Rectangle {
                    required property real modelData
                    width: 8; height: 8; radius: 2
                    color: Theme.alpha(Theme.success, modelData)
                    border.width: 1
                    border.color: Theme.alpha(Theme.success, Math.min(1, modelData + 0.10))
                }
            }
            Text {
                text: "More"
                color: Theme.textDisabled
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
            }
        }
    }
}
