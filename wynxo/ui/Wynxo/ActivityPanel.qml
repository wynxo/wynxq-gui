import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The full record of the session's runs.

    The conversation shows a compact line per action; this shows the whole
    timeline — every step, its state, how long it took, and what it returned
    when you open it. Turn headers group the runs so a long session stays
    readable.
*/
Item {
    id: root
    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property var rows: dock ? dock.activityRows : []

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Activity"
            detail: root.dock ? root.dock.activitySummary : ""

            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "trash"
                tooltip: "Clear the timeline"
                enabled: root.rows.length > 0
                onClicked: if (root.dock) root.dock.clearActivity()
            }
        }

        ListView {
            id: list
            objectName: "activityRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.rows.length > 0
            clip: true
            model: root.rows
            boundsBehavior: Flickable.StopAtBounds
            topMargin: Theme.s2
            bottomMargin: Theme.s4
            cacheBuffer: 600
            property bool following: true
            onMovementStarted: following = false
            onMovementEnded: following = atYEnd
            onCountChanged: if (following) Qt.callLater(positionViewAtEnd)

            ScrollBar.vertical: WScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: event
                required property var modelData
                required property int index
                width: list.width
                height: body.implicitHeight + Theme.s2
                property bool expanded: false
                readonly property bool isTurn: modelData.kind === "turn"
                readonly property color tone: Theme.stateColor(modelData.state)
                readonly property bool hasDetail: !!modelData.output || !!modelData.detail

                Accessible.role: Accessible.ListItem
                Accessible.name: (modelData.summary || modelData.label) + ", "
                                 + Theme.stateLabel(modelData.state)

                // ------------------------------------------------ turn header
                Rectangle {
                    anchors.fill: parent
                    anchors.topMargin: event.index === 0 ? 0 : Theme.s1
                    visible: event.isTurn
                    color: Theme.background
                }

                Column {
                    id: body
                    x: event.isTurn ? Theme.s3 : Theme.s4
                    width: parent.width - x - Theme.s3
                    spacing: 2
                    topPadding: Theme.s1

                    Row {
                        width: parent.width
                        spacing: Theme.s2

                        // The rail: one dot per step, one small mark per turn.
                        StatusDot {
                            visible: !event.isTurn
                            anchors.verticalCenter: parent.verticalCenter
                            width: 8; height: 8
                            tone: event.tone
                            pulsing: event.modelData.state === "running" || event.modelData.state === "waiting"
                        }
                        Icon {
                            visible: event.isTurn
                            anchors.verticalCenter: parent.verticalCenter
                            name: "bolt"
                            ink: Theme.textDisabled
                            width: 11; height: 11
                        }
                        Icon {
                            visible: !event.isTurn
                            anchors.verticalCenter: parent.verticalCenter
                            name: event.modelData.icon || "bolt"
                            ink: event.modelData.state === "done" ? Theme.textDisabled : event.tone
                            width: 12; height: 12
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.min(implicitWidth, body.width - 130)
                            text: event.modelData.summary || event.modelData.label
                            color: event.isTurn ? Theme.textMuted : Theme.textPrimary
                            font.family: Theme.sansFamily
                            font.pixelSize: event.isTurn ? Theme.micro : Theme.caption
                            font.weight: event.isTurn ? Font.Medium : Font.Normal
                            font.capitalization: event.isTurn ? Font.AllUppercase : Font.MixedCase
                            font.letterSpacing: event.isTurn ? 0.6 : 0
                            elide: Text.ElideRight
                        }
                        // State is never colour alone: a word rides with it.
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !event.isTurn && event.modelData.state !== "done"
                                     && event.modelData.state !== "running"
                            text: Theme.stateLabel(event.modelData.state)
                            color: event.tone
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: !!event.modelData.durationLabel
                            text: event.modelData.durationLabel
                            color: Theme.textDisabled
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        }
                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: event.hasDetail && !event.isTurn
                            name: event.expanded ? "chevronDown" : "chevronRight"
                            ink: Theme.textDisabled
                            width: 10; height: 10
                        }
                    }

                    Text {
                        width: parent.width
                        visible: !event.isTurn && text !== ""
                        leftPadding: 20
                        text: event.modelData.output || ""
                        textFormat: Text.PlainText
                        color: event.modelData.state === "failed" ? Theme.danger : Theme.textMuted
                        font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                        wrapMode: Text.WordWrap
                        maximumLineCount: event.expanded ? 24 : 1
                        elide: Text.ElideRight
                        lineHeight: 1.4
                    }

                    Rectangle {
                        width: parent.width - 20
                        x: 20
                        visible: event.expanded && !!event.modelData.detail
                        height: visible ? detail.implicitHeight + Theme.s2 * 2 : 0
                        radius: Theme.r1
                        color: Theme.surfaceSunken
                        Text {
                            id: detail
                            anchors.fill: parent
                            anchors.margins: Theme.s2
                            text: event.modelData.detail || ""
                            textFormat: Text.PlainText
                            color: Theme.textMuted
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                            wrapMode: Text.WrapAnywhere
                            maximumLineCount: 12
                            elide: Text.ElideRight
                        }
                    }

                    Item { width: 1; height: Theme.s1; visible: event.expanded }
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: event.hasDetail && !event.isTurn
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: event.expanded = !event.expanded
                }
            }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.rows.length === 0
            iconName: "activity"
            title: "No activity yet"
            detail: "Every command, file read and desktop action Wynxo takes is recorded here while the app is open."
        }
    }
}
