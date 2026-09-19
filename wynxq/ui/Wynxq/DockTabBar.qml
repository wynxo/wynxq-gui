import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The dock's rail: one icon per tool while the workspace is open.

    Closing the workspace removes this rail as well. Main.qml owns the lone
    restore button, so collapse produces a clean edge instead of a second,
    thinner sidebar. Clicking the chosen tab still closes the workspace.

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
            visible: !!(bridge && bridge.planSteps && bridge.planSteps.length > 0)
            implicitWidth: 32
            implicitHeight: visible ? 32 : 0
            hoverEnabled: true
            readonly property bool chosen: root.panelOpen && root.planSelected

            Accessible.role: Accessible.Button
            Accessible.name: "Plan"
            Accessible.checked: chosen
            onClicked: root.pickedPlan()

            ToolTip.visible: hovered
            ToolTip.text: "Plan · live task steps"
            ToolTip.delay: Theme.tooltipDelay

            scale: down ? Theme.pressScale : 1
            Behavior on scale {
                enabled: !Theme.reducedMotion
                NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
            }

            background: GlassSurface {
                radius: Theme.r2
                solid: planTab.chosen
                glassEnabled: planTab.hovered || planTab.down || planTab.visualFocus
                tint: planTab.chosen ? Theme.surfaceSelected
                      : planTab.down ? Theme.glassTintStrong : Theme.glassTintHover
                fillOpacity: planTab.chosen ? 1.0
                           : planTab.down ? 0.62
                           : planTab.hovered ? 0.46
                           : planTab.visualFocus ? 0.34 : 0.0
                outlineVisible: planTab.chosen || planTab.hovered || planTab.visualFocus
                strongEdge: planTab.hovered || planTab.down || planTab.visualFocus
                active: planTab.visualFocus
                sheen: planTab.hovered || planTab.down
                edgeColor: planTab.visualFocus ? Theme.accentEdge
                         : planTab.chosen ? Theme.glassEdge
                         : planTab.hovered ? Theme.glassEdgeStrong : "transparent"
            }

            contentItem: Item {
                Icon {
                    anchors.centerIn: parent
                    name: "clipboard"
                    ink: planTab.chosen ? Theme.accent
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
                height: planTab.chosen ? 14 : 0
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
                implicitWidth: 32
                implicitHeight: 32
                hoverEnabled: true
                readonly property bool chosen: root.panelOpen && !root.planSelected && root.current === modelData.id
                readonly property bool marked: !root.panelOpen && !root.planSelected && root.current === modelData.id

                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                Accessible.checked: chosen
                onClicked: root.picked(modelData.id)

                ToolTip.visible: hovered
                ToolTip.text: modelData.label + " · " + modelData.shortcut
                ToolTip.delay: Theme.tooltipDelay

                scale: down ? Theme.pressScale : 1
                Behavior on scale {
                    enabled: !Theme.reducedMotion
                    NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
                }

                background: GlassSurface {
                    radius: Theme.r2
                    solid: tab.chosen
                    glassEnabled: tab.hovered || tab.down || tab.visualFocus
                    tint: tab.chosen ? Theme.surfaceSelected
                          : tab.down ? Theme.glassTintStrong : Theme.glassTintHover
                    fillOpacity: tab.chosen ? 1.0
                               : tab.down ? 0.62
                               : tab.hovered ? 0.46
                               : tab.visualFocus ? 0.34 : 0.0
                    outlineVisible: tab.chosen || tab.hovered || tab.visualFocus
                    strongEdge: tab.hovered || tab.down || tab.visualFocus
                    active: tab.visualFocus
                    sheen: tab.hovered || tab.down
                    edgeColor: tab.visualFocus ? Theme.accentEdge
                             : tab.chosen ? Theme.glassEdge
                             : tab.hovered ? Theme.glassEdgeStrong : "transparent"
                }

                contentItem: Item {
                    Icon {
                        anchors.centerIn: parent
                        name: tab.modelData.icon
                        ink: tab.chosen ? Theme.accent
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
                    height: tab.chosen ? 14 : 0
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
