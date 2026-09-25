import QtQuick

Column {
    property string title: ""
    property string description: ""
    default property alias groupBody: holder.data
    width: parent ? parent.width : 400
    spacing: Theme.s2

    Text {
        text: parent.title
        color: Theme.textPrimary
        font.family: Theme.sansFamily
        font.pixelSize: Theme.heading
        font.weight: Font.DemiBold
    }
    Text {
        width: parent.width
        visible: parent.description !== ""
        text: parent.description
        color: Theme.textMuted
        font.family: Theme.sansFamily
        font.pixelSize: Theme.caption
        wrapMode: Text.WordWrap
        lineHeight: 1.35
        bottomPadding: 2
    }
    Column {
        id: holder
        width: parent.width
        spacing: Theme.s2
    }
}
