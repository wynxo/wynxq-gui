import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A real terminal, not an animation of one.

    The panel is a view onto a PTY-backed shell: `cd` persists, prompts appear,
    Ctrl+C reaches the foreground process. Output is rendered as styled rows so
    a build log keeps its colour, and the header states the shell and the
    directory the shell is actually in — read from the process, not remembered
    from when it started.
*/
Item {
    id: root
    signal revealDirectory(string path)
    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property bool live: !!(dock && dock.terminalRunning)

    function focusInput() { entry.forceActiveFocus(); }

    Component.onCompleted: if (dock) dock.setTerminalPalette(Theme.terminalPalette)
    Connections {
        target: Theme
        function onAccentChanged() { if (root.dock) root.dock.setTerminalPalette(Theme.terminalPalette); }
    }

    // Keep the shell's idea of the window in step with the panel's, so wrapping
    // and full-screen programs line up with what is on screen.
    readonly property int columns: Math.max(20, Math.floor((width - Theme.s3 * 2) / Math.max(1, glyph.width)))
    readonly property int visibleRows: Math.max(5, Math.floor(output.height / Math.max(1, glyph.height)))
    onColumnsChanged: resize.restart()
    onVisibleRowsChanged: resize.restart()
    Timer {
        id: resize
        interval: 120
        onTriggered: if (root.dock) root.dock.resizeTerminal(root.columns, root.visibleRows)
    }

    TextMetrics {
        id: glyph
        font.family: Theme.monoFamily
        font.pixelSize: Theme.code
        text: "M"
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Terminal"
            detail: root.dock
                ? (root.dock.terminalShell ? root.dock.terminalShell + "  " : "")
                  + root.dock.terminalDirectoryLabel
                : ""
            detailFont: "mono"
            detailElide: Text.ElideLeft

            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "folderOpen"
                tooltip: "Show this folder in Files"
                enabled: !!(root.dock && root.dock.terminalDirectory)
                onClicked: if (root.dock) root.revealDirectory(root.dock.terminalDirectory)
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "stop"
                tooltip: "Interrupt the running command"
                shortcut: "Ctrl+C"
                enabled: root.live
                onClicked: if (root.dock) root.dock.interruptTerminal()
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "copy"
                tooltip: "Copy all output"
                onClicked: if (bridge && root.dock) bridge.copyText(root.dock.terminalText())
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "clock"
                tooltip: "Clear command history"
                enabled: entry.history.length > 0
                onClicked: {
                    entry.history = [];
                    entry.historyCursor = -1;
                    entry.historyDraft = "";
                }
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "trash"
                tooltip: "Clear output"
                onClicked: if (root.dock) root.dock.clearTerminal()
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "retry"
                tooltip: root.live ? "Restart the shell" : "Start a shell"
                onClicked: if (root.dock) root.dock.restartTerminal()
            }
        }

        // ------------------------------------------------------ scrollback
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.surfaceSunken
            clip: true

            ListView {
                id: output
                objectName: "terminalOutput"
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s2
                topMargin: Theme.s2
                bottomMargin: Theme.s2
                model: root.dock ? root.dock.terminalModel : null
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                cacheBuffer: 800
                clip: true
                property bool following: true

                onMovementStarted: following = false
                onMovementEnded: following = atYEnd
                onCountChanged: if (following) Qt.callLater(positionViewAtEnd)
                onContentHeightChanged: if (following) positionViewAtEnd()

                ScrollBar.vertical: WScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                // An Item wraps the row so the model's `text` role cannot
                // collide with the Text element's own `text` property.
                delegate: Item {
                    required property string html
                    width: output.width
                    height: glyph.height

                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        // Spans are rendered in Python against
                        // Theme.terminalPalette, so ANSI keeps its meaning.
                        text: parent.html
                        textFormat: Text.StyledText
                        color: Theme.textSecondary
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.code
                        elide: Text.ElideNone
                        clip: true
                    }
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: !!(root.dock && root.dock.terminalError)
                iconName: "warning"
                tone: true
                title: "The shell did not start"
                detail: root.dock ? root.dock.terminalError : ""
                actionText: "Try again"
                onActionInvoked: if (root.dock) root.dock.restartTerminal()
            }

            EmptyState {
                anchors.fill: parent
                visible: !!(root.dock && !root.dock.terminalStarted && !root.dock.terminalError)
                iconName: "terminal"
                title: "No shell running"
                detail: "Start one in the project folder and it stays open for the session."
                actionText: "Start shell"
                onActionInvoked: if (root.dock) root.dock.startTerminal()
            }

            // Jump back to the newest output once you have scrolled away.
            AbstractButton {
                id: tail
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Theme.s3
                implicitHeight: 24
                implicitWidth: tailRow.implicitWidth + Theme.s3 * 2
                hoverEnabled: true
                opacity: !output.following && output.count > 0 ? 1 : 0
                visible: opacity > 0
                Accessible.name: "Jump to the newest output"
                onClicked: { output.following = true; output.positionViewAtEnd(); }
                Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                background: GlassSurface {
                    radius: Theme.rPill
                    solid: false
                    glassEnabled: tail.hovered || tail.down
                    tint: tail.down ? Theme.glassTintStrong : Theme.glassTintHover
                    fillOpacity: tail.down ? 0.72 : tail.hovered ? 0.56 : 0.0
                    outlineVisible: tail.hovered || tail.down
                    sheen: tail.hovered || tail.down
                }
                contentItem: Row {
                    id: tailRow
                    anchors.centerIn: parent
                    spacing: Theme.s2
                    Icon { name: "down"; ink: Theme.textSecondary; width: 11; height: 11; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: "Newest"
                        color: Theme.textSecondary
                        font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }

        // ------------------------------------------------------ the prompt
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.control + Theme.s2
            color: Theme.backgroundSoft
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1; color: Theme.borderSubtle
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s2
                anchors.topMargin: Theme.s1
                spacing: Theme.s2

                Icon {
                    Layout.preferredWidth: 11; Layout.preferredHeight: 11
                    name: "chevronRight"
                    ink: root.live ? Theme.accent : Theme.textDisabled
                    weight: 2.2
                }

                TextField {
                    id: entry
                    objectName: "terminalInput"
                    Layout.fillWidth: true
                    placeholderText: root.live ? "Run a command" : "Start the shell to run a command"
                    placeholderTextColor: Theme.textDisabled
                    color: Theme.textPrimary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.code
                    leftPadding: 0; rightPadding: 0
                    background: Item {}
                    selectByMouse: true
                    Accessible.role: Accessible.EditableText
                    Accessible.name: "Terminal command"

                    property var history: []
                    property int historyCursor: -1
                    property string historyDraft: ""

                    onTextEdited: {
                        if (historyCursor < 0) historyDraft = text;
                    }

                    onAccepted: {
                        if (!root.dock) return;
                        var command = text;
                        // An empty Enter still belongs to the shell: it draws a
                        // fresh prompt, exactly as pressing Enter always does.
                        root.dock.sendTerminal(command);
                        if (command.trim().length) {
                            history = [command].concat(history.filter(function (item) { return item !== command; })).slice(0, 100);
                        }
                        historyCursor = -1;
                        historyDraft = "";
                        text = "";
                        output.following = true;
                    }

                    // Preserve whatever the user was typing before walking the
                    // history. The old implementation replaced that draft with
                    // an empty string when Down returned to the newest entry.
                    Keys.onUpPressed: {
                        if (!history.length) return;
                        if (historyCursor < 0) historyDraft = text;
                        if (historyCursor + 1 < history.length) {
                            historyCursor++;
                            text = history[historyCursor];
                            cursorPosition = length;
                        }
                    }
                    Keys.onDownPressed: {
                        if (historyCursor > 0) {
                            historyCursor--;
                            text = history[historyCursor];
                            cursorPosition = length;
                        } else if (historyCursor === 0) {
                            historyCursor = -1;
                            text = historyDraft;
                            cursorPosition = length;
                        }
                    }
                    Keys.onPressed: function(event) {
                        if (!(event.modifiers & Qt.ControlModifier) || !root.dock) return;
                        if ((event.modifiers & Qt.ShiftModifier) && event.key === Qt.Key_C) {
                            if (bridge) bridge.copyText(root.dock.terminalText());
                            event.accepted = true;
                        } else if (event.key === Qt.Key_C) {
                            if (selectedText.length) return;       // copying, not interrupting
                            root.dock.interruptTerminal();
                            text = "";
                            historyCursor = -1;
                            historyDraft = "";
                            event.accepted = true;
                        } else if (event.key === Qt.Key_D) {
                            root.dock.writeTerminal("\u0004");
                            event.accepted = true;
                        } else if (event.key === Qt.Key_L) {
                            root.dock.clearTerminal();
                            event.accepted = true;
                        }
                    }
                }

                Text {
                    visible: root.dock && !root.live && root.dock.terminalStarted
                    text: "exited"
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                }
                StatusDot {
                    visible: root.live
                    width: 6; height: 6
                    tone: Theme.success
                }
            }
        }
    }
}
