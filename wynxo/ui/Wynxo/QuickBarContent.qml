import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A compact handoff into the current task.

    The bar deliberately keeps the current task mode instead of pretending to
    be a separate chat session. Make that boundary visible: Chat stays
    tool-free; Work keeps its project and tool permissions.
*/
Item {
    id: root
    signal submitted(string text)
    signal expandRequested()
    signal dismissed()

    property string answer: ""
    property bool answering: false
    readonly property string mode: bridge ? bridge.taskMode : "chat"
    readonly property bool workMode: root.mode === "work"

    function focusInput() { input.forceActiveFocus(); input.selectAll(); }
    function reset() { input.text = ""; answer = ""; }

    implicitHeight: shell.height

    // The quick bar is transient chrome, so it gets the richer material that
    // permanent work surfaces intentionally avoid.
    GlassSurface {
        id: shell
        width: parent.width
        height: column.implicitHeight + Theme.s3 * 2
        radius: Theme.r3
        solid: false
        autoGlass: false
        glassEnabled: true
        tint: Theme.glassTintStrong
        fillOpacity: Theme.glassStrongOpacity
        elevated: true
        strongEdge: true
        sheen: true
        edgeColor: Theme.glassEdgeStrong

        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: Theme.s3
            spacing: Theme.s3

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.s3

                Mark { Layout.preferredWidth: 20; Layout.preferredHeight: 20; Layout.leftMargin: Theme.s1 }

                TextField {
                    id: input
                    Layout.fillWidth: true
                    placeholderText: root.workMode
                        ? "Give the current Work task an instruction…"
                        : "Ask the current Chat task…"
                    placeholderTextColor: Theme.textMuted
                    color: Theme.textPrimary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.title
                    background: Item {}
                    Accessible.name: root.workMode
                        ? "Instruction for the current Work task"
                        : "Message for the current Chat task"
                    Accessible.description: root.workMode
                        ? "This task may use project, command, or desktop tools according to its permissions."
                        : "This task is conversation only and has no local tools."
                    onAccepted: root.send()
                    Keys.onEscapePressed: root.dismissed()
                }

                IconButton {
                    id: sendButton
                    iconName: root.answering ? "stop" : "arrow"
                    tooltip: root.answering ? "Stop" : "Send to current task"
                    width: 32; height: 32; iconSize: 15
                    tint: root.answering ? Theme.textPrimary : Theme.onAccent
                    activeTint: tint
                    enabled: root.answering || input.text.trim().length > 0
                    onClicked: root.answering ? (bridge && bridge.stop()) : root.send()
                    background: GlassSurface {
                        radius: Theme.r2
                        solid: true
                        autoGlass: false
                        glassEnabled: sendButton.enabled
                            && (sendButton.hovered || sendButton.down || sendButton.visualFocus || root.answering)
                        tint: root.answering ? Theme.glassTintStrong
                             : sendButton.enabled
                               ? (sendButton.hovered ? Theme.accentHover : Theme.accent)
                               : Theme.surfaceRaised
                        fillOpacity: root.answering ? 0.82
                                   : sendButton.enabled ? 0.94 : 1.0
                        strongEdge: sendButton.enabled && (sendButton.hovered || sendButton.visualFocus)
                        active: sendButton.visualFocus
                        sheen: sendButton.enabled && (sendButton.hovered || sendButton.visualFocus)
                        edgeColor: sendButton.visualFocus ? Theme.accentEdge
                                 : sendButton.enabled ? Theme.glassEdgeStrong : Theme.borderSubtle
                    }
                }
            }

            // Kept for the inline-answer path so the component can display a
            // response without growing into a full window when that path is
            // used by the shell.
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: root.answer.length ? Math.min(answerText.implicitHeight + Theme.s3 * 2, 220) : 0
                visible: root.answer.length > 0
                radius: Theme.r2
                color: Theme.surfaceSunken
                clip: true
                Flickable {
                    anchors.fill: parent
                    anchors.margins: Theme.s3
                    contentWidth: width
                    contentHeight: answerText.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: WScrollBar {}
                    TextEdit {
                        id: answerText
                        width: parent.width
                        text: root.answer
                        readOnly: true; selectByMouse: true
                        wrapMode: TextEdit.Wrap
                        color: Theme.textSecondary
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.onAccent
                        font.family: Theme.sansFamily; font.pixelSize: Theme.label
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.s2
                Chip {
                    text: root.workMode ? "Work" : "Chat"
                    iconName: root.workMode ? "cursor" : "chat"
                    selected: true
                    interactive: false
                    ToolTip.visible: hovered
                    ToolTip.text: root.workMode
                        ? "Sends to the current Work task, including its tool permissions"
                        : "Sends to the current tool-free Chat task"
                }
                Chip {
                    text: "Screen"; iconName: "camera"
                    onClicked: if (bridge) bridge.attachScreenshot()
                }
                Chip {
                    text: "Window"; iconName: "window"
                    onClicked: if (bridge) bridge.attachWindow()
                }
                Chip {
                    text: "File"; iconName: "file"
                    onClicked: if (bridge) bridge.attachFile()
                }
                Repeater {
                    model: bridge ? bridge.attachments : []
                    delegate: Chip {
                        required property var modelData
                        text: modelData.title
                        iconName: ContextKinds.icon(modelData.kind)
                        removable: true
                        interactive: false
                        selected: true
                        Layout.maximumWidth: 180
                        onRemoved: if (bridge) bridge.removeAttachment(modelData.id)
                    }
                }
                Item { Layout.fillWidth: true }
                Chip {
                    text: "Open Wynxq GUI"; iconName: "launch"
                    onClicked: root.expandRequested()
                }
            }
        }
    }

    function send() {
        var text = input.text.trim();
        if (!text || root.answering) return;
        root.answer = "";
        root.submitted(text);
        input.text = "";
    }
}
