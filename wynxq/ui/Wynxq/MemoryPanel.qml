import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    What Wynxq remembers between tasks — the real memory.md, edited in place.

    Memory only earns trust if you can see it. This is the file itself, not a
    rendering of it: what the panel shows is what the next task reads, and an
    edit saved here is the same edit as opening the file in an editor. A note
    typed into the box below goes in the same way the model's own `remember`
    tool would put it there.

    Everything is explicit. Nothing is written while you are typing, an unsaved
    buffer says so, and Forget everything asks first — a memory that quietly
    changes underneath you is worse than no memory at all.
*/
Item {
    id: root

    readonly property bool memoryOn: !!(bridge && bridge.memoryEnabled)
    readonly property int count: bridge ? bridge.memoryCount : 0
    property string loaded: ""
    property bool dirty: false

    function reload() {
        if (!bridge) return;
        loaded = bridge.memoryText;
        editor.text = loaded;
        dirty = false;
    }

    function save() {
        if (!bridge || !dirty) return;
        bridge.saveMemory(editor.text);
        loaded = editor.text;
        dirty = false;
    }

    Component.onCompleted: root.reload()

    Connections {
        target: bridge
        // The model can write memory mid-turn. Take the new file unless the
        // user has unsaved edits in front of them — their typing wins.
        function onMemoryChanged() { if (!root.dirty) root.reload(); }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Memory"
            detail: root.dirty ? "unsaved" : (root.memoryOn ? root.count + (root.count === 1 ? " note" : " notes") : "off")
            detailFont: "mono"

            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "save"
                tooltip: "Save memory (Ctrl+S)"
                enabled: root.dirty && root.memoryOn
                onClicked: root.save()
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "retry"
                tooltip: "Re-read memory.md from disk"
                onClicked: { root.dirty = false; if (bridge) bridge.reloadMemory(); root.reload(); }
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "launch"
                tooltip: "Open memory.md outside Wynxq"
                onClicked: if (bridge) bridge.revealMemory()
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "trash"
                tooltip: "Forget everything"
                enabled: root.count > 0
                onClicked: forgetSheet.open()
            }
        }

        // Memory off is a state, not an error: the file stays exactly as it is
        // and simply stops being read, and the switch to turn it back on is here.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            visible: !root.memoryOn

            Rectangle {
                anchors.fill: parent
                color: Theme.surfaceHover
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: 1
                    color: Theme.borderSubtle
                }
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s2
                spacing: Theme.s2
                Icon { name: "info"; ink: Theme.textMuted; Layout.preferredWidth: 12; Layout.preferredHeight: 12 }
                Text {
                    Layout.fillWidth: true
                    text: "Memory is off. Nothing here is read into a task."
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                    elide: Text.ElideRight
                }
                WButton {
                    text: "Turn on"
                    variant: "ghost"
                    compactPadding: true
                    implicitHeight: 22
                    font.pixelSize: Theme.micro
                    onClicked: if (bridge) bridge.setMemoryEnabled(true)
                }
            }
        }

        // The file, once there is a file worth showing. Before that the panel
        // says what memory is for rather than offering an empty text box.
        Flickable {
            id: flick
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.count > 0 || root.dirty
            clip: true
            contentWidth: width
            contentHeight: editor.implicitHeight + Theme.s3 * 2
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: WScrollBar {
                policy: ScrollBar.AsNeeded
            }

            TextEdit {
                id: editor
                objectName: "memoryEditor"
                x: Theme.s3
                y: Theme.s3
                width: flick.width - Theme.s3 * 2
                color: Theme.textPrimary
                selectionColor: Theme.accent
                selectedTextColor: Theme.onAccent
                font.family: Theme.monoFamily
                font.pixelSize: Theme.code
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                persistentSelection: true
                Accessible.role: Accessible.EditableText
                Accessible.name: "Memory file"

                onTextChanged: root.dirty = (text !== root.loaded)
                Keys.onPressed: function(event) {
                    if (event.key === Qt.Key_S && (event.modifiers & Qt.ControlModifier)) {
                        root.save();
                        event.accepted = true;
                    }
                }
            }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !flick.visible
            iconName: "memory"
            title: "Nothing remembered yet"
            detail: "Tell Wynxq something worth keeping — “I deploy with Nix, never Docker” — and it carries into every later task, in Wynxq and Wynxi alike."
        }

        Divider { Layout.fillWidth: true }

        // Adding a note by hand is the same operation the model performs, so it
        // lands in the same section of the same file rather than in a side list.
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.s3
            spacing: Theme.s2

            Field {
                id: noteField
                Layout.fillWidth: true
                placeholderText: "Remember that…"
                onAccepted: addNote.clicked()
            }
            WButton {
                id: addNote
                text: "Remember"
                variant: "primary"
                compactPadding: true
                enabled: noteField.text.trim().length > 0
                onClicked: {
                    if (!bridge || noteField.text.trim().length === 0) return;
                    root.dirty = false;
                    bridge.rememberNote(noteField.text);
                    noteField.text = "";
                    root.reload();
                }
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.s3
            Layout.rightMargin: Theme.s3
            Layout.bottomMargin: Theme.s2
            text: root.memoryOn
                ? "Stable preferences can be learned automatically. Secrets and temporary details are skipped."
                : "Automatic learning is paused while Memory is off."
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
            wrapMode: Text.WordWrap
        }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.s3
            Layout.rightMargin: Theme.s3
            Layout.bottomMargin: Theme.s3
            text: bridge ? bridge.memoryPath : ""
            color: Theme.textDisabled
            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
            elide: Text.ElideLeft
        }
    }

    ConfirmSheet {
        id: forgetSheet
        title: "Forget everything?"
        message: "Every note Wynxq has saved is removed. Tasks already in your history are not touched."
        detail: bridge ? bridge.memoryPath : ""
        confirmText: "Forget everything"
        confirmVariant: "danger"
        onConfirmed: {
            if (!bridge) return;
            root.dirty = false;
            bridge.clearMemory();
            root.reload();
        }
    }
}
