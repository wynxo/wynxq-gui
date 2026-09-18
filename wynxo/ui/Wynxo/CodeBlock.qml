import QtQuick
import QtQuick.Controls

/*!
    A fenced code block.

    Streaming and finalized code use separate text documents. Swapping one
    TextEdit between PlainText and RichText while tokens are arriving can make
    Qt rebuild selection/layout state at the exact moment a fence closes. The
    streaming document therefore stays plain forever; the finalized document
    is created once and receives syntax-highlighted rich text.

    Copy, save and terminal actions always use root.code — the untouched model
    output — never the highlighted HTML used only for display.
*/
Rectangle {
    id: root
    property string code: ""
    property string language: ""
    property string label: "Text"
    property bool streaming: false
    property bool runnable: false

    color: Theme.surfaceSunken
    radius: Theme.r2
    border.width: 1
    border.color: Theme.borderSubtle
    implicitHeight: header.height + body.implicitHeight + Theme.s3 * 2
    clip: true

    Item {
        id: header
        width: parent.width
        height: 34

        Text {
            anchors.left: parent.left
            anchors.leftMargin: Theme.s3
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: Theme.textMuted
            font.family: Theme.sansFamily
            font.pixelSize: Theme.micro
            font.letterSpacing: 0.8
            font.capitalization: Font.AllUppercase
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: Theme.s1
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            opacity: root.streaming ? 0 : 1
            visible: opacity > 0
            Behavior on opacity {
                enabled: !Theme.reducedMotion
                NumberAnimation { duration: Theme.fast }
            }

            IconButton {
                width: 28
                height: 28
                iconSize: 14
                iconName: "terminal"
                tooltip: "Copy and open a terminal"
                visible: root.runnable
                onClicked: if (bridge) bridge.copyAndOpenTerminal(root.code)
            }
            IconButton {
                width: 28
                height: 28
                iconSize: 14
                iconName: "save"
                tooltip: "Save snippet…"
                onClicked: if (bridge) bridge.saveCode(root.code, root.language)
            }
            IconButton {
                width: 28
                height: 28
                iconSize: 14
                iconName: "copy"
                tooltip: "Copy code"
                onClicked: if (bridge) bridge.copyText(root.code)
            }
        }

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.borderSubtle
        }
    }

    Flickable {
        id: body
        anchors.top: header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Theme.s3
        anchors.topMargin: Theme.s3
        implicitHeight: Math.min(codeLoader.item ? codeLoader.item.implicitHeight : 0, 520)
        height: implicitHeight
        contentWidth: Math.max(width, codeLoader.item ? codeLoader.item.implicitWidth : 0)
        contentHeight: codeLoader.item ? codeLoader.item.implicitHeight : 0
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.horizontal: WScrollBar { policy: ScrollBar.AsNeeded }
        ScrollBar.vertical: WScrollBar { policy: ScrollBar.AsNeeded }

        Loader {
            id: codeLoader
            width: Math.max(body.width, item ? item.implicitWidth : 0)
            height: item ? item.implicitHeight : 0
            sourceComponent: root.streaming ? streamingCode : finalizedCode
        }
    }

    Component {
        id: streamingCode
        TextEdit {
            readOnly: true
            selectByMouse: true
            textFormat: TextEdit.PlainText
            text: root.code
            color: Theme.codePalette.text
            selectionColor: Theme.accent
            selectedTextColor: Theme.onAccent
            font.family: Theme.monoFamily
            font.pixelSize: Theme.caption + 1
            wrapMode: TextEdit.NoWrap
            Accessible.name: "Streaming code"
        }
    }

    Component {
        id: finalizedCode
        TextEdit {
            id: finalText
            readOnly: true
            selectByMouse: true
            textFormat: TextEdit.RichText
            // `revision` exists only so a palette change re-runs this binding.
            property int revision: 0
            text: finalText.render(revision)
            function render(revision) {
                if (!bridge) return root.code;
                return bridge.highlight(root.code, root.language);
            }
            Connections {
                target: bridge
                function onPaletteChanged() { finalText.revision++; }
            }
            color: Theme.codePalette.text
            selectionColor: Theme.accent
            selectedTextColor: Theme.onAccent
            font.family: Theme.monoFamily
            font.pixelSize: Theme.caption + 1
            wrapMode: TextEdit.NoWrap
            Accessible.name: root.label + " code"
        }
    }
}
