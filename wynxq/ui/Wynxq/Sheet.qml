import QtQuick
import QtQuick.Controls
import QtQuick.Window

/*!
    Compact modal panel. The underlying workspace remains fully solid; the
    modal's open/close transition is the interaction that earns the glass.
*/
Popup {
    id: sheet
    property string title: ""
    property string subtitle: ""
    default property alias body: holder.data
    readonly property int headerHeight: title ? (subtitle ? 62 : 52) : 0

    anchors.centerIn: Overlay.overlay
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    property var returnFocusTo: null
    onAboutToShow: {
        var host = contentItem ? contentItem.Window.window : null;
        returnFocusTo = host ? host.activeFocusItem : null;
    }
    onClosed: {
        if (returnFocusTo && returnFocusTo.forceActiveFocus)
            returnFocusTo.forceActiveFocus();
        returnFocusTo = null;
    }

    Overlay.modal: Rectangle { color: Theme.scrim }

    background: GlassSurface {
        radius: Theme.r4
        tint: Theme.glassTintStrong
        fillOpacity: 0.92
        glassEnabled: true
        backdropBlur: true
        blurAmount: 0.70
        elevated: true
        strongEdge: true
        sheen: true
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.reducedMotion ? 0 : Theme.base; easing.type: Theme.easing }
            NumberAnimation { property: "scale"; from: 0.98; to: 1; duration: Theme.reducedMotion ? 0 : Theme.base; easing.type: Theme.easing }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.reducedMotion ? 0 : Theme.fast } }

    contentItem: Item {
        implicitWidth: holder.implicitWidth
        implicitHeight: header.height + holder.implicitHeight
        Accessible.role: Accessible.Dialog
        Accessible.name: sheet.title

        Item {
            id: header
            width: parent.width
            height: sheet.headerHeight
            visible: height > 0

            Column {
                anchors.left: parent.left; anchors.leftMargin: Theme.s5
                anchors.right: closeButton.left; anchors.rightMargin: Theme.s3
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    width: parent.width
                    text: sheet.title
                    color: Theme.textPrimary
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.heading
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    visible: sheet.subtitle !== ""
                    text: sheet.subtitle
                    color: Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    elide: Text.ElideRight
                }
            }

            IconButton {
                id: closeButton
                anchors.right: parent.right; anchors.rightMargin: Theme.s3
                anchors.verticalCenter: parent.verticalCenter
                iconName: "close"; tooltip: "Close"; shortcut: "Esc"
                onClicked: sheet.close()
            }

            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                height: 1; color: Theme.borderSubtle
            }
        }

        Item {
            id: holder
            anchors.top: header.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
        }
    }
}
