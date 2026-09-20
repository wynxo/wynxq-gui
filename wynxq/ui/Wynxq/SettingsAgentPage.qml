import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* Agent settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    spacing: Theme.s6
    SettingsGroup {
        title: "Local copilot"
        description: "Ask Wynxq to open apps, run commands, inspect files or help with code. Tools execute on this computer even when Ollama inference runs on another server. Commands run in your workspace folder, or your home folder when none is selected."
    }
    SettingsGroup {
        title: "Screen control"
        description: "Wynxq can see your screen and use your mouse and keyboard. It starts off every time Wynxq opens."
        Row {
            spacing: Theme.s3
            WButton {
                text: !(bridge && bridge.desktopAvailable) ? "Unavailable here"
                    : bridge && bridge.desktopEnabled ? "Turn off screen control"
                    : "Turn on screen control"
                iconName: "cursor"
                variant: bridge && bridge.desktopEnabled ? "secondary" : "primary"
                enabled: bridge && !bridge.connecting && bridge.desktopAvailable
                onClicked: if (bridge) bridge.toggleDesktop()
            }
            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.s2
                StatusDot {
                    anchors.verticalCenter: parent.verticalCenter
                    tone: bridge && bridge.desktopEnabled ? Theme.accent : Theme.textMuted
                    pulsing: bridge && bridge.desktopEnabled && bridge.busy
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: bridge && bridge.desktopEnabled ? "On" : "Off"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
            }
        }
        Text {
            width: parent.width
            text: bridge ? bridge.desktopBackend + " — " + bridge.desktopDetail : ""
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
        Row {
            width: parent.width
            spacing: Theme.s2
            visible: bridge && bridge.desktopRemembered
            Icon { name: "check"; ink: Theme.success; width: 13; height: 13
                   anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Your desktop remembered this permission, so it did not ask again."
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            }
        }
    }

    SettingsGroup {
        title: "Stopping a run"
        description: "Escape stops generation and desktop actions whenever Wynxq has focus. While a model is driving another window, Wynxq does not — so it also asks your desktop for a shortcut that works from anywhere."
        Row {
            spacing: Theme.s2
            visible: !!(bridge && bridge.desktopStopShortcut)
            Icon { name: "keyboard"; ink: Theme.textMuted; width: 14; height: 14
                   anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Stop from anywhere"
                color: Theme.textSecondary
                font.family: Theme.sansFamily; font.pixelSize: Theme.label
            }
            KeyHint {
                anchors.verticalCenter: parent.verticalCenter
                keys: bridge ? bridge.desktopStopShortcut : ""
            }
        }
        Text {
            width: parent.width
            visible: !!(bridge && bridge.desktopStopDetail) && !(bridge && bridge.desktopStopShortcut)
            text: bridge ? bridge.desktopStopDetail : ""
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
        Text {
            width: parent.width
            visible: !(bridge && bridge.desktopEnabled)
            text: "Turn screen control on to see which key your desktop assigned."
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
    }
    SettingsGroup {
        title: "Permission"
        description: "How much Wynxq may do — commands as well as the desktop — without asking first. It applies to Work and Wynxi tasks. A Chat task has no tools at all, so nothing there is ever approved."
        Repeater {
            model: bridge ? bridge.permissionModes : []
            delegate: AbstractButton {
                id: mode
                required property var modelData
                readonly property bool current: bridge && bridge.permissionMode === modelData.id
                width: parent.width
                implicitHeight: 54
                hoverEnabled: true
                Accessible.name: modelData.label
                Accessible.description: modelData.detail
                Accessible.checked: current
                onClicked: if (bridge) bridge.setPermissionMode(modelData.id)

                background: Rectangle {
                    radius: Theme.r2
                    color: mode.current ? Theme.surfaceSelected
                         : mode.hovered ? Theme.surfaceHover : "transparent"
                    border.width: mode.current || mode.visualFocus ? 1 : 0
                    border.color: Theme.accentEdge
                    Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                }
                contentItem: Row {
                    leftPadding: Theme.s4
                    spacing: Theme.s3
                    Icon {
                        name: mode.current ? "check" : "shield"
                        ink: mode.current ? Theme.accent : Theme.textMuted
                        width: 16; height: 16
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            text: modelData.label; color: Theme.textPrimary
                            font.family: Theme.sansFamily; font.pixelSize: Theme.label
                            font.weight: Font.Medium
                        }
                        Text {
                            text: modelData.detail; color: Theme.textMuted
                            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                        }
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
            }
        }
        Text {
            width: parent.width
            text: "Reading the screen and moving the pointer never prompt — they change nothing. Every run also has an action budget, set under Model & runtime."
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
    }

    SettingsGroup {
        title: "Memory"
        description: "Your selected model automatically learns useful facts, preferences and ongoing work from conversations. It can update saved notes and select relevant context from older chats. Both are stored locally and can be turned off separately; context used for an answer is sent to the selected Ollama server."

        Toggle {
            width: parent.width
            text: "Remember things between tasks"
            description: bridge ? bridge.memorySummary : ""
            checked: !!(bridge && bridge.memoryEnabled)
            onSwitched: function(value) { if (bridge) bridge.setMemoryEnabled(value); }
        }
        Toggle {
            width: parent.width
            text: "Reference past chats"
            description: "Let the model search older chats and select useful context by meaning. Recall depends on the model and adds processing time. Old assistant replies are never treated as facts."
            checked: !!(bridge && bridge.referenceChatHistory)
            onSwitched: function(value) { if (bridge) bridge.setReferenceChatHistory(value); }
        }
        Row {
            width: parent.width
            spacing: Theme.s2
            WButton {
                text: "Open the Memory panel"
                variant: "secondary"
                onClicked: { hostSheet.close(); hostSheet.openMemoryPanel(); }
            }
            WButton {
                text: "Show memory.md"
                variant: "ghost"
                onClicked: if (bridge) bridge.revealMemory()
            }
        }
        Text {
            width: parent.width
            text: "Notes are stored in " + (bridge ? bridge.memoryPath : "memory.md")
                 + " on this computer. Wynxq is told never to save secrets or credentials there;"
                 + " anything you would rather it forgot can be deleted in the panel. When relevant,"
                 + " saved memory and recalled chat excerpts are included in requests to the selected Ollama server."
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
    }
}
