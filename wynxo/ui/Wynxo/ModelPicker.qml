import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Choosing what runs, and how fast — the only place either is set.

    Everyday switching is a short list of what you actually use. Downloading,
    deleting and inspecting models is a different job and lives in the model
    manager, one click below.
*/
AbstractButton {
    id: button
    signal openModelManager()
    // Set by the surface that hosts the button; it knows how much room it has.
    property bool compact: false
    // Preview scenes replace the bridge object in-place. Closing an anchored
    // picker on that controller swap also prevents a stale popup from surviving
    // a workspace/account reset in any host that rebinds the controller.
    property var controllerIdentity: bridge
    onControllerIdentityChanged: if (popover.opened) popover.close()

    // The handful worth showing without a search box: current, favourites,
    // then recents, in the order the catalogue already ranks them.
    readonly property int shortlistLength: 6
    readonly property var currentEntry: {
        var catalog = bridge ? bridge.modelCatalog : [];
        for (var i = 0; i < catalog.length; i++)
            if (catalog[i].selected || catalog[i].name === bridge.model) return catalog[i];
        return ({});
    }
    readonly property bool modelLoaded: !!currentEntry.loaded
    readonly property var shortlist: {
        var catalog = bridge ? bridge.modelCatalog : [];
        var out = [];
        for (var i = 0; i < catalog.length && out.length < shortlistLength; i++)
            if (catalog[i].chat) out.push(catalog[i]);
        return out;
    }

    implicitHeight: Theme.controlSmall
    implicitWidth: row.implicitWidth + Theme.s2 * 2
    hoverEnabled: true
    Accessible.name: "Model: " + (bridge ? bridge.model : "none") + ". Change model and speed"
    onClicked: popover.opened ? popover.close() : popover.open()
    function showPicker() { popover.open(); }
    ToolTip.visible: hovered && !popover.opened
    ToolTip.text: !bridge ? ""
        : !bridge.online ? "Ollama offline · click to inspect"
        : (button.modelLoaded ? "Loaded · " : "Ready · ") + bridge.modelCapabilitySummary
    ToolTip.delay: 500

    background: Rectangle {
        radius: Theme.r2
        color: button.hovered || popover.opened ? Theme.surfaceHover : "transparent"
        border.width: button.visualFocus ? 2 : 0
        border.color: Theme.accentEdge
        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
    }

    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: Theme.s2
            StatusDot {
                width: 6; height: 6
                tone: !bridge || !bridge.online ? Theme.danger
                    : button.modelLoaded ? Theme.success : Theme.textMuted
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: !bridge ? "No model"
                    : button.compact ? bridge.modelShortName : bridge.model
                color: button.hovered || popover.opened ? Theme.textPrimary : Theme.textSecondary
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                anchors.verticalCenter: parent.verticalCenter
                elide: Text.ElideMiddle
                width: Math.min(implicitWidth, 190)
            }
            Icon {
                name: "down"; ink: Theme.textMuted; width: 11; height: 11
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }

    Popover {
        id: popover
        width: 320
        preferredEdge: "above"
        anchorX: -width + button.width
        implicitHeight: column.implicitHeight + Theme.s4 * 2

        ColumnLayout {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            spacing: Theme.s3

            SectionLabel { text: "Model" }
            Item { Layout.fillWidth: true }
            // Where inference runs is the one fact a local-first app should
            // never make you go looking for.
            Text {
                text: bridge ? "Ollama · " + bridge.endpointScopeLabel.toLowerCase() : ""
                color: Theme.textDisabled
                font.family: Theme.sansFamily
                font.pixelSize: Theme.micro
            }

            Text {
                Layout.fillWidth: true
                visible: !(bridge && bridge.online)
                text: "Ollama is not connected, so the installed models are unknown."
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                wrapMode: Text.WordWrap; lineHeight: 1.4
            }

            Repeater {
                model: button.shortlist
                delegate: AbstractButton {
                    id: entry
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 40
                    hoverEnabled: true
                    Accessible.name: modelData.name
                    Accessible.checked: modelData.selected
                    onClicked: { if (bridge) bridge.setModel(modelData.name); popover.close(); }

                    background: Rectangle {
                        radius: Theme.r2
                        color: entry.hovered ? Theme.surfaceHover
                             : modelData.selected ? Theme.surfaceSelected : "transparent"
                        border.width: entry.visualFocus ? 2 : 0
                        border.color: Theme.accentEdge
                        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
                    }
                    contentItem: RowLayout {
                        spacing: Theme.s3
                        Icon {
                            Layout.leftMargin: Theme.s2
                            name: modelData.selected ? "check" : "layers"
                            ink: modelData.selected ? Theme.accent : Theme.textMuted
                            Layout.preferredWidth: 14; Layout.preferredHeight: 14
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                Layout.fillWidth: true
                                text: modelData.name
                                color: Theme.textPrimary
                                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                font.weight: modelData.selected ? Font.DemiBold : Font.Normal
                                elide: Text.ElideMiddle
                            }
                            Text {
                                Layout.fillWidth: true
                                text: [modelData.parameters, modelData.quantization, modelData.sizeLabel]
                                      .filter(function(part) { return !!part; }).join(" · ")
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            Layout.rightMargin: Theme.s2
                            visible: modelData.loaded
                            text: "loaded"
                            color: Theme.success
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                        }
                    }
                    MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                }
            }

            // What the current model can do, so the choice is informed rather
            // than a name whose properties you have to remember.
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.s2
                spacing: Theme.s2
                visible: bridge && bridge.online
                Text {
                    visible: bridge && bridge.modelCapabilitiesLoading
                    text: "Checking what this model can do…"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                }
                Repeater {
                    model: !bridge || bridge.modelCapabilitiesLoading ? [] :
                           ["Chat"].concat(bridge.modelSupportsTools ? ["Tools"] : [])
                                   .concat(bridge.modelSupportsVision ? ["Vision"] : [])
                                   .concat(bridge.modelSupportsThinking ? ["Thinking"] : [])
                    delegate: Rectangle {
                        required property string modelData
                        implicitWidth: capability.implicitWidth + Theme.s2
                        implicitHeight: 18
                        radius: Theme.r1
                        color: Theme.surfaceHover
                        Text {
                            id: capability
                            anchors.centerIn: parent
                            text: modelData
                            color: Theme.textSecondary
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                        }
                    }
                }
                Item { Layout.fillWidth: true }
            }

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.s2
                visible: bridge && bridge.modelCapabilityHint !== ""
                text: bridge ? bridge.modelCapabilityHint : ""
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                wrapMode: Text.WordWrap; lineHeight: 1.4
            }

            WButton {
                Layout.fillWidth: true
                text: "Manage models…"
                iconName: "layers"
                variant: "ghost"
                implicitHeight: Theme.controlSmall
                onClicked: { popover.close(); button.openModelManager(); }
                ToolTip.visible: hovered
                ToolTip.text: "Download, delete and inspect · Ctrl+M"
            }

            Divider { Layout.fillWidth: true; Layout.topMargin: Theme.s1 }

            SectionLabel { Layout.fillWidth: true; text: "Speed" }
            Segmented {
                Layout.fillWidth: true
                implicitHeight: Theme.controlSmall
                options: [
                    { id: "Fast", label: "Fast", detail: "Short context, answers start sooner" },
                    { id: "Balanced", label: "Balanced", detail: "The everyday default" },
                    { id: "Deep", label: "Deep", detail: "Long context and a bigger action budget" },
                ]
                current: bridge ? bridge.runtimePreset : "Balanced"
                onSelected: function(value) { if (bridge) bridge.applyRuntimePreset(value); }
            }
            Text {
                Layout.fillWidth: true
                text: bridge ? bridge.runtimeSummary : ""
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.micro
            }
        }
    }
}