import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Models belong to the configured Ollama server. That server may be this
    computer, a homelab machine, or another trusted host; the UI never pretends
    a remote catalogue or download lives on the Wynxq machine.
*/
Sheet {
    id: sheet
    title: "Models"
    subtitle: bridge ? "Installed on Ollama · " + bridge.endpointScopeLabel : "Installed on Ollama"
    width: Math.min(720, parent ? parent.width - Theme.s7 : 720)
    height: Math.min(600, parent ? parent.height - Theme.s7 : 600)

    property string query: ""
    property string pendingDelete: ""

    onOpened: { query = ""; filter.text = ""; if (bridge) bridge.refreshModels(); filter.forceActiveFocus(); }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.s5
        anchors.topMargin: 0
        spacing: Theme.s3

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            Field {
                id: filter
                Layout.fillWidth: true
                iconName: "search"
                placeholderText: "Filter installed models"
                onTextChanged: sheet.query = text.toLowerCase()
                Keys.onEscapePressed: function(event) {
                    if (text.length) { text = ""; event.accepted = true; }
                    else event.accepted = false;
                }
            }
            IconButton {
                iconName: "retry"; tooltip: "Refresh from Ollama"
                onClicked: if (bridge) bridge.refreshModels()
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 1
            model: bridge ? bridge.modelCatalog : []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: WScrollBar { policy: ScrollBar.AsNeeded }

            delegate: AbstractButton {
                id: entry
                required property var modelData
                readonly property bool matches: !sheet.query || modelData.name.toLowerCase().indexOf(sheet.query) !== -1
                width: list.width
                height: matches ? 58 : 0
                visible: matches
                hoverEnabled: true
                Accessible.name: modelData.name
                Accessible.checked: modelData.selected
                onClicked: { if (bridge) bridge.setModel(modelData.name); sheet.close(); }

                scale: down ? Theme.pressScale : 1
                Behavior on scale {
                    enabled: !Theme.reducedMotion
                    NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
                }

                background: GlassSurface {
                    radius: Theme.r2
                    solid: modelData.selected
                    glassEnabled: entry.hovered || entry.down || entry.visualFocus
                    tint: modelData.selected ? Theme.surfaceSelected
                          : entry.down ? Theme.glassTintStrong : Theme.glassTintHover
                    fillOpacity: modelData.selected ? 1.0
                               : entry.down ? 0.62
                               : entry.hovered ? 0.48
                               : entry.visualFocus ? 0.34 : 0.0
                    outlineVisible: modelData.selected || entry.visualFocus
                    strongEdge: entry.hovered || entry.down || entry.visualFocus
                    active: entry.visualFocus
                    sheen: entry.hovered || entry.down
                    edgeColor: entry.visualFocus ? Theme.accentEdge
                             : modelData.selected ? Theme.glassEdge : "transparent"
                }

                contentItem: RowLayout {
                    spacing: Theme.s3
                    Icon {
                        Layout.leftMargin: Theme.s3
                        name: modelData.selected ? "check" : "layers"
                        ink: modelData.selected ? Theme.accent : Theme.textMuted
                        Layout.preferredWidth: 16; Layout.preferredHeight: 16
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.s2
                            Text {
                                text: modelData.name
                                color: Theme.textPrimary
                                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                font.weight: modelData.selected ? Font.DemiBold : Font.Medium
                                Layout.maximumWidth: 280
                                elide: Text.ElideMiddle
                            }
                            Tag { visible: modelData.loaded; text: "in memory"; tone: Theme.success; fill: Theme.successMuted }
                            Tag { visible: modelData.recent && !modelData.selected; text: "recent" }
                            Item { Layout.fillWidth: true }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: [modelData.parameters, modelData.quantization, modelData.sizeLabel,
                                   modelData.selected && bridge ? bridge.modelContextLabel : "",
                                   modelData.selected && bridge ? bridge.modelCapabilitySummary : ""]
                                  .filter(function(part) { return !!part; }).join(" · ")
                            color: modelData.selected ? Theme.textSecondary : Theme.textMuted
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            elide: Text.ElideRight
                        }
                    }
                    Row {
                        Layout.rightMargin: Theme.s1
                        spacing: 0
                        opacity: entry.hovered || entry.visualFocus || modelData.favorite ? 1 : 0
                        visible: opacity > 0
                        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                        IconButton {
                            width: 30; height: 30; iconSize: 14
                            iconName: modelData.favorite ? "starFilled" : "star"
                            tooltip: modelData.favorite ? "Remove favourite" : "Mark as favourite"
                            tint: modelData.favorite ? Theme.accent : Theme.textSecondary
                            activeTint: modelData.favorite ? Theme.accent : Theme.textPrimary
                            onClicked: if (bridge) bridge.toggleFavoriteModel(entry.modelData.name)
                        }
                        IconButton {
                            width: 30; height: 30; iconSize: 14
                            iconName: "trash"; tooltip: "Delete from Ollama server"
                            enabled: !modelData.selected
                            onClicked: { sheet.pendingDelete = entry.modelData.name; confirmDelete.show(); }
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    anchors.rightMargin: 64
                    acceptedButtons: Qt.NoButton
                    cursorShape: Qt.PointingHandCursor
                }
            }

            Column {
                anchors.centerIn: parent
                width: parent.width - Theme.s7
                spacing: Theme.s2
                visible: list.count === 0
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: bridge && bridge.online ? "No models installed" : "Ollama is not connected"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.label
                }
                Text {
                    width: parent.width
                    text: bridge && bridge.online
                          ? "Download one below — gemma3:4b for chat, or a vision model such as qwen2.5vl:7b for screen control."
                          : "Check the Ollama server address in Settings, make sure Ollama is listening there, then refresh."
                    color: Theme.textMuted
                    horizontalAlignment: Text.AlignHCenter
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                    wrapMode: Text.WordWrap; lineHeight: 1.45
                }
            }
        }

        Divider { Layout.fillWidth: true }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            SectionLabel { text: "Download" }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.s2
                Field {
                    id: pullField
                    Layout.fillWidth: true
                    placeholderText: "Ollama model tag, e.g. gemma3:4b"
                    mono: true
                    enabled: bridge && !bridge.pulling
                    onAccepted: if (bridge && !bridge.pulling) bridge.pullModel(text)
                }
                WButton {
                    text: bridge && bridge.pulling ? "Stop" : "Download"
                    iconName: bridge && bridge.pulling ? "stop" : "download"
                    variant: bridge && bridge.pulling ? "secondary" : "primary"
                    enabled: bridge && bridge.online && !bridge.busy && (bridge.pulling || pullField.text.trim().length > 0)
                    onClicked: bridge && bridge.pulling ? bridge.cancelPull() : bridge.pullModel(pullField.text)
                }
            }
            Meter {
                Layout.fillWidth: true
                visible: bridge && bridge.pulling
                value: bridge ? bridge.pullPercent : 0
            }
            Text {
                Layout.fillWidth: true
                text: bridge && bridge.pullProgress
                      ? bridge.pullProgress
                      : bridge ? "Downloads go from Ollama's registry to your configured Ollama server · " + bridge.endpointScopeLabel
                               : "Downloads go to the configured Ollama server."
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                elide: Text.ElideRight
            }
        }
    }

    ConfirmSheet {
        id: confirmDelete
        title: "Delete this model?"
        message: sheet.pendingDelete + " will be removed from the configured Ollama server. You can download it again later."
        confirmText: "Delete"
        confirmVariant: "danger"
        onConfirmed: if (bridge) bridge.deleteModel(sheet.pendingDelete)
    }

    component Tag: Rectangle {
        property alias text: label.text
        property color tone: Theme.textMuted
        property color fill: Theme.surfaceHover
        implicitWidth: label.implicitWidth + Theme.s2
        implicitHeight: 17
        radius: Theme.r1
        color: fill
        Text {
            id: label
            anchors.centerIn: parent
            color: parent.tone
            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
        }
    }
}
