import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

/*!
    Approval for a single desktop action.

    Safety state is never hidden: the prompt names the exact action, shows its
    risk, and defaults to declining if it is dismissed or times out.
*/
Popup {
    id: prompt
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(480, parent ? parent.width - Theme.s6 : 480)
    height: Math.min(implicitHeight, parent ? parent.height - Theme.s6 : 600)
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.NoAutoClose
    visible: bridge ? bridge.permissionPending : false
    property bool showDetails: false
    property var returnFocusTo: null
    onAboutToShow: {
        var host = contentItem.Window.window;
        returnFocusTo = host ? host.activeFocusItem : null;
    }
    onOpened: denyButton.forceActiveFocus()
    onClosed: {
        showDetails = false;
        if (returnFocusTo && returnFocusTo.forceActiveFocus)
            returnFocusTo.forceActiveFocus();
        returnFocusTo = null;
    }
    // "destructive" is the one risk that survives Auto: a command that can take
    // something away for good. It is named, not merely tinted a warmer colour.
    readonly property bool destructive: bridge && bridge.permissionRisk === "destructive"
    readonly property bool sensitive: prompt.destructive || (bridge && bridge.permissionRisk === "sensitive")
    readonly property bool isCommand: !!(bridge && bridge.permissionCommand)

    Overlay.modal: Rectangle { color: Theme.scrim }

    background: Rectangle {
        radius: Theme.r4
        color: Theme.surface
        border.width: 1
        border.color: prompt.sensitive ? Theme.warning : Theme.borderStrong
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.reducedMotion ? 0 : Theme.base }
            NumberAnimation { property: "scale"; from: 0.98; to: 1; duration: Theme.reducedMotion ? 0 : Theme.base; easing.type: Theme.easing }
        }
    }

    contentItem: ColumnLayout {
        spacing: Theme.s4
        Accessible.role: Accessible.Dialog
        Accessible.name: "Allow this action? " + (bridge ? bridge.permissionSummary : "")

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.s5
            Layout.bottomMargin: 0
            spacing: Theme.s3
            Rectangle {
                Layout.preferredWidth: 32; Layout.preferredHeight: 32
                Layout.alignment: Qt.AlignTop
                radius: Theme.r2
                color: prompt.sensitive ? Theme.warningMuted : Theme.surfaceHover
                Icon {
                    anchors.centerIn: parent
                    name: prompt.destructive ? "warning"
                        : prompt.isCommand ? "terminal"
                        : prompt.sensitive ? "warning" : "cursor"
                    ink: prompt.sensitive ? Theme.warning : Theme.textSecondary
                    width: 17; height: 17
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: prompt.destructive ? "This command cannot be undone"
                        : prompt.isCommand ? "Wynxo wants to run a command"
                        : prompt.sensitive ? "Wynxo wants to change something"
                        : "Allow this action?"
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.heading
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: prompt.destructive
                          ? "It can delete files, change the system, or act as another user. Read it before you allow it."
                        : prompt.isCommand
                          ? "It runs as you, with your files and your permissions."
                        : prompt.sensitive
                          ? "This can save, send or delete in whatever has focus."
                          : "Wynxo wants to act on your desktop."
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                    wrapMode: Text.WordWrap
                }
            }
        }

        // Long commands and arguments scroll together. The decision row stays
        // outside this viewport, reachable even in a 560 x 520 window.
        ScrollView {
            id: bodyScroll
            objectName: "permissionReview"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 60
            Layout.preferredHeight: Math.min(320, review.implicitHeight)
            Layout.leftMargin: Theme.s5
            Layout.rightMargin: Theme.s5
            contentWidth: availableWidth
            contentHeight: review.implicitHeight
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: WScrollBar {}

            ColumnLayout {
                id: review
                width: bodyScroll.availableWidth
                spacing: Theme.s3

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: summary.implicitHeight + Theme.s3 * 2
                    radius: Theme.r2
                    color: Theme.surfaceSunken
                    border.width: 1
                    border.color: Theme.borderSubtle
                    TextArea {
                        id: summary
                        objectName: "permissionCommand"
                        anchors.fill: parent
                        anchors.margins: Theme.s3
                        padding: 0
                        text: prompt.isCommand ? bridge.permissionCommand
                                               : (bridge ? bridge.permissionSummary : "")
                        color: Theme.textPrimary
                        textFormat: TextEdit.PlainText
                        readOnly: true
                        selectByMouse: true
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.onAccent
                        font.family: prompt.isCommand ? Theme.monoFamily : Theme.sansFamily
                        font.pixelSize: prompt.isCommand ? Theme.code : Theme.label
                        wrapMode: TextEdit.WrapAnywhere
                        background: Item {}
                        Accessible.name: prompt.isCommand ? "Exact command" : "Requested action"
                    }
                }

                // Where it runs. A command means something different in the project
                // than in the home folder, so the prompt never leaves it implied.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.s2
                    visible: prompt.isCommand && !!bridge.permissionDirectory
                    Icon { name: "folderOpen"; ink: Theme.textDisabled; Layout.preferredWidth: 12; Layout.preferredHeight: 12 }
                    Text {
                        Layout.fillWidth: true
                        text: bridge ? bridge.permissionDirectory : ""
                        color: Theme.textMuted
                        font.family: Theme.monoFamily; font.pixelSize: Theme.micro
                        wrapMode: Text.WrapAnywhere
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.s2
                    visible: bridge && bridge.permissionDetail.length > 0

                    AbstractButton {
                        id: detailsToggle
                        Layout.preferredHeight: 24
                        Layout.preferredWidth: detailsRow.implicitWidth + Theme.s2 * 2
                        hoverEnabled: true
                        Accessible.name: detailsLabel.text
                        onClicked: prompt.showDetails = !prompt.showDetails
                        background: Rectangle {
                            radius: Theme.r1
                            color: detailsToggle.hovered ? Theme.surfaceHover : "transparent"
                            border.width: detailsToggle.visualFocus ? 2 : 0
                            border.color: Theme.accentEdge
                        }
                        contentItem: Row {
                            id: detailsRow
                            spacing: Theme.s2
                            leftPadding: Theme.s2
                            Icon {
                                name: prompt.showDetails ? "down" : "chevron"
                                ink: Theme.textMuted; width: 11; height: 11
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                id: detailsLabel
                                anchors.verticalCenter: parent.verticalCenter
                                text: prompt.showDetails ? "Hide exact arguments" : "Show exact arguments"
                                color: Theme.textMuted
                                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                            }
                        }
                        MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
                    }
                    TextArea {
                        Layout.fillWidth: true
                        visible: prompt.showDetails
                        text: bridge ? bridge.permissionDetail : ""
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        color: Theme.textSecondary
                        selectionColor: Theme.accent
                        selectedTextColor: Theme.onAccent
                        font.family: Theme.monoFamily; font.pixelSize: Theme.caption
                        wrapMode: TextEdit.WrapAnywhere
                        background: Item {}
                        Accessible.name: "Exact action arguments"
                    }
                }
            }
        }

        RowLayout {
            objectName: "permissionActions"
            Layout.fillWidth: true
            Layout.margins: Theme.s5
            Layout.topMargin: 0
            spacing: Theme.s2
            WButton {
                text: "Allow all in this task"
                variant: "ghost"
                compactPadding: true
                onClicked: if (bridge) bridge.allowRestOfTask()
                ToolTip.visible: hovered
                ToolTip.text: "Stop asking until this task finishes. A command that cannot be undone is still asked about."
            }
            Item { Layout.fillWidth: true }
            WButton {
                id: denyButton
                objectName: "permissionDeny"
                text: "Deny"
                variant: "secondary"
                onClicked: if (bridge) bridge.resolvePermission(false)
                ToolTip.visible: hovered
                ToolTip.text: "Deny · Esc"
            }
            WButton {
                objectName: "permissionAllow"
                text: prompt.isCommand ? "Run once" : "Allow once"
                variant: "primary"
                onClicked: if (bridge) bridge.resolvePermission(true)
            }
        }
    }

    // Escape is handled by the window shortcut so it works even when the
    // prompt has not taken focus yet.
}
