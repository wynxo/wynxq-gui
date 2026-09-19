import QtQuick
import QtWebEngine

/*!
    The Qt WebEngine view, deliberately kept out of `qmldir`.

    `import QtWebEngine` fails outright on an installation without the module,
    and a failing import in a module type would take the whole Wynxq module
    down with it. BrowserPanel loads this file by URL instead, so a machine
    without WebEngine gets a clear explanation rather than a broken app.

    Everything the rest of Wynxq needs to know about the page is reported back
    through the dock, which owns the address bar's truth.
*/
Item {
    id: root
    property var dock: null
    property string pending: ""

    function goBack() { view.goBack(); }
    function goForward() { view.goForward(); }
    function reload() { view.reload(); }
    function stop() { view.stop(); }
    function capturePage() {
        // The page's own text, handed over only when the user asks for it.
        view.runJavaScript("document.body ? document.body.innerText : ''", function (text) {
            if (root.dock) root.dock.attachPage(view.url.toString(), view.title, text || "");
        });
    }

    onPendingChanged: if (pending) view.url = pending

    WebEngineView {
        id: view
        anchors.fill: parent
        url: root.pending || "about:blank"
        backgroundColor: Theme.background

        settings.javascriptCanOpenWindows: false
        settings.javascriptCanAccessClipboard: false
        settings.allowWindowActivationFromJavaScript: false
        settings.screenCaptureEnabled: false
        settings.localContentCanAccessFileUrls: false
        settings.localContentCanAccessRemoteUrls: false
        settings.fullScreenSupportEnabled: false

        onUrlChanged: root.report()
        onTitleChanged: root.report()
        onLoadingChanged: function(request) {
            if (!root.dock) return;
            root.dock.browserLoadState(request.status === WebEngineView.LoadStartedStatus,
                                       loadProgress / 100);
            if (request.status === WebEngineView.LoadFailedStatus)
                root.dock.browserFailed(request.errorString || "That page could not be loaded");
            else if (request.status === WebEngineView.LoadSucceededStatus)
                root.dock.browserFailed("");
            root.report();
        }
        onLoadProgressChanged: if (root.dock) root.dock.browserLoadState(loading, loadProgress / 100)

        // A page asking for a new window navigates in place instead; the panel
        // is one view, and a hidden popup would be a page you cannot see.
        onNewWindowRequested: function(request) { view.url = request.requestedUrl; }

        // Nothing is granted silently. The panel is a reader, not a device.
        onPermissionRequested: function(permission) { permission.deny(); }
    }

    function report() {
        if (!dock) return;
        dock.browserStateChanged(view.url.toString(), view.title);
        dock.browserHistoryState(view.canGoBack, view.canGoForward);
    }
}
