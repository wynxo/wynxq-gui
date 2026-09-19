import QtQuick
import QtQuick.Controls

/*!
    A small anchored surface for details that do not deserve a whole panel.
    The app underneath stays solid; opening the popover is the transient action
    that activates the glass treatment.
*/
Popup {
    id: popover
    default property alias body: holder.data
    property string preferredEdge: "below"
    property int gap: Theme.s2
    property alias title: heading.text

    padding: Theme.s4
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent | Popup.CloseOnPressOutside

    property real anchorX: 0
    function place() {
        if (!parent || !Overlay.overlay) return;
        // `implicitHeight` can stay tiny when a caller intentionally gives a
        // popover an explicit height. Placement must use the rendered extent,
        // otherwise an "above" popup only moves up by that tiny implicit value
        // and is clipped against the bottom of the window.
        var popupHeight = Math.max(Number(height) || 0, Number(implicitHeight) || 0);
        var below = parent.mapToItem(Overlay.overlay, 0, parent.height + gap);
        var above = parent.mapToItem(Overlay.overlay, 0, -popupHeight - gap);
        var wantAbove = preferredEdge === "above";
        if (wantAbove && above.y < 0 && below.y + popupHeight <= Overlay.overlay.height) wantAbove = false;
        else if (!wantAbove && below.y + popupHeight > Overlay.overlay.height && above.y >= 0) wantAbove = true;
        y = wantAbove ? -popupHeight - gap : parent.height + gap;

        var left = parent.mapToItem(Overlay.overlay, 0, 0).x;
        var wanted = anchorX;
        var overflow = left + wanted + width - Overlay.overlay.width + Theme.s2;
        if (overflow > 0) wanted -= overflow;
        x = Math.max(-left + Theme.s2, wanted);
    }

    onAboutToShow: place()

    background: GlassSurface {
        radius: Theme.r3
        tint: Theme.glassTintStrong
        fillOpacity: Theme.glassStrongOpacity
        glassEnabled: true
        backdropBlur: true
        blurAmount: 0.76
        elevated: true
        strongEdge: true
        sheen: true
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.reducedMotion ? 0 : Theme.fast }
            NumberAnimation { property: "scale"; from: 0.965; to: 1; duration: Theme.reducedMotion ? 0 : Theme.fast; easing.type: Theme.easing }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.reducedMotion ? 0 : Theme.fast } }

    contentItem: Item {
        implicitWidth: holder.implicitWidth
        implicitHeight: heading.height + (heading.visible ? Theme.s3 : 0) + holder.implicitHeight

        SectionLabel {
            id: heading
            width: parent.width
            visible: text !== ""
            height: visible ? implicitHeight : 0
        }
        Item {
            id: holder
            anchors.top: heading.bottom
            anchors.topMargin: heading.visible ? Theme.s3 : 0
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
        }
    }
}
