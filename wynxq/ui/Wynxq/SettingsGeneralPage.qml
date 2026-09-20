import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* General settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    function prepare() {
        endpointNameField.text = "";
        endpointField.text = "";
    }

    spacing: Theme.s6
    SettingsGroup {
        title: "Ollama servers"
        description: "Keep several Ollama machines. The default starts new chats; each existing chat remembers its own server and model."

        Repeater {
            model: bridge ? bridge.endpointProfiles : []
            delegate: Rectangle {
                id: endpointRow
                required property var modelData
                width: parent.width
                implicitHeight: 48
                radius: Theme.r2
                color: modelData.selected ? Theme.surfaceSelected : "transparent"
                border.width: 1
                border.color: modelData.selected ? Theme.borderStrong : Theme.borderSubtle

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.s3
                    anchors.rightMargin: Theme.s2
                    spacing: Theme.s2
                    StatusDot {
                        tone: modelData.selected && bridge && bridge.online
                            ? Theme.success : Theme.textDisabled
                        Layout.preferredWidth: 7; Layout.preferredHeight: 7
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.s2
                            Text {
                                text: modelData.name
                                color: Theme.textPrimary
                                font.family: Theme.sansFamily
                                font.pixelSize: Theme.label
                                font.weight: Font.Medium
                            }
                            Text {
                                visible: modelData.default
                                text: "DEFAULT"
                                color: Theme.textMuted
                                font.family: Theme.monoFamily
                                font.pixelSize: Theme.micro
                            }
                            Text {
                                visible: modelData.selected
                                text: "THIS CHAT"
                                color: Theme.success
                                font.family: Theme.monoFamily
                                font.pixelSize: Theme.micro
                            }
                            Item { Layout.fillWidth: true }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.url
                            color: Theme.textMuted
                            font.family: Theme.monoFamily
                            font.pixelSize: Theme.micro
                            elide: Text.ElideMiddle
                        }
                    }
                    WButton {
                        visible: !modelData.selected
                        text: "Use"
                        variant: "ghost"
                        compactPadding: true
                        enabled: bridge && !bridge.busy
                        onClicked: if (bridge) bridge.selectEndpoint(modelData.url)
                    }
                    WButton {
                        visible: !modelData.default
                        text: "Default"
                        variant: "ghost"
                        compactPadding: true
                        onClicked: if (bridge) bridge.setDefaultEndpoint(modelData.url)
                    }
                    IconButton {
                        visible: !modelData.default && !modelData.selected
                        width: 28; height: 28; iconSize: 12
                        iconName: "close"
                        tooltip: "Remove server"
                        onClicked: if (bridge) bridge.removeEndpointProfile(modelData.url)
                    }
                }
            }
        }

        RowLayout {
            width: parent.width
            spacing: Theme.s2
            Field {
                id: endpointNameField
                Layout.preferredWidth: 120
                placeholderText: "Server name"
                Accessible.name: "Ollama server name"
            }
            Field {
                id: endpointField
                Layout.fillWidth: true
                mono: true
                placeholderText: "http://192.168.178.29:11434"
                Accessible.name: "Ollama server URL"
                onAccepted: addEndpoint.clicked()
            }
            WButton {
                id: addEndpoint
                text: "Add"
                variant: "primary"
                onClicked: if (bridge && bridge.addEndpointProfile(
                    endpointNameField.text, endpointField.text)) {
                    endpointNameField.text = "";
                    endpointField.text = "";
                }
            }
        }

        RowLayout {
            width: parent.width
            spacing: Theme.s2
            StatusDot {
                tone: bridge && bridge.online ? Theme.success : Theme.danger
                Layout.preferredWidth: 7; Layout.preferredHeight: 7
            }
            Text {
                Layout.fillWidth: true
                text: !bridge ? ""
                    : bridge.online
                        ? bridge.endpointProfileName + " · " + bridge.models.length
                          + " model" + (bridge.models.length === 1 ? "" : "s")
                        : bridge.endpointProfileName + " · not connected"
                color: bridge && bridge.online ? Theme.textSecondary : Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            }
            WButton {
                text: "Reconnect"
                iconName: "retry"
                variant: "ghost"
                compactPadding: true
                onClicked: if (bridge) bridge.refreshModels()
            }
        }

        Text {
            width: parent.width
            text: bridge ? bridge.endpointPrivacyHint : ""
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
        Rectangle {
            width: parent.width
            visible: bridge && bridge.endpointScope === "remote"
                     && String(bridge.endpoint).indexOf("http://") === 0
            implicitHeight: insecureText.implicitHeight + Theme.s3 * 2
            radius: Theme.r2
            color: Theme.warningMuted
            border.width: 1
            border.color: Theme.alpha(Theme.warning, 0.35)
            Text {
                id: insecureText
                anchors.fill: parent
                anchors.margins: Theme.s3
                text: "This remote server uses plain HTTP. Prefer HTTPS or a trusted private tunnel before sending screenshots or sensitive files."
                color: Theme.textSecondary
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                wrapMode: Text.WordWrap; lineHeight: 1.45
            }
        }
    }
    SettingsGroup {
        title: "Behaviour"
        Toggle {
            width: parent.width
            text: "Desktop notifications"
            description: "Tell me when a long task finishes and Wynxq is not focused."
            checked: bridge ? bridge.notificationsEnabled : true
            onSwitched: function(value) { if (bridge) bridge.setFlag("notifications", value); }
        }
        Toggle {
            width: parent.width
            text: "System tray icon"
            description: "Keep Wynxq reachable from the tray. Takes effect on restart."
            checked: bridge ? bridge.trayEnabled : false
            onSwitched: function(value) { if (bridge) bridge.setFlag("tray", value); }
        }
    }
}
