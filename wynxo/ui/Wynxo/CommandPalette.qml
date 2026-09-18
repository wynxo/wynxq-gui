import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The home of everything that does not deserve a button.

    Grouped, filtered as you type, and driven entirely from the keyboard. If an
    action lives here and nowhere else, that is usually the right answer.
*/
Sheet {
    id: palette
    width: Math.min(600, parent ? parent.width - Theme.s7 : 600)
    height: Math.min(480, parent ? parent.height - Theme.s7 : 480)
    signal invoked(string action)

    readonly property bool workMode: !!(bridge && bridge.taskMode === "work")
    readonly property var commands: [
        { id: "new", group: "Task", label: "New task", detail: "Start a fresh task", icon: "plus", shortcut: "Ctrl+N" },
        { id: "newwork", group: "Task", label: "New Work task", detail: "Project, command and desktop tools", icon: "cursor" },
        { id: "compose", group: "Task", label: "Focus the composer", icon: "edit" },
        { id: "search", group: "Task", label: "Search tasks", detail: "Titles and message text", icon: "search", shortcut: "Ctrl+K" },
        { id: "next", group: "Task", label: "Next task", icon: "down", shortcut: "Alt+Down" },
        { id: "previous", group: "Task", label: "Previous task", icon: "up", shortcut: "Alt+Up" },
        { id: "regenerate", group: "Task", label: "Regenerate response", icon: "retry", shortcut: "Ctrl+R" },
        { id: "stop", group: "Task", label: "Stop", detail: "Cancel generation and desktop actions", icon: "stop", shortcut: "Esc" },
        { id: "duplicate", group: "Task", label: "Duplicate task", icon: "duplicate", shortcut: "Ctrl+D" },
        { id: "pin", group: "Task", label: "Pin or unpin task", icon: "pin" },
        { id: "export", group: "Task", label: "Export task to Markdown", icon: "download" },
        { id: "clear", group: "Task", label: "Clear messages", detail: "Empty this task but keep it", icon: "trash" },

        { id: "files", group: "Workspace", label: "Files", detail: "The project tree and file viewer", icon: "folder", shortcut: "Ctrl+Shift+E", workOnly: true },
        { id: "terminal-panel", group: "Workspace", label: "Terminal", detail: "A real shell in the project", icon: "terminal", shortcut: "Ctrl+`", workOnly: true },
        { id: "changes", group: "Workspace", label: "Changes", detail: "Uncommitted work, and its diff", icon: "branch", shortcut: "Ctrl+Shift+G", workOnly: true },
        { id: "context", group: "Workspace", label: "Context", detail: "What the model can see", icon: "layers", shortcut: "Ctrl+Shift+K", workOnly: true },
        { id: "memory", group: "Workspace", label: "Memory", detail: "What Wynxq GUI remembers between tasks", icon: "memory", shortcut: "Ctrl+Shift+M", workOnly: true },
        { id: "activity", group: "Workspace", label: "Activity", detail: "The full run timeline", icon: "bolt", shortcut: "Ctrl+Shift+A", workOnly: true },
        { id: "browser", group: "Workspace", label: "Browser", detail: "Read a page beside the task", icon: "globe", shortcut: "Ctrl+Shift+W", workOnly: true },
        { id: "preview", group: "Workspace", label: "Preview", detail: "Images and captures, full size", icon: "image", shortcut: "Ctrl+Shift+U", workOnly: true },
        { id: "dock", group: "Workspace", label: "Show or hide the workspace dock", icon: "panel", shortcut: "Ctrl+Shift+B", workOnly: true },

        { id: "project", group: "Project", label: "Open a project folder…", icon: "folder" },
        { id: "reveal", group: "Project", label: "Reveal project in file manager", icon: "launch" },
        { id: "terminal", group: "Project", label: "Open a terminal in the project", icon: "terminal" },
        { id: "copypath", group: "Project", label: "Copy project path", icon: "copy" },

        { id: "file", group: "Context", label: "Attach a file…", icon: "file" },
        { id: "folder", group: "Context", label: "Attach a folder…", icon: "folder" },
        { id: "screenshot", group: "Context", label: "Capture the screen", icon: "camera" },
        { id: "window", group: "Context", label: "Capture the active window", icon: "window" },
        { id: "region", group: "Context", label: "Capture a screen region…", icon: "crop" },
        { id: "clipboard", group: "Context", label: "Attach the clipboard", icon: "clipboard" },

        { id: "models", group: "Setup", label: "Manage models", detail: "Download, delete, inspect", icon: "layers", shortcut: "Ctrl+M" },
        { id: "desktop", group: "Setup", label: "Toggle screen control", icon: "cursor" },
        { id: "permission", group: "Setup", label: "Change permission mode", detail: "Ask, safe auto, or auto", icon: "shield" },
        { id: "reconnect", group: "Setup", label: "Reconnect to Ollama", icon: "bolt" },
        { id: "quickbar", group: "Setup", label: "Open the quick bar", icon: "command", shortcut: "Ctrl+Space" },
        { id: "sidebar", group: "Setup", label: "Show or hide the sidebar", icon: "panelLeft", shortcut: "Ctrl+B" },
        { id: "shortcuts", group: "Setup", label: "Keyboard shortcuts", icon: "keyboard" },
        { id: "settings", group: "Setup", label: "Settings", icon: "sliders", shortcut: "Ctrl+," },
    ]

    // A flat list of commands. The first of each group draws its own heading,
    // so the keyboard never has to step over rows it cannot choose.
    property var filtered: []
    property int highlighted: 0

    // A subsequence match, scored. `otm` finds "Open a terminal", and an exact
    // prefix still wins over a scattered one.
    function score(haystack, needle) {
        if (!needle) return 1;
        var at = haystack.indexOf(needle);
        if (at === 0) return 1000;
        if (at > 0) return 700 - at + (haystack.charAt(at - 1) === " " ? 120 : 0);
        var position = 0, points = 0, previous = -2;
        for (var i = 0; i < needle.length; i++) {
            var found = haystack.indexOf(needle.charAt(i), position);
            if (found < 0) return 0;
            points += found === previous + 1 ? 12 : 4;
            if (found === 0 || haystack.charAt(found - 1) === " ") points += 18;
            previous = found;
            position = found + 1;
        }
        return points;
    }

    function refilter() {
        var needle = search.text.toLowerCase().trim();
        var scored = [];
        for (var i = 0; i < commands.length; i++) {
            var item = commands[i];
            // Chat deliberately has no workspace dock. Do not advertise
            // commands that the shell will refuse as no-ops in that mode.
            if (item.workOnly && !palette.workMode)
                continue;
            var label = item.label.toLowerCase();
            var points = score(label, needle);
            if (!points) {
                // The detail and the group still match, at a lower weight, so
                // "diff" finds Changes without putting it above a title match.
                points = score(((item.detail || "") + " " + item.group).toLowerCase(), needle);
                points = points ? Math.min(points, 240) : 0;
            }
            if (points) scored.push({ command: item, points: points, order: i });
        }
        // Searching ranks by score; an empty query keeps the authored order and
        // its group headings, because that list is a menu, not a result set.
        if (needle) scored.sort(function (a, b) { return b.points - a.points || a.order - b.order; });
        var out = [];
        var seen = "";
        for (var j = 0; j < scored.length; j++) {
            var command = scored[j].command;
            var heading = needle ? "" : (command.group === seen ? "" : command.group);
            out.push({ command: command, heading: heading });
            seen = command.group;
        }
        filtered = out;
        highlighted = 0;
    }

    function move(step) {
        if (!filtered.length) return;
        highlighted = Math.max(0, Math.min(filtered.length - 1, highlighted + step));
    }

    function run() {
        if (highlighted < 0 || highlighted >= filtered.length) return;
        invoked(filtered[highlighted].command.id);
        close();
    }

    onOpened: { search.text = ""; refilter(); search.forceActiveFocus(); }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.s3
        spacing: Theme.s2

        Field {
            id: search
            Layout.fillWidth: true
            implicitHeight: 42
            iconName: "search"
            placeholderText: "Search commands…"
            font.pixelSize: Theme.body
            onTextChanged: palette.refilter()
            Keys.onDownPressed: palette.move(1)
            Keys.onUpPressed: palette.move(-1)
            Keys.onReturnPressed: palette.run()
            Keys.onEnterPressed: palette.run()
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 1
            model: palette.filtered
            currentIndex: palette.highlighted
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: WScrollBar { policy: ScrollBar.AsNeeded }
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)

            delegate: Item {
                id: entryRow
                required property var modelData
                required property int index
                readonly property var command: modelData.command
                readonly property bool on: index === palette.highlighted
                width: list.width
                height: heading.height + 38

                SectionLabel {
                    id: heading
                    x: Theme.s3
                    width: parent.width - Theme.s3 * 2
                    height: text === "" ? 0 : 26
                    visible: height > 0
                    verticalAlignment: Text.AlignBottom
                    bottomPadding: 5
                    text: entryRow.modelData.heading
                }

                GlassSurface {
                    anchors.top: heading.bottom
                    width: parent.width
                    height: 38
                    radius: Theme.r2
                    solid: entryRow.on
                    glassEnabled: entryRow.on
                    tint: Theme.surfaceSelected
                    fillOpacity: entryRow.on ? 1.0 : 0.0
                    outlineVisible: entryRow.on
                    strongEdge: entryRow.on
                    sheen: entryRow.on
                    edgeColor: entryRow.on ? Theme.glassEdgeStrong : "transparent"

                    Rectangle {
                        // Shape as well as colour, so the keyboard position is
                        // obvious without relying on a background tint alone.
                        anchors.verticalCenter: parent.verticalCenter
                        width: 2
                        height: entryRow.on ? 16 : 0
                        radius: 1
                        color: Theme.accent
                        Behavior on height { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.s3
                        anchors.rightMargin: Theme.s2
                        spacing: Theme.s3
                        Icon {
                            name: entryRow.command.icon || "chat"
                            ink: entryRow.on ? Theme.accent : Theme.textMuted
                            Layout.preferredWidth: 15; Layout.preferredHeight: 15
                        }
                        Text {
                            text: entryRow.command.label || ""
                            color: Theme.textPrimary
                            font.family: Theme.sansFamily; font.pixelSize: Theme.label
                            elide: Text.ElideRight
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: !!entryRow.command.detail && entryRow.width > 430
                            text: entryRow.command.detail || ""
                            // Muted text does not carry enough contrast on the
                            // highlighted surface, so the active row steps up.
                            color: entryRow.on ? Theme.textSecondary : Theme.textMuted
                            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                            elide: Text.ElideRight
                        }
                        Item { Layout.fillWidth: true; visible: !(!!entryRow.command.detail && entryRow.width > 430) }
                        KeyHint { keys: entryRow.command.shortcut || "" }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: palette.highlighted = entryRow.index
                        onClicked: { palette.invoked(entryRow.command.id); palette.close(); }
                    }
                }

                Accessible.role: Accessible.Button
                Accessible.name: entryRow.command.label || ""
            }

            Text {
                anchors.centerIn: parent
                visible: list.count === 0
                text: "No matching command"
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.label
            }
        }
    }
}
