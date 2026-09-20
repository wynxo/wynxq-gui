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

    spacing: Theme.s6
    SettingsGroup {
        title: "Accent"
        description: "One restrained highlight colour, used sparingly across the app."
        Flow {
            width: parent.width
            spacing: Theme.s2
            Repeater {
                model: bridge ? bridge.themes : []
                delegate: AbstractButton {
                    id: swatch
                    required property var modelData
                    readonly property bool current: bridge && bridge.theme === modelData.name
                    width: 96; height: 52
                    hoverEnabled: true
                    Accessible.name: modelData.name
                    Accessible.checked: current
                    onClicked: { if (bridge) bridge.setTheme(modelData.name); accentField.text = modelData.color; }
                    background: Rectangle {
                        radius: Theme.r2
                        color: swatch.hovered ? Theme.surfaceHover : Theme.surface
                        border.width: 1
                        border.color: swatch.current || swatch.visualFocus ? Theme.accentEdge : Theme.borderSubtle
                        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                    }
                    contentItem: Column {
                        spacing: Theme.s2
                        topPadding: Theme.s2
                        Rectangle {
                            width: 22; height: 22; radius: 11
                            color: modelData.color
                            anchors.horizontalCenter: parent.horizontalCenter
                            Icon {
                                anchors.centerIn: parent
                                visible: swatch.current
                                name: "check"; ink: Theme.textInverse
                                width: 13; height: 13
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
