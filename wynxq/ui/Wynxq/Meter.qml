import QtQuick

/*! A thin progress rail used for context usage and model downloads. */
Item {
    id: root
    property real value: 0
    property color tone: Theme.accent
    implicitHeight: 3
    implicitWidth: 120
    Accessible.role: Accessible.ProgressBar
    Accessible.name: Math.round(Math.max(0, Math.min(1, value)) * 100) + " percent"

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Theme.surfaceHover
    }
    Rectangle {
        height: parent.height
        width: parent.width * Math.max(0, Math.min(1, root.value))
        radius: height / 2
        color: root.value > 0.9 ? Theme.warning : root.tone
        Behavior on width { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.base; easing.type: Theme.easing } }
        Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.base } }
    }
}
