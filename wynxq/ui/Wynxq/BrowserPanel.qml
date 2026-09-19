import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    An embedded browser with a developer's chrome: address, back, forward,
    reload, open outside — and nothing else.

    The view itself lives in BrowserView.qml and is loaded only when Qt
    WebEngine is present, so an installation without it gets an explanation and
    a working "open outside" instead of a broken panel.

    The page reaches the model only when you hand it over. Wynxq does not read
    what you browse.
*/
Item {
    id: root
    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property bool available: !!(dock && dock.browserAvailable)
    readonly property bool loaded: loader.status === Loader.Ready

    function focusAddress() { address.forceActiveFocus(); address.selectAll(); }
    function comparableAddress(value) {
        var result = String(value || "").trim().toLowerCase();
        result = result.replace(/^https?:\/\//, "");
        while (result.length > 1 && result.endsWith("/")) result = result.slice(0, -1);
        return result;
    }

    // The address bar shows where you are until you start typing, then it is
    // yours until you commit or leave.
    property bool editing: false
    readonly property string shownUrl: dock ? dock.browserDisplayUrl : ""
    onShownUrlChanged: if (!editing) address.text = shownUrl

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ------------------------------------------------------- the chrome
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.control + Theme.s2 * 2
            color: Theme.backgroundSoft
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1; color: Theme.borderSubtle
            }

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.s2
                spacing: Theme.s1

                IconButton {
                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                    iconSize: 13
                    iconName: "back"
                    tooltip: "Back"
                    enabled: !!(root.dock && root.dock.browserCanGoBack)
                    onClicked: if (loader.item) loader.item.goBack()
                }
                IconButton {
                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                    iconSize: 13
                    iconName: "forward"
                    tooltip: "Forward"
                    enabled: !!(root.dock && root.dock.browserCanGoForward)
                    onClicked: if (loader.item) loader.item.goForward()
                }
                IconButton {
                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                    iconSize: 13
                    iconName: root.dock && root.dock.browserLoading ? "close" : "retry"
                    tooltip: root.dock && root.dock.browserLoading ? "Stop" : "Reload"
                    enabled: root.loaded && !!(root.dock && root.dock.browserUrl)
                    onClicked: {
                        if (!loader.item) return;
                        if (root.dock && root.dock.browserLoading) loader.item.stop();
                        else loader.item.reload();
                    }
                }

                Field {
                    id: address
                    objectName: "browserAddress"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28
                    iconName: !root.dock || !root.dock.browserTrust ? "search"
                            : root.dock.browserTrust === "secure" ? "lock"
                            : root.dock.browserTrust === "local" ? "globe" : "warning"
                    placeholderText: "Search or enter an address"
                    mono: true
                    font.pixelSize: Theme.micro
                    enabled: root.available
                    onActiveFocusChanged: {
                        root.editing = activeFocus;
                        if (!activeFocus) text = root.shownUrl;
                    }
                    onAccepted: {
                        if (!root.dock) return;
                        // A consumed navigation request remains in the backend as
                        // the current address. Re-entering that exact address used
                        // to be a no-op because the pending string did not change.
                        // Treat it as an explicit reload instead.
                        if (root.loaded && loader.item && root.dock.browserUrl
                                && root.comparableAddress(text) === root.comparableAddress(root.dock.browserUrl)) {
                            loader.item.reload();
                            root.editing = false;
                            focus = false;
                            return;
                        }
                        if (root.dock.navigate(text)) root.editing = false;
                        focus = false;
                    }
                    Keys.onEscapePressed: { text = root.shownUrl; focus = false; }
                }

                IconButton {
                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                    iconSize: 13
                    iconName: "paperclip"
                    tooltip: "Attach this page to the conversation"
                    enabled: root.loaded && !!(root.dock && root.dock.browserUrl)
                    onClicked: if (loader.item) loader.item.capturePage()
                }
                IconButton {
                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                    iconSize: 13
                    iconName: "launch"
                    tooltip: "Open in your system browser"
                    enabled: !!(root.dock && root.dock.browserUrl)
                    onClicked: if (root.dock && root.dock.browserUrl) Qt.openUrlExternally(root.dock.browserUrl)
                }
            }

            // Loading is a two-pixel rail on the chrome's edge, not a spinner.
            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 2
                color: "transparent"
                visible: !!(root.dock && root.dock.browserLoading)
                Rectangle {
                    height: parent.height
                    width: parent.width * (root.dock ? Math.max(0.04, root.dock.browserProgress) : 0)
                    color: Theme.accent
                    Behavior on width { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.base } }
                }
            }
        }

        // -------------------------------------------------------- the page
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.background
            clip: true

            Loader {
                id: loader
                anchors.fill: parent
                // Loaded by URL, not as a module type: `import QtWebEngine`
                // must not be attempted where the module is absent.
                source: root.available ? Qt.resolvedUrl("BrowserView.qml") : ""
                asynchronous: true
                onLoaded: {
                    item.dock = root.dock;
                    if (root.dock && root.dock.browserRequest) item.pending = root.dock.browserRequest;
                }
            }

            Connections {
                target: root.dock
                enabled: root.loaded
                function onBrowserChanged() {
                    if (loader.item && root.dock.browserRequest)
                        loader.item.pending = root.dock.browserRequest;
                }
            }

            // Nothing loaded yet: offer somewhere to start rather than a void.
            EmptyState {
                anchors.fill: parent
                visible: root.available && !(root.dock && root.dock.browserUrl)
                         && loader.status !== Loader.Error
                iconName: "globe"
                title: "Browser"
                detail: "Open a page to read it alongside the conversation, then attach it when it is useful."
                actionText: "Open a page"
                onActionInvoked: if (root.dock) root.dock.navigate(root.dock.browserHome)
            }

            EmptyState {
                anchors.fill: parent
                visible: !root.available || loader.status === Loader.Error
                iconName: "globe"
                title: "Embedded browsing is unavailable"
                detail: root.dock ? root.dock.browserUnavailableReason : ""
                actionText: "Open in your system browser"
                onActionInvoked: Qt.openUrlExternally(root.dock ? root.dock.browserHome : "")
            }

            Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: visible ? errorText.implicitHeight + Theme.s2 * 2 : 0
                visible: !!(root.dock && root.dock.browserError)
                color: Theme.dangerMuted
                Text {
                    id: errorText
                    anchors.fill: parent
                    anchors.margins: Theme.s2
                    text: root.dock ? root.dock.browserError : ""
                    color: Theme.textSecondary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                    wrapMode: Text.WordWrap
                }
            }
        }

        // ------------------------------------------------------ page title
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 24 : 0
            visible: !!(root.dock && root.dock.browserTitle)
            color: Theme.backgroundSoft
            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1; color: Theme.borderSubtle
            }
            Text {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                verticalAlignment: Text.AlignVCenter
                text: root.dock ? root.dock.browserTitle : ""
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                elide: Text.ElideRight
            }
        }
    }
}
