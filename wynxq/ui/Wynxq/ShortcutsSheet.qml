import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A reference sheet, not a settings page.

    Shortcuts are fixed, so there is nothing here to configure — only something
    to look up, from the command palette or the overflow menu. Two columns when
    there is room, so the whole list is on screen at once.
*/
Sheet {
    id: sheet
    title: "Keyboard"
    subtitle: "Active while Wynxq has focus"
    width: Math.min(700, parent ? parent.width - Theme.s7 : 700)
    // Hug the content: the sheet is a reference, so it should never scroll
    // unless the window itself is too short to hold it.
    height: Math.min(headerHeight + body.implicitHeight + Theme.s5 * 2,
                     parent ? parent.height - Theme.s7 : 620)

    readonly property int columns: width > 600 ? 2 : 1

    readonly property var sections: [
        { title: "Task", rows: [
            { keys: "Enter", label: "Send" },
            { keys: "Shift+Enter", label: "New line" },
            { keys: "Esc", label: "Stop — while Wynxq has focus" },
            { keys: "Ctrl+N", label: "New task" },
            { keys: "Ctrl+R", label: "Regenerate" },
            { keys: "Ctrl+D", label: "Duplicate task" },
        ]},
        { title: "Navigate", rows: [
            { keys: "Ctrl+K", label: "Search tasks" },
            { keys: "Alt+Up / Alt+Down", label: "Previous / next task" },
            { keys: "Ctrl+Shift+P", label: "Command palette" },
            { keys: "Ctrl+B", label: "Show or hide the sidebar" },
            { keys: "Ctrl+Space", label: "Quick bar" },
        ]},
        { title: "The workspace dock", rows: [
            { keys: "Ctrl+Shift+B", label: "Show or hide the dock panel" },
            { keys: "Ctrl+Shift+E", label: "Files" },
            { keys: "Ctrl+`", label: "Terminal" },
            { keys: "Ctrl+Shift+G", label: "Changes" },
            { keys: "Ctrl+Shift+K", label: "Context" },
            { keys: "Ctrl+Shift+M", label: "Memory" },
            { keys: "Ctrl+Shift+A", label: "Activity" },
            { keys: "Ctrl+Shift+W", label: "Browser" },
            { keys: "Ctrl+Shift+U", label: "Preview" },
            { keys: "Ctrl+L", label: "Focus the address bar — Browser only" },
        ]},
        { title: "File editor", rows: [
            { keys: "Ctrl+F", label: "Find in the open text file" },
            { keys: "Ctrl+G", label: "Go to line in the open text file" },
            { keys: "Ctrl+S", label: "Save the open file" },
        ]},
        { title: "While a run is on", rows: [
            { keys: "Esc", label: "Stop, from the Wynxq window" },
            { keys: "Desktop", label: "Stop from any window — see Settings → Agent" },
        ]},
        { title: "Context", rows: [
            { keys: "Ctrl+Shift+V", label: "Paste an image as context" },
        ]},
        { title: "Setup", rows: [
            { keys: "Ctrl+M", label: "Model manager" },
            { keys: "Ctrl+,", label: "Settings" },
        ]},
    ]

    ScrollView {
        anchors.fill: parent
        anchors.leftMargin: Theme.s5
        anchors.rightMargin: Theme.s5
        anchors.bottomMargin: Theme.s5
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: WScrollBar {}

        Column {
            id: body
            width: sheet.width - Theme.s5 * 2
            spacing: Theme.s5

            Grid {
                id: grid
                width: parent.width
                columns: sheet.columns
                columnSpacing: Theme.s6
                rowSpacing: Theme.s5
                readonly property real cellWidth: (width - columnSpacing * (columns - 1)) / columns

                Repeater {
                    model: sheet.sections
                    delegate: Column {
                        required property var modelData
                        width: grid.cellWidth
                        spacing: Theme.s2
                        SectionLabel { width: parent.width; text: modelData.title }
                        Repeater {
                            model: modelData.rows
                            delegate: Item {
                                required property var modelData
                                width: parent.width
                                height: 28
                                Text {
                                    anchors.left: parent.left
                                    anchors.right: keys.left
                                    anchors.rightMargin: Theme.s3
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.label
                                    color: Theme.textSecondary
                                    font.family: Theme.sansFamily; font.pixelSize: Theme.label
                                    elide: Text.ElideRight
                                }
                                KeyHint {
                                    id: keys
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    keys: modelData.keys
                                }
                            }
                        }
                    }
                }
            }

            Text {
                width: parent.width
                topPadding: Theme.s2
                text: "Linux gives applications no system-wide hotkey. To reach the quick bar from anywhere, bind your desktop's custom shortcut to “wynxq --quick”."
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                wrapMode: Text.WordWrap; lineHeight: 1.5
            }
        }
    }
}
