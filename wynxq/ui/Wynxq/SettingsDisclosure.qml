import QtQuick
import QtQuick.Controls

Column {
    id: disclosure
    property string title: ""
    property string hint: ""
    property bool expanded: false
    default property alias disclosureBody: inner.data
    width: parent ? parent.width : 400
    spacing: Theme.s3

    AbstractButton {
        id: toggle
        width: parent.width
        implicitHeight: Theme.control
        hoverEnabled: true
        Accessible.name: disclosure.title
        onClicked: disclosure.expanded = !disclosure.expanded
        scale: down ? Theme.pressScale : 1

        Behavior on scale {
            enabled: !Theme.reducedMotion
            NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
        }

        background: GlassSurface {
            radius: Theme.r2
            solid: false
            glassEnabled: toggle.hovered || toggle.down || toggle.visualFocus
            tint: toggle.down ? Theme.glassTintStrong : Theme.glassTintHover
            fillOpacity: toggle.down ? 0.56
                       : toggle.hovered ? 0.42
                       : toggle.visualFocus ? 0.30 : 0.0
            outlineVisible: toggle.visualFocus
            strongEdge: toggle.visualFocus
            active: toggle.visualFocus
            sheen: toggle.hovered || toggle.down
            edgeColor: toggle.visualFocus ? Theme.accentEdge : "transparent"
        }

        contentItem: Row {
            spacing: Theme.s2
            Icon {
                name: disclosure.expanded ? "down" : "chevron"
                ink: Theme.textSecondary
                width: 13
                height: 13
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: disclosure.title
                color: Theme.textPrimary
                font.family: Theme.sansFamily
                font.pixelSize: Theme.heading
                font.weight: Font.DemiBold
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.NoButton
            cursorShape: Qt.PointingHandCursor
        }
    }

    Text {
        width: parent.width
        visible: disclosure.expanded && disclosure.hint !== ""
        text: disclosure.hint
        color: Theme.textMuted
        font.family: Theme.sansFamily
        font.pixelSize: Theme.caption
        wrapMode: Text.WordWrap
        lineHeight: 1.5
    }

    Column {
        id: inner
        width: parent.width
        spacing: Theme.s3
        visible: disclosure.expanded
        height: visible ? implicitHeight : 0
    }
}
