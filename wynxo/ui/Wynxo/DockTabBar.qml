import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The dock's rail: one icon per tool, always on the right edge.

    The rail is the dock's affordance. It stays even when the panel is closed,
    so the tools are one click away and the window never loses its right-hand
    anchor. Clicking the tab that is already showing closes the panel — the same
    gesture opens and dismisses.

    Plan is intentionally a presentation tab rather than another backend tool.
    It shows the agent-authored, persisted execution plan while Activity remains
    the detailed audit trail of commands and desktop actions.
*/
Item {
    id: root
    property string current: ""
    property bool panelOpen: false
    property bool planSelected: false
    signal picked(string id)
    signal pickedPlan()
    signal toggleDock()

    implicitWidth: Theme.railWidth

    readonly property var entries: bridge && bridge.workspaceDock ? bridge.workspaceDock.tabs : []

    // The rail is permanent workspace chrome, so it stays opaque. Individual
    // tabs still use glass for hover/press/focus because those are transient
    // interactions rather than another always-on translucent layer.
    Rectangle {
        anchors.fill: parent
        color: Theme.backgroundSoft
        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 1
            color: Theme.borderSubtle
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: Theme.s2
        anchors.bottomMargin: Theme.s2
        spacing: 2

        AbstractButton {
            id: planTab
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: 34
            implicitHeight: 34
            hoverEnabled: true
            readonly property bool chosen: root.panelOpen && root.planSelected

            Accessible.role: Accessible.Button
            Accessible.name: "Plan"
            Accessible.checked: chosen
            onClicked: root.pickedPlan()

            ToolTip.visible: hovered
            ToolTip.text: "Plan · live task steps"
            ToolTip.delay: 450

            background: GlassSurface {
                radius: Theme.r2
                tint: planTab.chosen ? Theme.accent
                     : planTab.down ? Theme.glassTintStrong : Theme.glassTintHover
                fillOpacity: planTab.down ? 0.72
                           : planTab.chosen ? 0.14
                           : planTab.hovered ? 0.50 : 0.0
                outlineVisible: planTab.chosen || planTab.hovered || planTab.visualFocus
                strongEdge: planTab.chosen || planTab.hovered
                active: planTab.visualFocus
                sheen: planTab.chosen || planTab.hovered
                edgeColor: planTab.visualFocus ? Theme.accentEdge
                         : planTab.chosen ? Theme.accentEdge : Theme.glassEdge
            }

            contentItem: Item {
                Icon {
                    anchors.centerIn: parent
                    name: "clipboard"
                    ink: planTab.chosen ? Theme.textPrimary
                       : planTab.hovered ? Theme.textSecondary : Theme.textMuted
                    width: 15; height: 15
                    weight: 1.7
                }
            }

            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: -Theme.s2 - 1
                anchors.verticalCenter: parent.verticalCenter
                width: 2
                height: planTab.chosen ? 18 : 0
                radius: 1
                color: Theme.accent
                Behavior on height { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast; easing.type: Theme.easing } }
            }

            Rectangle {
                visible: !root.panelOpen && bridge && bridge.planSteps && bridge.planSteps.length >= 2
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.margins: 6
                width: 5; height: 5; radius: 2.5
                color: Theme.accent
            }

            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
        }

        Repeater {
            model: root.entries
            delegate: AbstractButton {
                id: tab
                required property var modelData
                required property int index
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: 34
                implicitHeight: 34
                hoverEnabled: true
                readonly property bool chosen: root.panelOpen && !root.planSelected && root.current === modelData.id
                readonly property bool marked: !root.panelOpen && !root.planSelected && root.current === modelData.id

                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                Accessible.checked: chosen
                onClicked: root.picked(modelData.id)

                ToolTip.visible: hovered
                ToolTip.text: modelData.label + " · " + modelData.shortcut
                ToolTip.delay: 450

                background: GlassSurface {
                    radius: Theme.r2
                    tint: tab.chosen ? Theme.accent
                         : tab.down ? Theme.glassTintStrong : Theme.glassTintHover
                    fillOpacity: tab.down ? 0.72
                               : tab.chosen ? 0.14
                               : tab.hovered ? 0.50 : 0.0
                    outlineVisible: tab.chosen || tab.hovered || tab.visualFocus
                    strongEdge: tab.chosen || tab.hovered
                    active: tab.visualFocus
                    sheen: tab.chosen || tab.hovered
                    edgeColor: tab.visualFocus ? Theme.accentEdge
                             : tab.chosen ? Theme.accentEdge : Theme.glassEdge
                }

                contentItem: Item {
                    Icon {
                        anchors.centerIn: parent
                        name: tab.modelData.icon
                        ink: tab.chosen ? Theme.textPrimary
                           : tab.hovered || tab.marked ? Theme.textSecondary : Theme.textMuted
                        width: 15; height: 15
                        weight: 1.7
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: -Theme.s2 - 1
                    anchors.verticalCenter: parent.verticalCenter
                    width: 2
                    height: tab.chosen ? 18 : 0
                    radius: 1
                    color: Theme.accent
                    Behavior on height { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast; easing.type: Theme.easing } }
                }

                Rectangle {
                    visible: !root.panelOpen && tab.modelData.id === "activity"
                             && bridge && bridge.workspaceDock && bridge.workspaceDock.activityRunning
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 6
                    width: 5; height: 5; radius: 2.5
                    color: Theme.accent
                }

                WMenu {
                    id: tabMenu
                    anchorX: -menuWidth
                    menuWidth: 210
                    items: [
                        { id: "up", label: "Move up", icon: "up", disabled: tab.index === 0 },
                        { id: "down", label: "Move down", icon: "down",
                          disabled: tab.index === root.entries.length - 1 },
                        { separator: true },
                        { id: "hide", label: "Hide from rail", icon: "close" },
                    ]
                    onPicked: function(id) {
                        if (!bridge || !bridge.workspaceDock) return;
                        if (id === "up") bridge.workspaceDock.moveTab(tab.modelData.id, -1);
                        else if (id === "down") bridge.workspaceDock.moveTab(tab.modelData.id, 1);
                        else if (id === "hide") bridge.workspaceDock.setTabHidden(tab.modelData.id, true);
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onClicked: tabMenu.open()
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
            }
        }

        Item { Layout.fillHeight: true }

        IconButton {
            Layout.alignment: Qt.AlignHCenter
            width: 30; height: 30
            iconSize: 13
            iconName: root.panelOpen ? "forward" : "back"
            tooltip: root.panelOpen ? "Close the workspace dock" : "Open the workspace dock"
            shortcut: "Ctrl+Shift+B"
            onClicked: root.toggleDock()
        }
    }
}
