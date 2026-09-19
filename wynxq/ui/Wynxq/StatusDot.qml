import QtQuick

/*! A status dot that never relies on colour alone: it also pulses or stills. */
Item {
    id: root
    property color tone: Theme.success
    property bool pulsing: false
    implicitWidth: 7
    implicitHeight: 7
    Accessible.ignored: true   // The label beside it carries the state in words.

    Rectangle {
        id: halo
        anchors.centerIn: parent
        width: parent.width * 2.6; height: width; radius: width / 2
        color: Theme.alpha(root.tone, 0.16)
        opacity: root.pulsing ? 1 : 0
        visible: opacity > 0
        SequentialAnimation on scale {
            running: root.pulsing && !Theme.reducedMotion
            loops: Animation.Infinite
            NumberAnimation { from: 0.75; to: 1.1; duration: 1100; easing.type: Easing.InOutQuad }
            NumberAnimation { from: 1.1; to: 0.75; duration: 1100; easing.type: Easing.InOutQuad }
        }
        Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.base } }
    }
    Rectangle {
        anchors.centerIn: parent
        width: parent.width; height: width; radius: width / 2
        color: root.tone
        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.base } }
    }
}
