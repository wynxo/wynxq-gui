import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    One open file: code with line numbers, an image, or an honest refusal.

    It is a viewer that can also save. Editing is a plain monospaced buffer with
    an unsaved marker — not a half-built IDE. What it does, it does properly:
    the gutter stays aligned, long lines scroll rather than wrap by default, and
    the file on disk is never touched until you ask.
*/
Item {
    id: root
    signal closed()

    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property var record: dock ? dock.file : ({})
    readonly property bool hasFile: !!(record && record.path)
    readonly property bool isImage: hasFile && !!record.image
    readonly property bool readable: hasFile && !record.error && !record.binary && !record.image
    readonly property bool editable: readable && !record.truncated
    readonly property bool dirty: !!(dock && dock.fileModified)
    property bool wrap: false
    property bool findOpen: false
    property bool goLineOpen: false
    property int findPosition: -1
    property int findCount: 0
    property int findOrdinal: 0
    property bool findCountCapped: false
    readonly property int maxFindMatches: 10000

    readonly property int bufferLines: readable ? editor.text.split("\n").length : 0

    // Derived from the live buffer. Wrapping hides the
    // gutter, because a wrapped line no longer matches a numbered row.
    readonly property string numbers: {
        var total = root.readable ? Math.min(root.bufferLines, 50000) : 0;
        if (!total) return "";
        var out = [];
        for (var line = 1; line <= total; line++) out.push(line);
        return out.join("\n");
    }

    // Loading a different file replaces the buffer; typing in it does not.
    property string loadedPath: ""
    onRecordChanged: {
        if (record.path !== loadedPath) {
            loadedPath = record.path || "";
            editor.text = record.text || "";
            root.findPosition = -1;
            root.findCount = 0;
            root.findOrdinal = 0;
            root.findCountCapped = false;
            findInput.text = "";
            lineInput.text = "";
            root.findOpen = false;
            root.goLineOpen = false;
        }
    }

    function save() { if (dock && root.editable) dock.saveFile(); }
    function parentFolder(path) {
        var value = String(path || "");
        var slash = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
        return slash === 0 ? value.slice(0, 1) : slash > 0 ? value.slice(0, slash) : value;
    }
    function terminalInFileFolder() {
        if (!dock || !root.hasFile) return;
        var directory = root.parentFolder(root.record.path);
        // POSIX single quoting keeps dollar signs, backticks and newlines literal.
        dock.runInTerminal("cd -- '" + directory.replace(/'/g, "'\"'\"'") + "'");
    }
    function openFind() {
        if (!readable) return;
        goLineOpen = false;
        findOpen = true;
        root.recountFindMatches();
        Qt.callLater(function () { findInput.forceActiveFocus(); findInput.selectAll(); });
    }
    function closeFind() {
        findOpen = false;
        findPosition = -1;
        findOrdinal = 0;
        editor.deselect();
        editor.forceActiveFocus();
    }
    function openGoLine() {
        if (!readable) return;
        findOpen = false;
        findPosition = -1;
        findOrdinal = 0;
        editor.deselect();
        goLineOpen = true;
        lineInput.text = "";
        Qt.callLater(function () { lineInput.forceActiveFocus(); });
    }
    function closeGoLine() {
        goLineOpen = false;
        editor.forceActiveFocus();
    }
    function positionForLine(value) {
        var wanted = Math.round(Number(value) || 0);
        var total = Math.max(1, Number(root.bufferLines || 1));
        if (wanted < 1 || wanted > total) return -1;
        if (wanted === 1) return 0;
        var position = 0;
        for (var line = 1; line < wanted; line++) {
            var newline = editor.text.indexOf("\n", position);
            if (newline < 0) return editor.text.length;
            position = newline + 1;
        }
        return position;
    }
    function goToLine() {
        var position = root.positionForLine(lineInput.text);
        if (position < 0) return;
        editor.deselect();
        editor.cursorPosition = position;
        goLineOpen = false;
        editor.forceActiveFocus();
        // TextEdit sits inside our own Flickable, so moving its cursor does not
        // automatically scroll the outer viewport. Keep the destination about
        // a third of the way down the panel so nearby code remains visible.
        Qt.callLater(function () {
            var maximum = Math.max(0, flick.contentHeight - flick.height);
            var desired = Math.max(0, editor.cursorRectangle.y - flick.height * 0.33);
            flick.contentY = Math.min(maximum, desired);
            flick.contentX = 0;
        });
    }
    function revealCursor() {
        if (!root.readable) return;
        var cursor = editor.cursorRectangle;
        var left = editor.x + cursor.x;
        var top = editor.y + cursor.y;
        if (top < flick.contentY) flick.contentY = top;
        else if (top + cursor.height > flick.contentY + flick.height)
            flick.contentY = top + cursor.height - flick.height;
        if (left < flick.contentX) flick.contentX = left;
        else if (left + cursor.width > flick.contentX + flick.width)
            flick.contentX = left + cursor.width - flick.width;
        flick.contentY = Math.max(0, Math.min(flick.contentY, flick.contentHeight - flick.height));
        flick.contentX = Math.max(0, Math.min(flick.contentX, flick.contentWidth - flick.width));
    }
    function recountFindMatches() {
        var query = findInput.text.toLowerCase();
        if (!query || !readable) {
            findCount = 0;
            findOrdinal = 0;
            findCountCapped = false;
            return;
        }
        var haystack = editor.text.toLowerCase();
        var cursor = 0;
        var count = 0;
        var next = -1;
        while ((next = haystack.indexOf(query, cursor)) >= 0) {
            count++;
            cursor = next + Math.max(1, query.length);
            if (count >= maxFindMatches) {
                findCountCapped = haystack.indexOf(query, cursor) >= 0;
                break;
            }
        }
        findCount = count;
        if (!count) findOrdinal = 0;
    }
    function ordinalFor(haystack, query, target) {
        if (target < 0 || !query) return 0;
        var cursor = 0;
        var ordinal = 0;
        var next = -1;
        while ((next = haystack.indexOf(query, cursor)) >= 0) {
            ordinal++;
            if (next === target) return ordinal;
            if (ordinal >= maxFindMatches) return maxFindMatches;
            cursor = next + Math.max(1, query.length);
        }
        return 0;
    }
    function findNext(backwards) {
        var needle = findInput.text;
        if (!needle || !readable) {
            findPosition = -1;
            findOrdinal = 0;
            editor.deselect();
            return;
        }
        var haystack = editor.text.toLowerCase();
        var query = needle.toLowerCase();
        var position = -1;
        if (backwards) {
            var before = findPosition > 0 ? findPosition - 1 : haystack.length;
            position = haystack.lastIndexOf(query, before);
            if (position < 0) position = haystack.lastIndexOf(query);
        } else {
            var after = findPosition >= 0 ? findPosition + query.length : 0;
            position = haystack.indexOf(query, after);
            if (position < 0) position = haystack.indexOf(query);
        }
        findPosition = position;
        findOrdinal = root.ordinalFor(haystack, query, position);
        if (position >= 0) {
            editor.select(position, position + query.length);
            Qt.callLater(root.revealCursor);
        } else {
            editor.deselect();
        }
    }

    Shortcut {
        sequences: ["Ctrl+F"]
        enabled: root.readable
        onActivated: root.openFind()
    }
    Shortcut {
        sequences: ["Ctrl+G"]
        enabled: root.readable
        onActivated: root.openGoLine()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: root.hasFile ? (record.name + (root.dirty ? " •" : "")) : "No file open"
            detail: root.hasFile
                ? (record.relative && record.relative !== record.name
                   ? record.relative : record.sizeLabel)
                : ""
            detailFont: "mono"
            detailElide: Text.ElideLeft

            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.dirty
                iconName: "save"
                tooltip: "Save"
                shortcut: "Ctrl+S"
                tint: Theme.accent
                activeTint: Theme.accent
                onClicked: root.save()
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.dirty
                iconName: "revert"
                tooltip: "Discard unsaved edits"
                onClicked: if (root.dock) { root.dock.revertFileBuffer(); editor.text = root.record.text || ""; }
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.readable
                iconName: "search"
                tooltip: "Find in file"
                shortcut: "Ctrl+F"
                active: root.findOpen
                onClicked: root.findOpen ? root.closeFind() : root.openFind()
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.readable
                iconName: "wrap"
                tooltip: root.wrap ? "Stop wrapping long lines" : "Wrap long lines"
                active: root.wrap
                onClicked: root.wrap = !root.wrap
            }
            IconButton {
                id: fileMore
                width: 28; height: 28; iconSize: 12
                visible: root.hasFile
                iconName: "moreVertical"
                tooltip: "File actions"
                active: fileMenu.opened
                onClicked: fileMenu.opened ? fileMenu.close() : fileMenu.open()

                WMenu {
                    id: fileMenu
                    anchorX: -menuWidth + fileMore.width
                    menuWidth: 246
                    items: [
                        { id: "line", label: "Go to line…", icon: "code", shortcut: "Ctrl+G", disabled: !root.readable },
                        { id: "copy", label: "Copy whole file", icon: "copy", disabled: !root.readable },
                        { separator: true },
                        { id: "attach", label: "Attach to conversation", icon: "paperclip" },
                        { id: "terminal", label: "Terminal in containing folder", icon: "terminal" },
                        { id: "reveal", label: "Reveal outside Wynxo", icon: "launch" },
                    ]
                    onPicked: function(id) {
                        if (id === "line") root.openGoLine();
                        else if (id === "copy" && bridge) bridge.copyText(editor.text);
                        else if (id === "attach" && bridge) bridge.attachPath(root.record.path);
                        else if (id === "terminal") root.terminalInFileFolder();
                        else if (id === "reveal" && bridge) bridge.revealPath(root.record.path);
                    }
                }
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.hasFile
                iconName: "close"
                tooltip: "Close file"
                onClicked: root.closed()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.findOpen ? Theme.control + Theme.s2 : 0
            visible: root.findOpen
            color: Theme.backgroundSoft
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.borderSubtle
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s2
                anchors.rightMargin: Theme.s2
                anchors.topMargin: Theme.s1
                anchors.bottomMargin: Theme.s1
                spacing: Theme.s1

                Field {
                    id: findInput
                    objectName: "fileFindInput"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.controlSmall
                    iconName: "search"
                    placeholderText: "Find in file"

                    onTextChanged: {
                        root.findPosition = -1;
                        root.recountFindMatches();
                        if (text.length) root.findNext(false);
                        else editor.deselect();
                    }
                    Keys.onReturnPressed: function(event) {
                        root.findNext(!!(event.modifiers & Qt.ShiftModifier));
                        event.accepted = true;
                    }
                    Keys.onEscapePressed: function(event) { root.closeFind(); event.accepted = true; }
                }
                Text {
                    Layout.minimumWidth: implicitWidth
                    text: !findInput.text.length ? ""
                        : root.findCount === 0 ? "No matches"
                        : (root.findOrdinal > 0 ? root.findOrdinal : 1) + " / "
                          + root.findCount + (root.findCountCapped ? "+" : "")
                    color: root.findCount === 0 && findInput.text.length ? Theme.warning : Theme.textMuted
                    font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                }
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26
                    iconName: "up"; iconSize: 11
                    tooltip: "Previous match"
                    enabled: root.findCount > 0
                    onClicked: root.findNext(true)
                }
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26
                    iconName: "down"; iconSize: 11
                    tooltip: "Next match"
                    enabled: root.findCount > 0
                    onClicked: root.findNext(false)
                }
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26
                    iconName: "close"; iconSize: 11
                    tooltip: "Close find"
                    onClicked: root.closeFind()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.goLineOpen ? Theme.control + Theme.s2 : 0
            visible: root.goLineOpen
            color: Theme.backgroundSoft
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.borderSubtle
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s2
                anchors.rightMargin: Theme.s2
                anchors.topMargin: Theme.s1
                anchors.bottomMargin: Theme.s1
                spacing: Theme.s2

                Field {
                    id: lineInput
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.controlSmall
                    iconName: "code"
                    placeholderText: "Line 1–" + Math.max(1, root.bufferLines || 1)
                    validator: IntValidator { bottom: 1; top: Math.max(1, root.bufferLines || 1) }
                    Keys.onReturnPressed: function(event) { root.goToLine(); event.accepted = true; }
                    Keys.onEscapePressed: function(event) { root.closeGoLine(); event.accepted = true; }
                }
                Text {
                    text: (root.bufferLines) + " lines"
                    color: Theme.textMuted
                    font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                }
                WButton {
                    text: "Go"
                    compactPadding: true
                    implicitHeight: 24
                    enabled: lineInput.acceptableInput
                    onClicked: root.goToLine()
                }
                IconButton {
                    Layout.preferredWidth: 26; Layout.preferredHeight: 26
                    iconName: "close"; iconSize: 11
                    tooltip: "Close go to line"
                    onClicked: root.closeGoLine()
                }
            }
        }

        // -------------------------------------------------------- the code
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.surfaceSunken
            clip: true

            Flickable {
                id: flick
                objectName: "fileViewport"
                anchors.fill: parent
                visible: root.readable
                contentWidth: Math.max(width, editor.x + editor.contentWidth + Theme.s4)
                contentHeight: Math.max(height, editor.contentHeight + Theme.s3 * 2)
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                ScrollBar.vertical: WScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                ScrollBar.horizontal: WScrollBar {
                    policy: root.wrap ? ScrollBar.AlwaysOff : ScrollBar.AsNeeded
                }

                // One Text, not one per line: a 12 000-line file would
                // otherwise put 12 000 items in the scene graph. The same font
                // and line height as the editor keeps the two in step.
                Text {
                    id: gutter
                    x: 0
                    y: Theme.s3
                    width: Math.max(30, numberMetrics.width + Theme.s3)
                    visible: root.readable && !root.wrap
                    rightPadding: Theme.s2
                    horizontalAlignment: Text.AlignRight
                    text: root.numbers
                    color: Theme.textDisabled
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.code
                    textFormat: Text.PlainText
                }

                TextMetrics {
                    id: numberMetrics
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.code
                    text: String(Math.max(1000, root.bufferLines || 1000))
                }

                TextEdit {
                    id: editor
                    objectName: "fileEditor"
                    x: gutter.visible ? gutter.width : Theme.s3
                    y: Theme.s3
                    width: root.wrap ? flick.width - x - Theme.s3
                                     : Math.max(contentWidth, flick.width - x)
                    color: Theme.textPrimary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                    font.family: Theme.monoFamily
                    font.pixelSize: Theme.code
                    selectByMouse: true
                    readOnly: !root.editable
                    wrapMode: root.wrap ? TextEdit.WrapAnywhere : TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                    persistentSelection: true
                    Accessible.role: root.editable ? Accessible.EditableText : Accessible.StaticText
                    Accessible.name: root.hasFile ? root.record.name : "File contents"

                    onCursorRectangleChanged: Qt.callLater(root.revealCursor)

                    onTextChanged: {
                        if (root.dock && root.loadedPath && root.editable) root.dock.setFileBuffer(text);
                        if (root.findOpen && findInput.text.length) {
                            root.findPosition = -1;
                            root.recountFindMatches();
                            root.findNext(false);
                        }
                    }
                    Keys.onPressed: function(event) {
                        if (event.key === Qt.Key_S && (event.modifiers & Qt.ControlModifier)) {
                            root.save();
                            event.accepted = true;
                        } else if (event.key === Qt.Key_F && (event.modifiers & Qt.ControlModifier)) {
                            root.openFind();
                            event.accepted = true;
                        } else if (event.key === Qt.Key_G && (event.modifiers & Qt.ControlModifier)) {
                            root.openGoLine();
                            event.accepted = true;
                        }
                    }
                }
            }

            // ------------------------------------------------------ image
            Item {
                anchors.fill: parent
                anchors.margins: Theme.s4
                visible: root.isImage
                Image {
                    id: preview
                    anchors.centerIn: parent
                    width: Math.min(parent.width, implicitWidth)
                    height: Math.min(parent.height, implicitHeight)
                    source: root.isImage ? "data:image/" + (root.record.imageFormat || "png")
                                           + ";base64," + root.record.image : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    visible: preview.status === Image.Ready
                    text: preview.sourceSize.width + " × " + preview.sourceSize.height
                          + (root.record.sizeLabel ? " · " + root.record.sizeLabel : "")
                    color: Theme.textMuted
                    font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: root.hasFile && !!root.record.error
                iconName: root.record.binary ? "lock" : "warning"
                title: root.record.binary ? "Not a text file" : "Could not open this file"
                detail: root.record.error || ""
                actionText: "Open outside Wynxo"
                onActionInvoked: if (bridge) bridge.revealPath(root.record.path)
            }

            EmptyState {
                anchors.fill: parent
                visible: !root.hasFile
                iconName: "file"
                title: "No file open"
                detail: "Pick a file in the tree above to read or edit it here."
            }
        }

        // ----------------------------------------------- read-only preview
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.record.truncated ? 30 : 0
            visible: !!root.record.truncated
            color: Theme.backgroundSoft
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1; color: Theme.borderSubtle
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                spacing: Theme.s2
                Icon {
                    name: "lock"
                    ink: Theme.textMuted
                    Layout.preferredWidth: 11
                    Layout.preferredHeight: 11
                }
                Text {
                    Layout.fillWidth: true
                    text: "Large-file preview · read-only to protect content not loaded into the editor"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.micro
                    elide: Text.ElideRight
                }
            }
        }

        // -------------------------------------------------- unsaved banner
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.dirty ? 30 : 0
            visible: root.dirty
            color: Theme.warningMuted
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1; color: Theme.alpha(Theme.warning, 0.3)
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s2
                spacing: Theme.s2
                Icon { name: "edit"; ink: Theme.warning; Layout.preferredWidth: 11; Layout.preferredHeight: 11 }
                Text {
                    Layout.fillWidth: true
                    text: "Unsaved changes"
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                }
                WButton {
                    text: "Save"
                    variant: "primary"
                    compactPadding: true
                    implicitHeight: 22
                    font.pixelSize: Theme.micro
                    onClicked: root.save()
                }
            }
        }
    }
}