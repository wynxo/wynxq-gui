import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    One agent-authored plan step.

    Plan statuses are intentionally mapped onto the same visual vocabulary as
    Activity so completed/running/failed always mean the same thing, while the
    content itself remains a concise task plan rather than a tool log.
*/
Item {
    id: root
    required property var step
    property int number: 1
    property bool last: false

    readonly property string rawState: String(step && step.status || "pending")
    readonly property string stateKey: rawState === "completed" ? "done"
                                      : rawState === "in_progress" ? "running"
                                      : rawState === "skipped" ? "cancelled"
                                      : rawState === "pending" ? "queued"
                                      : rawState
    readonly property bool active: stateKey === "running"
    readonly property bool done: stateKey === "done"
    readonly property bool failed: stateKey === "failed"
    readonly property bool skipped: stateKey === "cancelled"
    readonly property color tone: Theme.stateColor(stateKey)
    readonly property string titleText: String(step && step.title || "Plan step")
    readonly property string stateText: done ? "Completed"
                                           : active ? "Running"
                                           : failed ? "Failed"
                                           : skipped ? "Skipped"
                                           : "Pending"

    implicitHeight: content.implicitHeight + Theme.s4

    Accessible.role: Accessible.ListItem
    Accessible.name: titleText + ", " + stateText

    Rectangle {
        x: 20
        y: 27
        width: 1
        height: Math.max(0, root.height - 17)
        visible: !root.last
        color: Theme.borderSubtle
    }

    Item {
        x: Theme.s3
        y: Theme.s2
        width: 18
        height: 18

        Rectangle {
            anchors.centerIn: parent
            width: 18; height: 18; radius: 9
            color: root.done ? Theme.surfaceSelected : "transparent"
            border.width: root.done ? 0 : 1
            border.color: root.active ? root.tone : Theme.borderStrong
        }

        Icon {
            anchors.centerIn: parent
            visible: root.done || root.failed || root.skipped
            name: root.done ? "check" : root.failed ? "warning" : "close"
            ink: root.done ? Theme.textPrimary : root.tone
            width: 10; height: 10
            weight: 1.9
        }

        StatusDot {
            anchors.centerIn: parent
            visible: root.active
            width: 7; height: 7
            tone: root.tone
            pulsing: true
        }

        Text {
            anchors.centerIn: parent
            visible: !root.done && !root.active && !root.failed && !root.skipped
            text: root.number
            color: Theme.textDisabled
            font.family: Theme.monoFamily
            font.pixelSize: Theme.micro
            font.weight: Font.Medium
        }
    }

    ColumnLayout {
        id: content
        x: 45
        y: Theme.s2
        width: parent.width - x - Theme.s3
        spacing: 3

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2

            Text {
                Layout.fillWidth: true
                text: root.titleText
                color: root.done ? Theme.textSecondary : Theme.textPrimary
                font.family: Theme.sansFamily
                font.pixelSize: Theme.body
                font.weight: root.active ? Font.Medium : Font.Normal
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                elide: Text.ElideRight
                lineHeight: 1.25
            }

            Text {
                text: root.stateText
                color: root.done ? Theme.textDisabled : root.tone
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
                font.weight: root.active || root.failed ? Font.Medium : Font.Normal
                Layout.alignment: Qt.AlignTop
            }
        }
    }
}
