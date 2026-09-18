import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    What is uncommitted in the project, and what each change looks like.

    Git already knows what "changed" means, so the panel asks it rather than
    keeping a second opinion. The list is the summary; picking a file opens the
    diff underneath it. Reverting is here, behind a confirmation, because
    throwing away work is exactly the action that must never be one click.
*/
Item {
    id: root
    signal openRequested(string path)
    signal revertRequested(string path, string name)

    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property var entries: dock ? dock.changes : []
    readonly property bool showingDiff: !!(dock && dock.diffPath)

    function shortStatus(code) {
        return code === "?" ? "A" : code;
    }
    function statusTone(code) {
        if (code === "A" || code === "?") return Theme.diffAddInk;
        if (code === "D") return Theme.diffRemoveInk;
        if (code === "U") return Theme.warning;
        return Theme.info;
    }
    function parentFolder(path) {
        var value = String(path || "");
        var slash = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
        return slash > 0 ? value.slice(0, slash) : value;
    }
    function terminalFor(relativePath) {
        if (!root.dock || !relativePath) return;
        var absolute = root.dock.absolutePath(relativePath);
        root.dock.runInTerminal("cd " + JSON.stringify(root.parentFolder(absolute)));
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Changes"
            detail: root.dock && root.dock.branch ? root.dock.branch : ""
            detailFont: "mono"

            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "retry"
                tooltip: "Refresh"
                enabled: !(root.dock && root.dock.changesBusy)
                onClicked: if (root.dock) root.dock.refreshChanges()
            }
        }

        // ------------------------------------------------------- summary
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: root.dock && root.dock.isRepository ? 28 : 0
            visible: !!(root.dock && root.dock.isRepository)
            color: Theme.background

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                spacing: Theme.s2

                Text {
                    Layout.fillWidth: true
                    text: root.dock ? root.dock.changesSummary : ""
                    color: Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.micro
                    elide: Text.ElideRight
                }
                StatusDot {
                    visible: !!(root.dock && root.dock.changesBusy)
                    width: 6; height: 6
                    tone: Theme.accent
                    pulsing: true
                }
            }
        }

        // -------------------------------------------------------- the list
        ListView {
            id: list
            objectName: "changesList"
            Layout.fillWidth: true
            Layout.fillHeight: !root.showingDiff
            Layout.preferredHeight: root.showingDiff
                ? Math.min(contentHeight, Math.round(root.height * 0.34)) : -1
            visible: root.entries.length > 0
            clip: true
            model: root.entries
            boundsBehavior: Flickable.StopAtBounds
            reuseItems: true
            ScrollBar.vertical: WScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: AbstractButton {
                id: change
                required property var modelData
                width: list.width
                height: Theme.rowHeight
                hoverEnabled: true
                readonly property bool current: !!(root.dock && root.dock.diffPath === modelData.path)
                readonly property bool existsInWorktree: modelData.status !== "D"
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.statusLabel + " " + modelData.path
                        + ", " + modelData.added + " added, " + modelData.removed + " removed"
                onClicked: if (root.dock) {
                    if (change.current) root.dock.closeDiff();
                    else root.dock.openDiff(modelData.path);
                }

                background: Rectangle {
                    color: change.current ? Theme.surfaceSelected
                         : change.hovered || changeMenu.opened ? Theme.surfaceHover : "transparent"
                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 2
                        height: change.current ? parent.height - 10 : 0
                        color: Theme.accent
                    }
                }

                contentItem: RowLayout {
                    spacing: Theme.s2

                    // The one-letter status is the fastest thing to scan, so
                    // it gets a fixed column and never moves.
                    Text {
                        Layout.leftMargin: Theme.s3
                        Layout.preferredWidth: 10
                        text: root.shortStatus(change.modelData.status)
                        color: root.statusTone(change.modelData.status)
                        font.family: Theme.monoFamily
                        font.pixelSize: Theme.caption
                        font.weight: Font.Medium
                        horizontalAlignment: Text.AlignHCenter
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        spacing: 0
                        Text {
                            Layout.fillWidth: true
                            text: change.modelData.name
                            color: change.current ? Theme.textPrimary : Theme.textSecondary
                            font.family: Theme.sansFamily
                            font.pixelSize: Theme.caption
                            font.weight: change.current ? Font.Medium : Font.Normal
                            elide: Text.ElideMiddle
                        }
                        Text {
                            Layout.fillWidth: true
                            visible: !!change.modelData.directory
                            text: change.modelData.directory
                            color: Theme.textDisabled
                            font.family: Theme.monoFamily
                            font.pixelSize: Theme.micro
                            elide: Text.ElideLeft
                        }
                    }

                    Row {
                        Layout.rightMargin: Theme.s2
                        spacing: Theme.s1
                        opacity: change.hovered ? 0 : 1
                        visible: opacity > 0
                        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                        Text {
                            visible: change.modelData.added > 0
                            text: "+" + change.modelData.added
                            color: Theme.diffAddInk
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        }
                        Text {
                            visible: change.modelData.removed > 0
                            text: "−" + change.modelData.removed
                            color: Theme.diffRemoveInk
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        }
                    }
                }

                IconButton {
                    id: more
                    anchors.right: parent.right
                    anchors.rightMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    width: 26; height: 26; iconSize: 12
                    iconName: "moreVertical"
                    tooltip: "File actions"
                    opacity: change.hovered || changeMenu.opened ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
                    onClicked: changeMenu.opened ? changeMenu.close() : changeMenu.open()

                    WMenu {
                        id: changeMenu
                        anchorX: -menuWidth + more.width
                        menuWidth: 244
                        items: [
                            { id: "open", label: "Open file", icon: "file",
                              disabled: !change.existsInWorktree },
                            { id: "diff", label: change.current ? "Hide diff" : "Show diff", icon: "branch" },
                            { separator: true },
                            { id: "copyRelative", label: "Copy relative path", icon: "copy" },
                            { id: "reveal", label: "Reveal in file manager", icon: "launch",
                              disabled: !change.existsInWorktree },
                            { id: "terminal", label: "Terminal in containing folder", icon: "terminal" },
                            { id: "attach", label: "Attach to conversation", icon: "paperclip",
                              disabled: !change.existsInWorktree },
                            { separator: true },
                            { id: "revert", label: "Discard changes", icon: "revert", danger: true },
                        ]
                        onPicked: function(id) {
                            if (!root.dock) return;
                            var absolute = root.dock.absolutePath(change.modelData.path);
                            if (id === "open") root.openRequested(absolute);
                            else if (id === "diff") change.clicked();
                            else if (id === "copyRelative" && bridge) bridge.copyText(change.modelData.path);
                            else if (id === "reveal" && bridge) bridge.revealPath(absolute);
                            else if (id === "terminal") root.terminalFor(change.modelData.path);
                            else if (id === "attach" && bridge) bridge.attachPath(absolute);
                            else if (id === "revert") root.revertRequested(change.modelData.path, change.modelData.name);
                        }
                    }
                }
            }
        }

        Divider { Layout.fillWidth: true; visible: root.showingDiff }

        DiffViewer {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.showingDiff
            onClosed: if (root.dock) root.dock.closeDiff()
            onOpenRequested: function(path) { root.openRequested(path); }
        }

        // ------------------------------------------------------ empty states
        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !(root.dock && root.dock.projectPath)
            iconName: "folder"
            title: "No project open"
            detail: "Changes are read from the Git repository of the project folder."
            actionText: "Open project…"
            onActionInvoked: if (bridge) bridge.chooseProject()
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !!(root.dock && root.dock.projectPath && !root.dock.isRepository)
            iconName: "branch"
            title: "Not a Git repository"
            detail: "Wynxo reads changes from Git. Initialise one in this folder to track them here."
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !!(root.dock && root.dock.isRepository) && root.entries.length === 0
                     && !(root.dock && root.dock.changesError)
            iconName: "check"
            title: "Working tree clean"
            detail: root.dock && root.dock.branch
                ? "Nothing uncommitted on " + root.dock.branch + "."
                : "Nothing uncommitted."
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !!(root.dock && root.dock.changesError)
            iconName: "warning"
            tone: true
            title: "Git could not be read"
            detail: root.dock ? root.dock.changesError : ""
            actionText: "Try again"
            onActionInvoked: if (root.dock) root.dock.refreshChanges()
        }
    }
}
