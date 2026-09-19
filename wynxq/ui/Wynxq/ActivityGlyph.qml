import QtQuick

/*!
    A tiny contribution-style activity mark.

    Six square cells carry transient work state without turning the interface
    into a loading-spinner collection. Green is reserved for progress/activity;
    reduced motion leaves the same readable static mark.
*/
Item {
    id: root
    property bool running: true
    property color tone: Theme.success
    property int phase: 0

    implicitWidth: grid.implicitWidth
    implicitHeight: grid.implicitHeight
    Accessible.ignored: true

    Timer {
        interval: 170
        repeat: true
        running: root.running && root.visible && !Theme.reducedMotion
        onTriggered: root.phase = (root.phase + 1) % 6
    }

    Grid {
        id: grid
        rows: 2
        flow: Grid.TopToBottom
        rowSpacing: 2
        columnSpacing: 2

        Repeater {
            model: 6
            delegate: Rectangle {
                id: cell
                required property int index
                readonly property int rawDistance: Math.abs(index - root.phase)
                readonly property int distance: Math.min(rawDistance, 6 - rawDistance)

                width: 5
                height: 5
                radius: 1.5
                color: root.tone
                opacity: !root.running || Theme.reducedMotion ? (0.28 + index * 0.07)
                    : distance === 0 ? 1.0 : distance === 1 ? 0.58 : 0.22
                scale: root.running && !Theme.reducedMotion && distance === 0 ? 1.08 : 1.0

                Behavior on opacity {
                    enabled: !Theme.reducedMotion
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }
                Behavior on scale {
                    enabled: !Theme.reducedMotion
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }
            }
        }
    }
}
