import QtQuick

/*! A cached vector sculpture. Pointer feedback only; no idle animation. */
Item {
    id: root
    implicitWidth: 144
    implicitHeight: 144
    Accessible.ignored: true

    Image {
        anchors.fill: parent
        source: Qt.resolvedUrl("../../assets/wynxo-chrome.svgz")
        sourceSize.width: Math.ceil(root.width * 2)
        sourceSize.height: Math.ceil(root.height * 2)
        fillMode: Image.PreserveAspectFit
        smooth: true
        asynchronous: true
        rotation: !Theme.reducedMotion && pointer.hovered
            ? (pointer.point.position.x / Math.max(1, root.width) - 0.5) * 10 : 0
        Behavior on rotation {
            enabled: !Theme.reducedMotion
            NumberAnimation { duration: Theme.slow; easing.type: Theme.easing }
        }
    }
    HoverHandler { id: pointer }
}
