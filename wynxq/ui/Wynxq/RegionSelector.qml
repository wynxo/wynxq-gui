import QtQuick
import QtQuick.Window

/*!
    Pick part of the screen to attach.

    The capture already happened; this only crops it. Drag to select, release
    to attach, Escape to cancel. Nothing new is captured while it is open.
*/
Window {
    id: selector
    objectName: "regionSelector"
    visible: bridge ? bridge.regionActive : false
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    title: "Select a region"

    // The captured image is in screen pixels; the window is in logical ones.
    readonly property real ratio: shot.paintedWidth > 0 && bridge
                                  ? bridge.regionWidth / shot.paintedWidth : 1
    readonly property real offsetX: (width - shot.paintedWidth) / 2
    readonly property real offsetY: (height - shot.paintedHeight) / 2

    QtObject {
        id: box
        property real startX: 0
        property real startY: 0
        property real endX: 0
        property real endY: 0
        property bool dragging: false
        readonly property real left: Math.min(startX, endX)
        readonly property real top: Math.min(startY, endY)
        readonly property real right: Math.max(startX, endX)
        readonly property real bottom: Math.max(startY, endY)
        readonly property real span: right - left
        readonly property real rise: bottom - top
        function reset() { dragging = false; startX = startY = endX = endY = 0; }
    }

    onVisibleChanged: {
        if (!visible) return;
        box.reset();
        selector.showFullScreen();
        selector.requestActivate();
    }

    Image {
        id: shot
        anchors.fill: parent
        source: bridge && bridge.regionImage ? "data:image/png;base64," + bridge.regionImage : ""
        fillMode: Image.PreserveAspectFit
        asynchronous: false
        smooth: true
    }

    // Everything outside the selection is dimmed, so the choice is obvious.
    Item {
        anchors.fill: parent
        readonly property color veil: Theme.alpha(Theme.background, 0.62)
        Rectangle {
            color: parent.veil
            x: 0; y: 0; width: selector.width
            height: box.dragging ? box.top : selector.height
        }
        Rectangle {
            visible: box.dragging
            color: parent.veil
            x: 0; y: box.top; width: box.left; height: box.rise
        }
        Rectangle {
            visible: box.dragging
            color: parent.veil
            x: box.right; y: box.top; width: selector.width - box.right; height: box.rise
        }
        Rectangle {
            visible: box.dragging
            color: parent.veil
            x: 0; y: box.bottom; width: selector.width; height: selector.height - box.bottom
        }
    }

    Rectangle {
        visible: box.dragging && box.span > 2 && box.rise > 2
        x: box.left; y: box.top
        width: box.span; height: box.rise
        color: "transparent"
        border.width: 1
        border.color: Theme.accent
    }

    Rectangle {
        visible: !box.dragging
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Theme.s8
        width: hint.implicitWidth + Theme.s6 * 2
        height: 44
        radius: Theme.rPill
        color: Theme.surfaceRaised
        border.width: 1
        border.color: Theme.borderStrong
        Text {
            id: hint
            anchors.centerIn: parent
            text: "Drag to select a region · Escape to cancel"
            color: Theme.textPrimary
            font.family: Theme.sansFamily
            font.pixelSize: Theme.label
        }
    }

    Text {
        visible: box.dragging && box.span > 40
        x: box.left; y: Math.max(0, box.top - 24)
        text: Math.round(box.span * selector.ratio) + " × " + Math.round(box.rise * selector.ratio)
        color: Theme.textPrimary
        font.family: Theme.monoFamily
        font.pixelSize: Theme.caption
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.CrossCursor
        onPressed: function(mouse) {
            box.startX = box.endX = mouse.x;
            box.startY = box.endY = mouse.y;
            box.dragging = true;
        }
        onPositionChanged: function(mouse) {
            if (!box.dragging) return;
            box.endX = mouse.x;
            box.endY = mouse.y;
        }
        onReleased: {
            if (!box.dragging || !bridge) return;
            box.dragging = false;
            if (box.span < 6 || box.rise < 6) { bridge.cancelRegion(); return; }
            bridge.cropRegion(Math.round((box.left - selector.offsetX) * selector.ratio),
                              Math.round((box.top - selector.offsetY) * selector.ratio),
                              Math.round(box.span * selector.ratio),
                              Math.round(box.rise * selector.ratio));
        }
    }

    Shortcut { sequences: ["Escape"]; onActivated: bridge && bridge.cancelRegion() }
}
