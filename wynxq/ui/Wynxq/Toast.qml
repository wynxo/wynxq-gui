import QtQuick

/*! Transient confirmation. Bottom-centred, never blocking. */
Item {
    id: root
    property string message: ""
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: Theme.s7
    width: card.width
    height: card.height
    opacity: 0
    visible: opacity > 0
    z: 900
    Accessible.role: Accessible.StaticText
    Accessible.name: root.message

    function show(text) {
        root.message = text;
        root.opacity = 1;
        timer.restart();
    }

    Rectangle {
        id: card
        width: Math.min(label.implicitWidth + Theme.s5 * 2, root.parent ? root.parent.width - Theme.s7 * 2 : 480)
        height: 36
        radius: Theme.r2
        color: Theme.surfaceSelected
        border.width: 1
        border.color: Theme.borderStrong
        Text {
            id: label
            anchors.centerIn: parent
            width: Math.min(implicitWidth, parent.width - Theme.s5 * 2)
            horizontalAlignment: Text.AlignHCenter
            text: root.message
            color: Theme.textPrimary
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
            elide: Text.ElideRight
        }
    }

    transform: Translate { y: root.opacity > 0 ? 0 : 8 }
    Behavior on opacity { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.base; easing.type: Theme.easing } }
    Timer { id: timer; interval: 2600; onTriggered: root.opacity = 0 }
}
