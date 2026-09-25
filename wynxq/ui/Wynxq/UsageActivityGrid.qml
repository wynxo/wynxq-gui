import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Column {
    id: root
    objectName: "usageActivityGrid"
    property var days: []
    property int mode: 0
    readonly property int leading: days.length ? (new Date(days[0].date + "T00:00:00").getDay() + 6) % 7 : 0
    readonly property int columns: Math.max(1, Math.ceil((leading + days.length) / 7))
    readonly property real cellSize: Math.max(2, (width - (columns - 1) * 3) / columns)
    readonly property var values: {
        var output = [], sum = 0, weeks = {}
        for (var i = 0; i < days.length; i++) {
            var week = Math.floor((leading + i) / 7)
            weeks[week] = (weeks[week] || 0) + Number(days[i].tokens || 0)
        }
        for (var j = 0; j < days.length; j++) {
            sum += Number(days[j].tokens || 0)
            output.push(mode === 2 ? sum : mode === 1 ? weeks[Math.floor((leading + j) / 7)] : Number(days[j].tokens || 0))
        }
        return output
    }
    readonly property real maximum: Math.max.apply(null, [1].concat(values))
    spacing: 12
    RowLayout {
        width: parent.width
        Text { Layout.fillWidth: true; text: "Token activity"; color: Theme.textPrimary; font.family: Theme.sansFamily; font.pixelSize: Theme.heading; font.weight: Font.DemiBold }
        Repeater {
            model: ["Daily", "Weekly", "Cumulative"]
            delegate: Button {
                required property string modelData
                required property int index
                objectName: "usageActivityMode" + index
                text: modelData
                implicitHeight: 28
                implicitWidth: contentItem.implicitWidth + 18
                onClicked: root.mode = index
                Accessible.name: modelData + " token activity"
                background: Rectangle { radius: Theme.r1; color: root.mode === index ? Theme.surfaceHover : "transparent"; border.width: parent.activeFocus ? 1 : 0; border.color: Theme.accent }
                contentItem: Text { text: parent.text; color: root.mode === index ? Theme.textPrimary : Theme.textMuted; font.family: Theme.sansFamily; font.pixelSize: Theme.caption; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
            }
        }
    }
    Grid {
        rows: 7
        flow: Grid.TopToBottom
        spacing: 3
        Repeater {
            model: root.columns * 7
            delegate: Rectangle {
                required property int index
                readonly property int dayIndex: index - root.leading
                readonly property bool valid: dayIndex >= 0 && dayIndex < root.days.length
                readonly property real tokens: valid ? root.values[dayIndex] : 0
                width: root.cellSize
                height: root.cellSize
                radius: 2
                color: !valid ? "transparent" : tokens > 0 ? Theme.alpha(Theme.success, 0.22 + 0.78 * Math.sqrt(tokens / root.maximum)) : Theme.surfaceHover
                border.width: valid ? 1 : 0
                border.color: hover.hovered ? Theme.textSecondary : Theme.borderSubtle
                HoverHandler { id: hover }
                ToolTip.visible: valid && hover.hovered
                ToolTip.delay: 150
                ToolTip.text: valid ? root.days[dayIndex].date + " · " + Number(tokens).toLocaleString(Qt.locale(), 'f', 0) + " tokens" + (root.mode === 1 ? " this week" : root.mode === 2 ? " in displayed period to date" : "") : ""
            }
        }
    }
    Item {
        width: parent.width
        height: 16
        Repeater {
            model: root.columns
            delegate: Text {
                required property int index
                readonly property int dayIndex: Math.max(0, index * 7 - root.leading)
                readonly property string date: dayIndex < root.days.length ? root.days[dayIndex].date : ""
                readonly property bool newMonth: index === 0 || (dayIndex >= 7 && date.slice(5, 7) !== root.days[dayIndex - 7].date.slice(5, 7))
                visible: newMonth && index < root.columns - 2
                x: index * (root.cellSize + 3)
                text: date ? Qt.formatDate(new Date(date + "T00:00:00"), "MMM") : ""
                color: Theme.textMuted
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
            }
        }
    }
    RowLayout {
        width: parent.width
        Text { Layout.fillWidth: true; text: root.days.length ? root.days[0].date + " — " + root.days[root.days.length - 1].date : "No recorded activity yet"; color: Theme.textDisabled; font.family: Theme.sansFamily; font.pixelSize: Theme.micro }
        Text { text: "Less"; color: Theme.textMuted; font.pixelSize: Theme.micro }
        Repeater { model: [0, .25, .5, .75, 1]; delegate: Rectangle { required property real modelData; width: 9; height: 9; radius: 2; color: modelData ? Theme.alpha(Theme.success, modelData) : Theme.surfaceHover } }
        Text { text: "More"; color: Theme.textMuted; font.pixelSize: Theme.micro }
    }
}
