import QtQuick

/*! A single-stroke icon set drawn on canvas so it stays crisp at any size. */
Canvas {
    id: icon
    property string name: "plus"
    property color ink: Theme.textSecondary
    property real weight: 1.6
    implicitWidth: 20
    implicitHeight: 20
    antialiasing: true
    onNameChanged: requestPaint()
    onInkChanged: requestPaint()
    onWeightChanged: requestPaint()
    onPaint: {
        let c = getContext("2d"); c.reset();
        c.scale(width / 24, height / 24);
        c.strokeStyle = ink; c.fillStyle = ink; c.lineWidth = weight;
        c.lineCap = "round"; c.lineJoin = "round";
        function line(points) { c.beginPath(); c.moveTo(points[0][0], points[0][1]); for (let i = 1; i < points.length; i++) c.lineTo(points[i][0], points[i][1]); c.stroke(); }
        function rect(x, y, w, h, r) { if (r === undefined) r = 2; c.beginPath(); c.roundedRect ? c.roundedRect(x, y, w, h, r, r) : c.rect(x, y, w, h); c.stroke(); }
        function circle(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.stroke(); }
        function dot(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.fill(); }
        switch (name) {
        case "plus": line([[12,5],[12,19]]); line([[5,12],[19,12]]); break;
        case "search": circle(10.5,10.5,6); line([[15,15],[20,20]]); break;
        case "chat": line([[4,5],[20,5],[20,16],[11,16],[6,20],[6,16],[4,16],[4,5]]); break;
        case "desktop": rect(3,4,18,13); line([[8,21],[16,21]]); line([[12,17],[12,21]]); break;
        case "arrow": line([[12,19],[12,5]]); line([[6,11],[12,5],[18,11]]); break;
        case "chevron": line([[9,5],[16,12],[9,19]]); break;
        case "down": line([[6,9],[12,15],[18,9]]); break;
        case "up": line([[6,15],[12,9],[18,15]]); break;
        case "check": line([[5,12.5],[10,17.5],[19.5,6.5]]); break;
        case "close": line([[6,6],[18,18]]); line([[18,6],[6,18]]); break;
        case "stop": c.beginPath(); c.rect(7.5,7.5,9,9); c.fill(); break;
        case "copy": rect(8.5,8.5,11.5,12.5,2.5); line([[15,5.5],[15,3.5],[4,3.5],[4,15],[5.5,15]]); break;
        case "folder": line([[3,6.5],[9,6.5],[11,9],[21,9],[21,19.5],[3,19.5],[3,6.5]]); break;
        case "file": line([[6,3],[14,3],[19,8],[19,21],[6,21],[6,3]]); line([[14,3],[14,8],[19,8]]); break;
        case "code": line([[8.5,6],[3.5,12],[8.5,18]]); line([[15.5,6],[20.5,12],[15.5,18]]); line([[13.5,3.5],[10.5,20.5]]); break;
        case "paint": line([[14,4],[20,10],[11,19],[5,19],[5,13],[14,4]]); line([[11,7],[17,13]]); break;
        case "bolt": line([[13,2.5],[5.5,13],[11,13],[10.5,21.5],[18.5,10.5],[13,10.5],[13,2.5]]); break;
        case "sliders": line([[4,7],[9,7]]); line([[15,7],[20,7]]); circle(12,7,2.6); line([[4,17],[13,17]]); line([[19,17],[20,17]]); circle(16,17,2.6); break;
        case "edit": line([[4,20],[8.5,19],[19,8.5],[15,4.5],[4.5,15],[4,20]]); line([[13,6.5],[17,10.5]]); break;
        case "download": line([[12,3.5],[12,15]]); line([[7,10],[12,15],[17,10]]); line([[4,16.5],[4,20.5],[20,20.5],[20,16.5]]); break;
        case "trash": line([[4,6.5],[20,6.5]]); line([[9,6.5],[9,3.5],[15,3.5],[15,6.5]]); line([[6,6.5],[7,20.5],[17,20.5],[18,6.5]]); line([[10,10.5],[10,16.5]]); line([[14,10.5],[14,16.5]]); break;
        case "shield": line([[12,3],[20,6],[19,15],[12,21.5],[5,15],[4,6],[12,3]]); line([[8.5,12],[11,14.5],[15.5,9.5]]); break;
        case "cursor": line([[5.5,3.5],[19.5,13],[12.5,14],[10,21],[5.5,3.5]]); break;
        case "panel": rect(3,4,18,16,3); line([[15,4],[15,20]]); break;
        case "panelLeft": rect(3,4,18,16,3); line([[9,4],[9,20]]); break;
        case "sun": circle(12,12,4); for (let i = 0; i < 8; i++) { let a = i * Math.PI / 4; line([[12+6.6*Math.cos(a),12+6.6*Math.sin(a)],[12+9.4*Math.cos(a),12+9.4*Math.sin(a)]]); } break;
        case "pin": line([[9,3.5],[15,3.5],[14,9],[18.5,13],[13,13],[12,21],[11,13],[5.5,13],[10,9],[9,3.5]]); break;
        case "retry": line([[5,8],[5,3.5],[9.5,3.5]]); c.beginPath(); c.arc(12,12,8,-2.5,2.2); c.stroke(); break;
        case "duplicate": rect(8,8,12,13,2.5); line([[15.5,5],[4,5],[4,16.5]]); break;
        case "eye": line([[2.5,12],[6,7.5],[12,5.5],[18,7.5],[21.5,12],[18,16.5],[12,18.5],[6,16.5],[2.5,12]]); circle(12,12,3); break;
        case "image": rect(3,5,18,14,3); circle(8.5,10,1.8); line([[4,17],[9.5,12],[13,15],[16,12.5],[20,17]]); break;
        case "keyboard": rect(2.5,6,19,12,2.5); line([[6,10],[6,10]]); line([[6,10],[7,10]]); line([[10,10],[11,10]]); line([[14,10],[15,10]]); line([[17.5,10],[18,10]]); line([[8,14],[16,14]]); break;
        case "scroll": line([[12,4],[12,20]]); line([[8.5,7.5],[12,4],[15.5,7.5]]); line([[8.5,16.5],[12,20],[15.5,16.5]]); break;
        case "clock": circle(12,12,8.5); line([[12,7.5],[12,12],[15.5,14]]); break;
        case "launch": line([[13,4],[20,4],[20,11]]); line([[20,4],[11,13]]); line([[17,14.5],[17,20],[4,20],[4,7],[9.5,7]]); break;
        case "grid": rect(3.5,3.5,7,7,2); rect(13.5,3.5,7,7,2); rect(3.5,13.5,7,7,2); rect(13.5,13.5,7,7,2); break;
        case "crop": line([[6.5,2.5],[6.5,17.5],[21.5,17.5]]); line([[2.5,6.5],[17.5,6.5],[17.5,21.5]]); break;
        case "command": line([[9,9],[15,9],[15,15],[9,15],[9,9]]); circle(6.5,6.5,2.5); circle(17.5,6.5,2.5); circle(6.5,17.5,2.5); circle(17.5,17.5,2.5); break;
        case "folderOpen": line([[3,19.5],[3,6.5],[9,6.5],[11,9],[19,9],[19,11.5]]); line([[3,19.5],[6.5,11.5],[22,11.5],[18.5,19.5],[3,19.5]]); break;
        case "bug": rect(7,8,10,12,5); line([[7,12],[3.5,10]]); line([[7,16],[3.5,17.5]]); line([[17,12],[20.5,10]]); line([[17,16],[20.5,17.5]]); line([[9.5,8],[8.5,4.5]]); line([[14.5,8],[15.5,4.5]]); break;
        case "paperclip": line([[19,10.5],[10.5,19],[6.5,19],[4.5,15.5],[13.5,6],[16.5,6],[18,9],[9.5,17.5]]); break;
        case "camera": line([[3,8.5],[7.5,8.5],[9.5,5.5],[14.5,5.5],[16.5,8.5],[21,8.5],[21,19.5],[3,19.5],[3,8.5]]); circle(12,13.5,3.6); break;
        case "window": rect(3,4.5,18,15,3); line([[3,9],[21,9]]); dot(6.2,6.8,0.9); dot(9,6.8,0.9); break;
        case "memory": rect(6,6,12,12,2.5); rect(9.5,9.5,5,5,1); for (let m = 0; m < 3; m++) { let o = 8.5 + m * 3.5; line([[o,3],[o,6]]); line([[o,18],[o,21]]); line([[3,o],[6,o]]); line([[18,o],[21,o]]); } break;
        case "clipboard": line([[9,4.5],[6,4.5],[6,20.5],[18,20.5],[18,4.5],[15,4.5]]); rect(9,2.5,6,4,1.5); break;
        case "info": circle(12,12,8.5); line([[12,11],[12,16.5]]); dot(12,7.8,1); break;
        case "warning": line([[12,3.5],[21.5,20],[2.5,20],[12,3.5]]); line([[12,9.5],[12,14.5]]); dot(12,17.3,1); break;
        case "lock": rect(5,10.5,14,10,2.5); line([[8,10.5],[8,7.5],[12,4.5],[16,7.5],[16,10.5]]); break;
        case "terminal": rect(2.5,4.5,19,15,3); line([[6.5,10],[9.5,12.5],[6.5,15]]); line([[12,15.5],[17,15.5]]); break;
        case "more": dot(5.5,12,1.5); dot(12,12,1.5); dot(18.5,12,1.5); break;
        case "moreVertical": dot(12,5.5,1.5); dot(12,12,1.5); dot(12,18.5,1.5); break;
        case "branch": circle(6.5,5.5,2.5); circle(6.5,18.5,2.5); circle(17.5,9,2.5); line([[6.5,8],[6.5,16]]); line([[17.5,11.5],[17.5,13],[6.5,13]]); break;
        case "star": line([[12,3.5],[14.7,9.6],[21,10.4],[16.3,14.8],[17.6,21],[12,17.9],[6.4,21],[7.7,14.8],[3,10.4],[9.3,9.6],[12,3.5]]); break;
        case "starFilled": c.beginPath(); c.moveTo(12,3.5); c.lineTo(14.7,9.6); c.lineTo(21,10.4); c.lineTo(16.3,14.8); c.lineTo(17.6,21); c.lineTo(12,17.9); c.lineTo(6.4,21); c.lineTo(7.7,14.8); c.lineTo(3,10.4); c.lineTo(9.3,9.6); c.closePath(); c.fill(); break;
        case "layers": line([[12,3.5],[21,8],[12,12.5],[3,8],[12,3.5]]); line([[3,12],[12,16.5],[21,12]]); line([[3,16],[12,20.5],[21,16]]); break;
        case "save": line([[4,5.5],[4,20.5],[20,20.5],[20,9],[16.5,5.5],[4,5.5]]); rect(8,5.5,8,5,1); rect(7.5,14,9,6.5,1); break;
        case "globe": circle(12,12,8.5); line([[3.5,12],[20.5,12]]); line([[12,3.5],[9,7],[8.2,12],[9,17],[12,20.5],[15,17],[15.8,12],[15,7],[12,3.5]]); break;
        case "back": line([[11,5],[4,12],[11,19]]); line([[4,12],[20,12]]); break;
        case "forward": line([[13,5],[20,12],[13,19]]); line([[4,12],[20,12]]); break;
        case "panelRight": rect(3,4,18,16,3); line([[15,4],[15,20]]); break;
        case "chevronRight": line([[9.5,6.5],[15,12],[9.5,17.5]]); break;
        case "chevronDown": line([[6.5,9.5],[12,15],[17.5,9.5]]); break;
        case "filter": line([[3.5,5.5],[20.5,5.5]]); line([[6.5,12],[17.5,12]]); line([[9.5,18.5],[14.5,18.5]]); break;
        case "revert": line([[4,10],[4,5],[9,5]]); c.beginPath(); c.arc(12,13,7.6,-2.9,1.9); c.stroke(); break;
        case "filePlus": line([[6,3],[14,3],[19,8],[19,21],[6,21],[6,3]]); line([[14,3],[14,8],[19,8]]); line([[12.5,11.5],[12.5,17.5]]); line([[9.5,14.5],[15.5,14.5]]); break;
        case "folderPlus": line([[3,6.5],[9,6.5],[11,9],[21,9],[21,19.5],[3,19.5],[3,6.5]]); line([[12,11.5],[12,17]]); line([[9.2,14.2],[14.8,14.2]]); break;
        case "expand": line([[9.5,3.5],[3.5,3.5],[3.5,9.5]]); line([[14.5,20.5],[20.5,20.5],[20.5,14.5]]); line([[3.5,3.5],[9.5,9.5]]); line([[20.5,20.5],[14.5,14.5]]); break;
        case "collapse": line([[3.5,9.5],[9.5,9.5],[9.5,3.5]]); line([[20.5,14.5],[14.5,14.5],[14.5,20.5]]); line([[9.5,9.5],[3.5,3.5]]); line([[14.5,14.5],[20.5,20.5]]); break;
        case "activity": line([[2.5,12],[7,12],[9.5,5],[14,19],[16.5,12],[21.5,12]]); break;
        case "cpu": rect(5.5,5.5,13,13,2.5); rect(9.5,9.5,5,5,1); line([[12,5.5],[12,2.5]]); line([[12,18.5],[12,21.5]]); line([[5.5,12],[2.5,12]]); line([[18.5,12],[21.5,12]]); break;
        case "dot": dot(12,12,3); break;
        case "hidden": line([[3,3.5],[21,20.5]]); line([[2.5,12],[6,7.5],[12,5.5],[15.5,6.5]]); line([[19,9.5],[21.5,12],[18,16.5],[12,18.5],[8.5,17.5]]); break;
        case "wrap": line([[4,6],[20,6]]); line([[4,12],[16,12],[19,15],[16,18]]); line([[19,15],[9,15]]); line([[4,18],[6,18]]); break;
        case "menu": line([[4,7],[20,7]]); line([[4,12],[20,12]]); line([[4,17],[20,17]]); break;
        default: circle(12,12,7);
        }
    }
}
