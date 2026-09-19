import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* Model settings page. Kept separate from the SettingsSheet navigation shell. */
Column {
    required property var bridge
    required property var hostSheet

    spacing: Theme.s6
    SettingsGroup {
        title: "Current chat model"
        description: "This chat's model. Server + model switching lives together in the composer picker; the server default for new chats is managed under General."
        Row {
            spacing: Theme.s3
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: bridge ? bridge.model : ""
                color: Theme.textPrimary
                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                font.weight: Font.Medium
            }
            WButton {
                anchors.verticalCenter: parent.verticalCenter
                text: "Manage models"
                iconName: "layers"
                onClicked: { hostSheet.close(); hostSheet.openModelManager(); }
            }
        }
        Text {
            width: parent.width
            text: bridge ? bridge.modelCapabilityHint : ""
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }
    }
    SettingsGroup {
        title: "Speed"
        description: bridge ? bridge.runtimeHint : ""
        Segmented {
            width: Math.min(parent.width, 400)
            options: [
                { id: "Fast", label: "Fast", detail: "Low latency" },
                { id: "Balanced", label: "Balanced", detail: "Everyday default" },
                { id: "Deep", label: "Deep", detail: "More context and reasoning" },
                { id: "Custom", label: "Custom", detail: "Your own values" },
            ]
            current: bridge ? bridge.runtimePreset : "Balanced"
            onSelected: function(value) {
                if (value === "Custom" || !bridge) return;
                bridge.applyRuntimePreset(value);
                ctxField.text = bridge.numCtx; tempField.text = bridge.temperature;
                keepField.text = bridge.keepAlive; stepsField.text = bridge.maxSteps;
            }
        }
        Toggle {
            width: parent.width
            text: "Let the model think before answering"
            description: "Uses the model's reasoning mode where Ollama reports support for it."
            checked: bridge ? bridge.thinking : false
            onSwitched: function(value) { if (bridge) bridge.setFlag("think", value); }
        }
    }
    SettingsDisclosure {
        width: parent.width
        title: "Advanced generation options"
        hint: "Ollama options. Saving these switches the preset to Custom."
        Grid {
            id: advancedGrid
            width: parent.width
            columns: width > 460 ? 2 : 1
            columnSpacing: Theme.s3
            rowSpacing: Theme.s3
            property real cellWidth: columns === 2 ? (width - columnSpacing) / 2 : width

            Column {
                width: advancedGrid.cellWidth
                spacing: Theme.s2
                SettingsFieldLabel { text: "Context tokens" }
                Field { id: ctxField; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly }
            }
            Column {
                width: advancedGrid.cellWidth
                spacing: Theme.s2
                SettingsFieldLabel { text: "Temperature" }
                Field { id: tempField; width: parent.width }
            }
            Column {
                width: advancedGrid.cellWidth
                spacing: Theme.s2
                SettingsFieldLabel { text: "Keep model loaded" }
                Field { id: keepField; width: parent.width; placeholderText: "5m" }
            }
            Column {
                width: advancedGrid.cellWidth
                spacing: Theme.s2
                SettingsFieldLabel { text: "Desktop action budget" }
                Field { id: stepsField; width: parent.width; inputMethodHints: Qt.ImhDigitsOnly }
            }
        }
        WButton {
            text: "Save runtime settings"
            variant: "primary"
            enabled: bridge && !bridge.busy
            onClicked: if (bridge) bridge.saveRuntimeSettings(ctxField.text, tempField.text,
                                                             keepField.text, stepsField.text)
        }
    }
}
