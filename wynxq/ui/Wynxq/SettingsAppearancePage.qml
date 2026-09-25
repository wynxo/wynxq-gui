import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* Appearance settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    function prepare() {
        accentField.text = bridge ? bridge.accentColor : "";
    }

    Connections {
        target: bridge
        function onChanged() {
            if (!accentField.activeFocus) accentField.text = bridge.accentColor;
        }
    }

    spacing: Theme.s5
    SettingsGroup {
        title: "App colors"
        description: "Change the canvas, sidebar, settings, panels and controls together. Applied immediately and remembered after restart."
        Segmented {
            objectName: "appColorSchemePicker"
            width: Math.min(360, parent.width)
            options: [{id: "Dark", label: "Dark gray"}, {id: "Black", label: "Black"}, {id: "Midnight", label: "Midnight"}]
            current: bridge ? bridge.colorScheme : "Dark"
            onSelected: function(value) { if (bridge) bridge.setColorScheme(value); }
        }
    }
    SettingsGroup {
        title: "Accent"
        description: "Choose the highlight color for buttons, selections and focus throughout the app. Activity stays green and status colors keep their meaning."
        Flow {
            width: parent.width
            spacing: Theme.s2
            Repeater {
                model: bridge ? bridge.themes : []
                delegate: AbstractButton {
                    id: swatch
                    required property var modelData
                    readonly property bool current: bridge && bridge.accentColor.toLowerCase() === modelData.color.toLowerCase()
                    width: 88; height: 44
                    hoverEnabled: true
                    Accessible.name: modelData.name
                    Accessible.checked: current
                    onClicked: { if (bridge) bridge.setTheme(modelData.name); accentField.text = modelData.color; }
                    background: Rectangle {
                        radius: Theme.r1
                        color: swatch.current ? Theme.surfaceRaised : swatch.hovered ? Theme.surfaceHover : "transparent"
                        border.width: swatch.current || swatch.visualFocus ? 1 : 0
                        border.color: swatch.visualFocus ? Theme.accentEdge : Theme.border
                        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                    }
                    contentItem: Column {
                        spacing: Theme.s2
                        topPadding: Theme.s2
                        Rectangle {
                            width: 18; height: 18; radius: 9
                            color: modelData.color
                            anchors.horizontalCenter: parent.horizontalCenter
                            Icon {
                                anchors.centerIn: parent
                                visible: swatch.current
                                name: "check"; ink: Theme.textInverse
                                width: 11; height: 11
                            }
                        }
                        Text {
                            text: modelData.name
                            color: swatch.current ? Theme.textPrimary : Theme.textSecondary
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            anchors.horizontalCenter: parent.horizontalCenter
                        }
                    }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                }
            }
        }
        Row {
            spacing: Theme.s2
            width: parent.width
            Field {
                id: accentField
                width: Math.min(200, parent.width - 100)
                mono: true
                placeholderText: "#e9e3d6"
                onAccepted: if (bridge) bridge.setAccent(text)
            }
            WButton { text: "Apply"; onClicked: if (bridge) bridge.setAccent(accentField.text) }
        }
    }
    SettingsGroup {
        title: "Density and motion"
        Segmented {
            width: 240
            options: [{ id: "Comfortable", label: "Comfortable" }, { id: "Compact", label: "Compact" }]
            current: bridge ? bridge.density : "Comfortable"
            onSelected: function(value) { if (bridge) bridge.setDensity(value); }
        }
        Toggle {
            width: parent.width
            text: "Reduce motion"
            description: "Turn off transitions and looping animations."
            checked: bridge ? bridge.reducedMotion : false
            onSwitched: function(value) { if (bridge) bridge.setFlag("reduced_motion", value); }
        }
        Toggle {
            width: parent.width
            text: "Use the system font"
            description: "Match your desktop's interface font instead of the bundled Inter."
            checked: bridge ? bridge.systemFont : false
            onSwitched: function(value) { if (bridge) bridge.setFlag("system_font", value); }
        }
        Toggle {
            width: parent.width
            text: "Solid dark canvas"
            description: "A flat background instead of the layered one."
            checked: bridge ? bridge.solidBackground : true
            onSwitched: function(value) { if (bridge) bridge.setFlag("solid_background", value); }
        }
    }
}
