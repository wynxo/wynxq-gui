import QtQuick

/*!
    The Wynxq mark: two open arcs around a solid core, matching the app icon.

    It is drawn, not animated. Identity is not a status indicator — when
    something is running, the interface says so in words.
*/
Canvas {
    id: mark
    property color tone: Theme.accent
    implicitWidth: 20
    implicitHeight: 20
    antialiasing: true
    Accessible.ignored: true   // Decorative; the wordmark beside it carries the name.

    onToneChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const c = getContext("2d");
        c.reset();
        const size = Math.min(width, height);
        c.scale(size / 64, size / 64);
        c.lineCap = "round";

        c.strokeStyle = Qt.rgba(tone.r, tone.g, tone.b, 0.92);
        c.lineWidth = 4.4;
        c.beginPath();
        c.arc(32, 32, 24, -Math.PI * 0.62, Math.PI * 1.24);
        c.stroke();

        // The inner arc runs the other way, which gives the mark a direction.
        c.strokeStyle = Qt.rgba(tone.r, tone.g, tone.b, 0.4);
        c.lineWidth = 3.4;
        c.beginPath();
        c.arc(32, 32, 15, Math.PI * 0.35, Math.PI * 1.72);
        c.stroke();

        c.fillStyle = tone;
        c.beginPath();
        c.arc(32, 32, 6, 0, Math.PI * 2);
        c.fill();
    }
}
