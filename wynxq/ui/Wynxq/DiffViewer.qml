import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A unified diff, rendered as rows rather than as a wall of text.

    Two narrow gutters carry the old and new line numbers so you can point at a
    line without counting. Added and removed rows are tinted, never shouted:
    the sign in the gutter does the work and the fill only groups it.
*/
Item {
    id: root
    signal closed()
    signal openRequested(string path)

    readonly property var dock: bridge ? bridge.workspaceDock : null
    readonly property var rows: dock ? dock.diffRows : []
    readonly property string path: dock ? dock.diffPath : ""

    function toneFor(type) {
        if (type === "add") return Theme.diffAddInk;
        if (type === "remove") return Theme.diffRemoveInk;
        if (type === "hunk") return Theme.diffHunk;
        if (type === "meta") return Theme.textMuted;
        return Theme.textSecondary;
    }
    function fillFor(type) {
        if (type === "add") return Theme.diffAddFill;
        if (type === "remove") return Theme.diffRemoveFill;
        return "transparent";
    }
    function signFor(type) {
        if (type === "add") return "+";
        if (type === "remove") return "−";
        return "";
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader {
            Layout.fillWidth: true
            title: root.path ? root.path.split("/").pop() : "Diff"
            detail: root.path
            detailFont: "mono"

            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "file"
                tooltip: "Open this file"
                onClicked: if (root.dock) root.openRequested(root.dock.absolutePath(root.path))
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "copy"
                tooltip: "Copy the diff"
                onClicked: {
                    if (!bridge) return;
                    var lines = [];
                    for (var i = 0; i < root.rows.length; i++)
                        lines.push(root.signFor(root.rows[i].type).replace("−", "-") + root.rows[i].text);
                    bridge.copyText(lines.join("\n"));
                }
            }
            IconButton {
                width: 28; height: 28; iconSize: 12
                iconName: "close"
                tooltip: "Close the diff"
                onClicked: root.closed()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.surfaceSunken
            clip: true

            ListView {
                id: lines
                objectName: "diffRows"
                anchors.fill: parent
                visible: root.rows.length > 0
                model: root.rows
                clip: true
                reuseItems: true
                cacheBuffer: 600
                boundsBehavior: Flickable.StopAtBounds
                topMargin: Theme.s2
                bottomMargin: Theme.s2
                ScrollBar.vertical: WScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                ScrollBar.horizontal: WScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                contentWidth: width

                delegate: Item {
                    id: line
                    required property var modelData
                    width: lines.width
                    height: modelData.type === "hunk" ? Theme.denseRow + 6 : Theme.denseRow - 4

                    Rectangle {
                        anchors.fill: parent
                        color: root.fillFor(line.modelData.type)
                    }

                    Rectangle {
                        visible: line.modelData.type === "hunk"
                        anchors.fill: parent
                        color: Theme.background
                        Rectangle {
                            anchors { left: parent.left; right: parent.right; top: parent.top }
                            height: 1; color: Theme.borderSubtle
                        }
                    }

                    Row {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 0

                        Text {
                            width: 34
                            visible: line.modelData.type !== "hunk"
                            horizontalAlignment: Text.AlignRight
                            rightPadding: Theme.s2
                            text: line.modelData.old > 0 ? line.modelData.old : ""
                            color: Theme.textDisabled
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        }
                        Text {
                            width: 34
                            visible: line.modelData.type !== "hunk"
                            horizontalAlignment: Text.AlignRight
                            rightPadding: Theme.s2
                            text: line.modelData.new > 0 ? line.modelData.new : ""
                            color: Theme.textDisabled
                            font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        }
                        Text {
                            width: 12
                            visible: line.modelData.type !== "hunk"
                            horizontalAlignment: Text.AlignHCenter
                            text: root.signFor(line.modelData.type)
                            color: root.toneFor(line.modelData.type)
                            font.family: Theme.monoFamily; font.pixelSize: Theme.code
                        }
                        Text {
                            width: parent.width - (line.modelData.type === "hunk" ? Theme.s3 : 80)
                            leftPadding: line.modelData.type === "hunk" ? Theme.s3 : 0
                            text: line.modelData.text
                            textFormat: Text.PlainText
                            color: root.toneFor(line.modelData.type)
                            font.family: Theme.monoFamily
                            font.pixelSize: line.modelData.type === "hunk" ? Theme.micro : Theme.code
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            EmptyState {
                anchors.fill: parent
                visible: root.rows.length === 0
                iconName: root.dock && root.dock.diffError === "Loading…" ? "clock" : "info"
                title: root.dock && root.dock.diffError ? root.dock.diffError : "Nothing to show"
                detail: root.dock && root.dock.diffError === "Binary file"
                    ? "Wynxq does not render binary diffs." : ""
            }
        }
    }
}
