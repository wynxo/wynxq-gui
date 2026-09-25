import QtQuick
import QtQuick.Controls

// Reveal only at the scrollbar edge or during scrolling. Keep drag capture
// alive outside the viewport, and fade after wheel/keyboard movement settles.
ScrollBar {
    id: control
    objectName: "wynxqScrollBar"
    property Item hoverTarget: parent
    readonly property bool viewportMoving: hoverTarget
        && ((hoverTarget.moving === true)
            || (hoverTarget.contentItem && hoverTarget.contentItem.moving === true))
    readonly property bool revealed: size < 1
        && (hovered || edgeHover.hovered || pressed || viewportMoving || scrollFade.running)

    property bool initialized: false
    Component.onCompleted: initialized = true
    onPositionChanged: if (initialized) scrollFade.restart()
    Timer { id: scrollFade; interval: 650 }

    x: orientation === Qt.Vertical && parent ? parent.width - width : 0
    y: orientation === Qt.Horizontal && parent ? parent.height - height : 0
    width: orientation === Qt.Vertical ? implicitWidth : (parent ? parent.width : implicitWidth)
    height: orientation === Qt.Horizontal ? implicitHeight : (parent ? parent.height : implicitHeight)
    policy: ScrollBar.AsNeeded
    hoverEnabled: true
    minimumSize: 0.04
    padding: 3
    implicitWidth: orientation === Qt.Vertical ? 12 : 40
    implicitHeight: orientation === Qt.Horizontal ? 12 : 40
    opacity: revealed ? 1 : 0
    Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }

    HoverHandler {
        id: edgeHover
        parent: control
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
    }

    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: 3
        color: control.pressed ? Theme.textMuted : Theme.borderStrong
        opacity: control.hovered || control.pressed ? 1 : 0.65
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }
    }
    background: Item {}
}
