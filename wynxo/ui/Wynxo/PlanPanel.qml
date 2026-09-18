import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The agent's concise, persisted plan for the current task.

    These rows are authored through the agent's update_plan tool. They are not
    inferred from prompt text and they are not the raw Activity audit trail.
*/
Item {
    id: root
    readonly property var rows: bridge ? bridge.planSteps : []

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Plan"
            detail: bridge ? bridge.planSummary : ""

            StatusDot {
                visible: bridge && bridge.busy && root.rows.length > 0
                width: 8; height: 8
                tone: Theme.accent
                pulsing: true
            }
        }

        ListView {
            id: list
            objectName: "planRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.rows.length > 0
            model: root.rows
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            topMargin: Theme.s2
            bottomMargin: Theme.s4
            cacheBuffer: 400

            ScrollBar.vertical: WScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: PlanTaskRow {
                required property var modelData
                required property int index
                width: list.width
                step: modelData
                number: index + 1
                last: index === root.rows.length - 1
            }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.rows.length === 0
            iconName: "clipboard"
            title: "No plan yet"
            detail: "For multi-step work, Wynxo will publish a short plan here and keep each step up to date as it works."
        }
    }
}
