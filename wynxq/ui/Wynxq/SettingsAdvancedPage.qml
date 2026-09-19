import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* Advanced settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    spacing: Theme.s6
    SettingsGroup {
        title: "Privacy & data path"
        description: bridge ? bridge.endpointPrivacyHint : ""
        Repeater {
            model: [
                { icon: "layers", line: "Inference is sent only to the Ollama server URL you configure above." },
                { icon: "chat", line: "Task history stays in Wynxq's private SQLite database on this computer." },
                { icon: "camera", line: "Screenshots are not written to chat history, but a model request can send them to your configured Ollama server." },
                { icon: "lock", line: "Wynxq has no account, API key requirement, telemetry service, or hosted backend of its own." },
                { icon: "shield", line: "Server redirects and environment proxy settings are refused by the Ollama transport." },
            ]
            delegate: RowLayout {
                required property var modelData
                width: parent.width
                spacing: Theme.s3
                Icon { name: modelData.icon; ink: Theme.textMuted; width: 14; height: 14; Layout.alignment: Qt.AlignTop }
                Text {
                    Layout.fillWidth: true
                    text: modelData.line; color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                    wrapMode: Text.WordWrap; lineHeight: 1.45
                }
            }
        }
    }
    SettingsGroup {
        title: "Local data"
        Text {
            width: parent.width
            text: bridge ? bridge.dataLocation : ""
            color: Theme.textSecondary
            font.family: Theme.monoFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WrapAnywhere
        }
        Row {
            spacing: Theme.s2
            WButton {
                text: "Open data folder"
                iconName: "folder"
                onClicked: if (bridge) bridge.revealPath(bridge.dataLocation.replace(/\/[^/]*$/, ""))
            }
            WButton {
                text: "Replay the welcome"
                iconName: "retry"
                variant: "ghost"
                onClicked: { if (bridge) bridge.resetOnboarding(); hostSheet.close(); }
            }
        }
    }
    SettingsGroup {
        title: "Global quick bar"
        description: "Linux gives applications no system-wide hotkey. Bind your desktop's custom shortcut to this command and the quick bar will open from anywhere."
        Rectangle {
            width: parent.width; height: 38; radius: Theme.r2
            color: Theme.surfaceSunken
            border.width: 1; border.color: Theme.borderSubtle
            Text {
                anchors.left: parent.left; anchors.leftMargin: Theme.s3
                anchors.verticalCenter: parent.verticalCenter
                text: "wynxq --quick"
                color: Theme.textSecondary
                font.family: Theme.monoFamily; font.pixelSize: Theme.caption
            }
            IconButton {
                anchors.right: parent.right; anchors.rightMargin: Theme.s1
                anchors.verticalCenter: parent.verticalCenter
                width: 30; height: 30; iconSize: 14
                iconName: "copy"; tooltip: "Copy command"
                onClicked: if (bridge) bridge.copyText("wynxq --quick")
            }
        }
    }
    SettingsGroup {
        title: "About"
        Text {
            width: parent.width
            text: "Wynxq " + (bridge ? bridge.appVersion : "") + " — an Ollama-powered copilot for the Linux desktop. "
                  + "Inference can run locally or on a server you choose. Desktop backend: " + (bridge ? bridge.desktopBackend : "") + ".\n\n"
                  + "Interface type is Inter; code is set in JetBrains Mono, both under the SIL Open Font "
                  + "License. Wynxq is an independent project and is not affiliated with Ollama or any AI vendor."
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.5
        }
    }
}
