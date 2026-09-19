import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Whatever is worth looking at rather than reading: an image, a capture, a
    rendered Markdown note.

    It only shows something when something has been put here — an image opened
    from the tree, a screenshot taken during a run. There is no placeholder
    preview, because a preview of nothing is not a feature.
*/
Item {
    id: root
    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property var item: dock ? dock.preview : ({})
    readonly property string kind: item && item.kind ? item.kind : ""

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: "Preview"
            detail: root.item && root.item.title ? root.item.title : ""

            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.kind === "image" && !!root.item.path
                iconName: "launch"
                tooltip: "Open outside Wynxq"
                onClicked: if (bridge) bridge.revealPath(root.item.path)
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                visible: root.kind !== ""
                iconName: "close"
                tooltip: "Clear the preview"
                onClicked: if (root.dock) root.dock.clearPreview()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.surfaceSunken
            clip: true

            // ------------------------------------------------------ image
            Item {
                anchors.fill: parent
                anchors.margins: Theme.s4
                visible: root.kind === "image"

                Image {
                    id: picture
                    anchors.centerIn: parent
                    width: Math.min(parent.width, implicitWidth)
                    height: Math.min(parent.height, implicitHeight)
                    source: root.kind === "image" && root.item.image
                            ? "data:image/png;base64," + root.item.image : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    smooth: true
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    visible: picture.status === Image.Ready
                    text: picture.sourceSize.width + " × " + picture.sourceSize.height
                    color: Theme.textMuted
                    font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                }
            }

            // ------------------------------------------- markdown and text
            Flickable {
                id: prose
                anchors.fill: parent
                anchors.margins: Theme.s4
                visible: root.kind === "markdown" || root.kind === "text"
                contentWidth: width
                contentHeight: (root.kind === "markdown" ? markdown.contentHeight
                                                         : plain.contentHeight) + Theme.s4
                boundsBehavior: Flickable.StopAtBounds
                clip: true
                ScrollBar.vertical: WScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                // `source` is the Markdown; `text` is what Python renders from
                // it. Setting `text` here would print the source instead.
                Markdown {
                    id: markdown
                    width: prose.width - Theme.s2
                    visible: root.kind === "markdown"
                    source: root.kind === "markdown" ? (root.item.body || "") : ""
                }

                TextEdit {
                    id: plain
                    width: prose.width - Theme.s2
                    visible: root.kind === "text"
                    text: root.kind === "text" ? (root.item.body || "") : ""
                    textFormat: TextEdit.PlainText
                    readOnly: true
                    selectByMouse: true
                    color: Theme.textSecondary
                    selectionColor: Theme.accent
                    selectedTextColor: Theme.onAccent
                    font.family: Theme.monoFamily; font.pixelSize: Theme.code
                    wrapMode: TextEdit.Wrap
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: root.kind === ""
                iconName: "image"
                title: "Nothing to preview"
                detail: "Open an image from the file tree, or take a screenshot, and it appears here full size."
            }
        }
    }
}
