import QtQuick

/*! A keyboard shortcut, set once so every surface spells them the same way. */
Rectangle {
    id: hint
    property string keys: ""
    implicitWidth: label.implicitWidth + Theme.s2 + 2
    implicitHeight: 19
    radius: Theme.r1
    color: Theme.surfaceSunken
    border.width: 1
    border.color: Theme.borderSubtle
    visible: keys !== ""
    Accessible.ignored: true   // The control it labels already names its shortcut.

    Text {
        id: label
        anchors.centerIn: parent
        text: hint.keys
        color: Theme.textMuted
        font.family: Theme.sansFamily
        font.pixelSize: Theme.micro
        font.weight: Font.Medium
    }
}
