import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The right-hand workspace: the tools, beside the conversation.

    The rail is always there; the panel opens beside it. Only the visible panel
    is instantiated, and each one keeps its state once it has been opened, so
    switching tabs is instant and a terminal does not restart because you
    looked at the files.

    Files and the file viewer share the column: the tree above, the open file
    below, because opening a file from a tree that then disappears is a worse
    tree.

    Plan is the agent-authored execution outline for genuine multi-step work.
    It can reveal itself once when the agent publishes a plan, but after the
    user chooses any workspace surface for this task the dock never moves itself
    again. That preference resets when the conversation changes.
*/
Item {
    id: root
    property bool panelOpen: false
    property int panelWidth: 380
    property bool planSelected: false
    property bool userSelectedWorkspaceTab: false
    property string observedTaskId: bridge ? bridge.taskId : ""
    property string pendingFilePath: ""
    readonly property alias resizing: resizer.dragging
    signal widthChangeRequested(int value)
    signal focusEditorRequested()

    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property string tab: dock ? dock.tab : "files"

    implicitWidth: Theme.railWidth + (panelOpen ? panelWidth + 5 : 0)

    function focusPanel() {
        if (planSelected) return;
        if (tab === "browser" && browserLoader.item) browserLoader.item.focusAddress();
        else if (tab === "terminal" && terminalLoader.item) terminalLoader.item.focusInput();
        else if (tab === "files" && filesLoader.item) filesLoader.item.focusFilter();
    }

    function openFile(path) {
        if (!dock || !path) return;
        var absolute = dock.absolutePath(path);
        if (dock.fileModified && dock.filePath) {
            // Clicking the already-open file should never throw its buffer away.
            if (absolute && absolute === dock.filePath) {
                dock.revealFile(path);
                return;
            }
            unsavedFileSheet.ask("open", path);
            return;
        }
        openFileNow(path);
    }

    function openFileNow(path) {
        if (!dock || !path) return;
        planSelected = false;
        // The backend is the final data-loss boundary. A programmatic caller
        // can make the buffer dirty between the UI check above and this call,
        // so reveal/select only after it explicitly accepts the transition.
        if (!dock.openFile(path)) return;
        dock.revealFile(path);
    }

    function closeFileRequested() {
        if (!dock) return;
        if (dock.fileModified) {
            unsavedFileSheet.ask("close", "");
            return;
        }
        dock.closeFile();
    }

    function revealDirectoryInFiles(path) {
        if (!dock || !path) return;
        // This transition was explicitly requested by the user from Terminal,
        // so Files becomes their chosen workspace surface rather than an
        // automatic suggestion the app may later move away from.
        userSelectedWorkspaceTab = true;
        planSelected = false;
        dock.setTab("files");
        if (!dock.visible) dock.setVisible(true);
        // A stale file search would hide the tree we are about to reveal.
        // Clearing through FileExplorer keeps both its visible field and the
        // backend filter in sync, then reveal the real shell directory.
        Qt.callLater(function () {
            if (filesLoader.item) filesLoader.item.clearFilter();
            dock.revealFile(path);
        });
    }

    function pickWorkspaceTab(id) {
        userSelectedWorkspaceTab = true;
        if (!dock) return;
        if (planSelected) {
            planSelected = false;
            dock.setTab(id);
            if (!dock.visible) dock.setVisible(true);
            return;
        }
        dock.openTab(id);
    }

    function pickPlan() {
        userSelectedWorkspaceTab = true;
        if (!dock) return;
        if (planSelected && dock.visible) {
            dock.setVisible(false);
            return;
        }
        planSelected = true;
        dock.setTab(dock.tab);
        if (!dock.visible) dock.setVisible(true);
    }

    Connections {
        target: bridge

        function onChanged() {
            if (!bridge) return;
            var taskId = bridge.taskId || "";
            if (taskId !== root.observedTaskId) {
                root.observedTaskId = taskId;
                root.userSelectedWorkspaceTab = false;
                root.planSelected = false;
            }
        }

        function onPlanChanged() {
            if (!bridge || !root.dock || root.userSelectedWorkspaceTab)
                return;
            var steps = bridge.planSteps || [];
            if (steps.length >= 2) {
                root.planSelected = true;
                if (!root.dock.visible) root.dock.setVisible(true);
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------- the handle
        Item {
            id: resizer
            property bool dragging: drag.active
            visible: root.panelOpen
            Layout.preferredWidth: visible ? 5 : 0
            Layout.fillHeight: true
            z: 3

            Rectangle {
                anchors.centerIn: parent
                width: 1; height: parent.height
                color: resizer.dragging || edge.hovered ? Theme.glassEdgeStrong : Theme.borderSubtle
                Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
            }
            HoverHandler { id: edge; cursorShape: Qt.SizeHorCursor }
            DragHandler {
                id: drag
                target: null
                yAxis.enabled: false
                cursorShape: Qt.SizeHorCursor
                property real startWidth: 0
                onActiveChanged: {
                    if (active) startWidth = root.panelWidth;
                    else if (root.dock) root.dock.setWidth(root.panelWidth);
                }
                onTranslationChanged: {
                    if (!active || !root.dock) return;
                    root.widthChangeRequested(Math.max(root.dock.minimumWidth,
                        Math.min(root.dock.maximumWidth, startWidth - translation.x)));
                }
            }
        }

        // -------------------------------------------------------- the panel
        Item {
            id: panel
            Layout.preferredWidth: root.panelOpen ? root.panelWidth : 0
            Layout.fillHeight: true
            visible: root.panelOpen
            clip: true

            // The workspace is a permanent productivity surface. Keep it fully
            // opaque at rest; glass belongs to hover/focus/drag feedback inside
            // the tools, not to the panel behind them.
            Rectangle {
                anchors.fill: parent
                color: Theme.background
            }

            Loader {
                id: planLoader
                anchors.fill: parent
                visible: root.planSelected
                active: visible
                sourceComponent: PlanPanel {}
            }

            SplitView {
                id: filesSplit
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "files"
                orientation: Qt.Vertical
                handle: Rectangle {
                    implicitHeight: 5
                    color: "transparent"
                    Rectangle {
                        anchors.centerIn: parent
                        width: parent.width; height: 1
                        color: SplitHandle.pressed || SplitHandle.hovered
                               ? Theme.glassEdgeStrong : Theme.borderSubtle
                    }
                }

                Loader {
                    id: filesLoader
                    SplitView.preferredHeight: Math.round(root.height * 0.34)
                    SplitView.minimumHeight: 120
                    active: !root.planSelected && root.tab === "files"
                    sourceComponent: FileExplorer {
                        onOpenRequested: function(path) { root.openFile(path); }
                    }
                }
                Loader {
                    id: viewerLoader
                    SplitView.fillHeight: true
                    SplitView.minimumHeight: 120
                    active: !root.planSelected && root.tab === "files"
                    sourceComponent: FileViewer {
                        onClosed: root.closeFileRequested()
                        onFocusRequested: root.focusEditorRequested()
                    }
                }
            }

            Loader {
                id: terminalLoader
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "terminal"
                active: visible || item !== null
                sourceComponent: TerminalPanel {
                    onRevealDirectory: function(path) { root.revealDirectoryInFiles(path); }
                }
            }

            Loader {
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "changes"
                active: visible
                sourceComponent: ChangesPanel {
                    onOpenRequested: function(path) {
                        if (!path || !root.dock) return;
                        root.planSelected = false;
                        root.dock.setTab("files");
                        root.openFile(path);
                    }
                    onRevertRequested: function(path, name) { revertSheet.ask(path, name); }
                }
            }

            Loader {
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "context"
                active: visible
                sourceComponent: ContextPanel {}
            }

            Loader {
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "memory"
                active: visible
                sourceComponent: MemoryPanel {}
            }

            Loader {
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "activity"
                active: visible
                sourceComponent: ActivityPanel {}
            }

            Loader {
                id: browserLoader
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "browser"
                active: visible || item !== null
                sourceComponent: BrowserPanel {}
            }

            Loader {
                anchors.fill: parent
                visible: !root.planSelected && root.tab === "preview"
                active: visible
                sourceComponent: PreviewPanel {}
            }
        }

        DockTabBar {
            Layout.preferredWidth: Theme.railWidth
            Layout.fillHeight: true
            current: root.tab
            panelOpen: root.panelOpen
            planSelected: root.planSelected
            onPicked: function(id) { root.pickWorkspaceTab(id); }
            onPickedPlan: root.pickPlan()
            onToggleDock: {
                root.userSelectedWorkspaceTab = true;
                if (root.dock) root.dock.toggle();
            }
        }
    }

    ConfirmSheet {
        id: unsavedFileSheet
        title: "Discard unsaved edits?"
        confirmText: "Discard"
        confirmVariant: "danger"
        property string nextAction: ""
        function ask(action, path) {
            nextAction = action;
            root.pendingFilePath = path || "";
            message = action === "open"
                ? "Opening another file will discard the edits in the current file."
                : "Closing this file will discard its unsaved edits.";
            detail = root.dock ? root.dock.filePath : "";
            show();
        }
        onConfirmed: {
            if (!root.dock) return;
            root.dock.revertFileBuffer();
            if (nextAction === "open") {
                var target = root.pendingFilePath;
                root.pendingFilePath = "";
                root.openFileNow(target);
            } else {
                root.pendingFilePath = "";
                root.dock.closeFile();
            }
        }
    }

    ConfirmSheet {
        id: revertSheet
        title: "Discard these changes?"
        confirmText: "Discard"
        confirmVariant: "danger"
        property string targetPath: ""
        function ask(path, name) {
            targetPath = path;
            message = "Every uncommitted change in “" + name + "” will be thrown away. This cannot be undone.";
            detail = path;
            show();
        }
        onConfirmed: if (root.dock) root.dock.revertChange(targetPath)
    }
}
