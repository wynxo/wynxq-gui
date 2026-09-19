import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    The one-line header every dock panel wears.

    Title on the left, a quiet detail beside it, actions on the right. Thin on
    purpose: the panel is 380px wide and the content is the point.
*/
Item {
    id: root
    property string title: ""
    property string detail: ""
    property string detailFont: "sans"        // "sans" or "mono"
    // Paths are cut at the front, prose at the end.
    property int detailElide: Text.ElideMiddle
    default property alias actions: actionRow.data

    implicitHeight: Theme.compact ? 32 : 34

    Rectangle {
        anchors.fill: parent
        color: Theme.backgroundSoft
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1
            color: Theme.borderSubtle
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.s3
        anchors.rightMargin: Theme.s1
        spacing: Theme.s2

        Text {
            text: root.title
            color: Theme.textSecondary
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
            font.weight: Font.Medium
            elide: Text.ElideRight
            Layout.maximumWidth: root.width * 0.5
        }

        Text {
            visible: root.detail !== ""
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: root.detail
            color: Theme.textMuted
            font.family: root.detailFont === "mono" ? Theme.monoFamily : Theme.sansFamily
            font.pixelSize: Theme.micro
            elide: root.detailElide
        }

        Item { Layout.fillWidth: !root.detail; Layout.minimumWidth: 0 }

        Row {
            id: actionRow
            Layout.alignment: Qt.AlignVCenter
            spacing: 0
        }
    }
}
