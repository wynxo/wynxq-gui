import QtQuick
import QtQuick.Controls

// One quiet, predictable scrollbar for every scrollable surface. The hover
// handler observes the viewport without consuming clicks or wheel events.
ScrollBar {
    id: control
    objectName: "wynxqScrollBar"
    property Item hoverTarget: parent
    readonly property bool viewportMoving: hoverTarget
        && ((hoverTarget.moving === true)
            || (hoverTarget.contentItem && hoverTarget.contentItem.moving === true))
    readonly property bool revealed: size < 1
        && (viewportHover.hovered || hovered || pressed || viewportMoving)

    policy: ScrollBar.AsNeeded
    hoverEnabled: true
    minimumSize: 0.04
    padding: 3
    implicitWidth: orientation === Qt.Vertical ? 12 : 40
    implicitHeight: orientation === Qt.Horizontal ? 12 : 40
    opacity: revealed ? 1 : 0
    Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast } }

    HoverHandler {
        id: viewportHover
        parent: control.hoverTarget
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
