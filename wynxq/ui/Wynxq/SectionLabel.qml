import QtQuick

/*! Quiet structural label shared by sidebars, sheets and activity groups. */
Text {
    color: Theme.textMuted
    font.family: Theme.sansFamily
    font.pixelSize: Theme.caption
    font.weight: Font.Medium
    font.letterSpacing: 0
    font.capitalization: Font.MixedCase
    elide: Text.ElideRight
}
