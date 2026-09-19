import QtQuick
import QtQuick.Controls

/*!
    Prose.

    Markdown is rendered to styled HTML by Python so headings, tables, quotes
    and lists follow the same type scale as the rest of the app. While a
    message is still streaming the re-render is throttled, which keeps token
    updates smooth on long answers.
*/
TextEdit {
    id: view
    property string source: ""
    property bool streaming: false
    signal linkClicked(string link)

    textFormat: TextEdit.RichText
    readOnly: true
    selectByMouse: true
    wrapMode: TextEdit.Wrap
    color: Theme.textPrimary
    selectionColor: Theme.accent
    selectedTextColor: Theme.onAccent
    font.family: Theme.sansFamily
    font.pixelSize: Theme.body
    text: view.render(revision)
    onLinkActivated: function(link) { view.linkClicked(link); }

    // Prose is rendered in Python, so changing the accent has to re-run the
    // binding. `revision` exists only to make that dependency explicit.
    property int revision: 0
    function render(revision) {
        return bridge ? bridge.renderMarkdown(rendered) : rendered;
    }
    Connections {
        target: bridge
        function onPaletteChanged() { view.revision++; }
    }

    property string rendered: ""
    onSourceChanged: {
        if (!streaming) { rendered = source; return; }
        if (!throttle.running) { rendered = source; throttle.restart(); }
        else throttle.pending = true;
    }

    Timer {
        id: throttle
        interval: 70
        property bool pending: false
        onTriggered: {
            if (pending) { pending = false; view.rendered = view.source; restart(); }
        }
    }

    // Flush the last tokens as soon as streaming stops.
    onStreamingChanged: if (!streaming) { throttle.stop(); throttle.pending = false; rendered = source; }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        cursorShape: view.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor
    }
}
