import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Sheet {
    id: sheet
    title: "Focused editor"
    subtitle: bridge && bridge.workspaceDock && bridge.workspaceDock.filePath
        ? (bridge.workspaceDock.file.relative || bridge.workspaceDock.file.name || bridge.workspaceDock.filePath)
        : "Open a file from the workspace"
    width: Math.min(Theme.focusEditorWidth, parent ? parent.width - Theme.s6 : Theme.focusEditorWidth)
    height: Math.min(760, parent ? parent.height - Theme.s6 : 760)
    signal askRequested()

    readonly property var dock: bridge ? bridge.workspaceDock : null

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        FileViewer {
            Layout.fillWidth: true
            Layout.fillHeight: true
            allowFocus: false
            onClosed: sheet.close()
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            color: Theme.backgroundSoft
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                height: 1; color: Theme.borderSubtle
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                spacing: Theme.s2

                Text {
                    Layout.fillWidth: true
                    text: !sheet.dock ? ""
                        : sheet.dock.fileModified ? "Unsaved edits · shared with the workspace editor"
                        : sheet.dock.changesSummary
                    color: sheet.dock && sheet.dock.fileModified ? Theme.warning : Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    elide: Text.ElideRight
                }

                WButton {
                    visible: !!(sheet.dock && sheet.dock.filePath)
                    text: "Ask Wynxq"
                    iconName: "chat"
                    variant: "primary"
                    compactPadding: true
                    onClicked: {
                        if (!bridge || !sheet.dock || !sheet.dock.filePath) return;
                        bridge.attachPath(sheet.dock.filePath);
                        sheet.askRequested();
                    }
                }
            }
        }
    }
}
