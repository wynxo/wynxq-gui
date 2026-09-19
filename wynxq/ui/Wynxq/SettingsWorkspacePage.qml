import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* Workspace settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    spacing: Theme.s6

    SettingsGroup {
        title: "The dock"
        description: "Files, Terminal, Changes, Context, Memory, Activity, Browser and Preview live on the right. Closing the workspace removes the panel and rail together; restore it from the lower-right button or Ctrl+Shift+B."

        Row {
            width: parent.width
            spacing: Theme.s3
            Toggle {
                id: dockToggle
                anchors.verticalCenter: parent.verticalCenter
                checked: !!(bridge && bridge.workspaceDock && bridge.workspaceDock.visible)
                Accessible.name: "Open the workspace dock"
                onToggled: if (bridge && bridge.workspaceDock)
                               bridge.workspaceDock.setVisible(checked)
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                SettingsFieldLabel { text: "Open the dock panel" }
                Text {
                    text: "Remembered between sessions, along with its width and the tab you left open."
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                    width: hostSheet.width - 420
                    wrapMode: Text.WordWrap
                }
            }
        }

        Row {
            width: parent.width
            spacing: Theme.s3
            Toggle {
                anchors.verticalCenter: parent.verticalCenter
                checked: !!(bridge && bridge.workspaceDock && bridge.workspaceDock.showHidden)
                Accessible.name: "Show hidden files in the tree"
                onToggled: if (bridge && bridge.workspaceDock)
                               bridge.workspaceDock.setShowHidden(checked)
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1
                SettingsFieldLabel { text: "Show dotfiles in the file tree" }
                Text {
                    text: "Build folders and caches stay hidden either way."
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                }
            }
        }
    }

    SettingsGroup {
        title: "Terminal"
        description: "The Terminal panel runs a real shell in the project folder, with your own environment. It starts when you first open the panel and stays open for the session."

        Row {
            width: parent.width
            spacing: Theme.s3
            Column {
                spacing: 2
                SettingsFieldLabel { text: "Shell" }
                Text {
                    text: bridge && bridge.workspaceDock && bridge.workspaceDock.terminalShell
                          ? bridge.workspaceDock.terminalShell : "Your login shell ($SHELL)"
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                }
            }
            Item { width: Theme.s5; height: 1 }
            Column {
                spacing: 2
                SettingsFieldLabel { text: "Working directory" }
                Text {
                    text: bridge && bridge.workspaceDock && bridge.workspaceDock.terminalDirectoryLabel
                          ? bridge.workspaceDock.terminalDirectoryLabel : "The project folder, or home"
                    color: Theme.textSecondary
                    font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                }
            }
        }

        WButton {
            text: "Restart the shell"
            iconName: "retry"
            compactPadding: true
            enabled: !!(bridge && bridge.workspaceDock)
            onClicked: if (bridge && bridge.workspaceDock) bridge.workspaceDock.restartTerminal()
        }
    }

    SettingsGroup {
        title: "Browser"
        description: "A page opens beside the conversation instead of pulling you out of Wynxq. Nothing on it reaches the model until you attach it."

        Row {
            width: parent.width
            spacing: Theme.s2
            StatusDot {
                anchors.verticalCenter: parent.verticalCenter
                tone: bridge && bridge.workspaceDock && bridge.workspaceDock.browserAvailable
                      ? Theme.success : Theme.textMuted
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - Theme.s5
                text: bridge && bridge.workspaceDock && bridge.workspaceDock.browserAvailable
                      ? "Qt WebEngine is available on this system."
                      : (bridge && bridge.workspaceDock ? bridge.workspaceDock.browserUnavailableReason : "")
                color: Theme.textSecondary
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                wrapMode: Text.WordWrap
            }
        }

        Text {
            width: parent.width
            text: "Pop-ups, screen capture and permission requests are refused; only http and https addresses are opened."
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
    }

    SettingsGroup {
        title: "Changes"
        description: "Uncommitted work is read from Git in the project folder. Discarding a file's changes always asks first."

        Row {
            width: parent.width
            spacing: Theme.s2
            StatusDot {
                anchors.verticalCenter: parent.verticalCenter
                tone: bridge && bridge.workspaceDock && bridge.workspaceDock.isRepository
                      ? Theme.success : Theme.textMuted
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: !bridge || !bridge.workspaceDock ? ""
                    : !bridge.projectPath ? "No project is open."
                    : bridge.workspaceDock.isRepository
                      ? "Tracking " + bridge.workspaceDock.branch
                      : "The project folder is not a Git repository."
                color: Theme.textSecondary
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            }
        }
    }
}
