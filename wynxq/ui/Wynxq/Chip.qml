import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    A compact token: an attached piece of context, or a small inline control.

    Chips stay visually solid/quiet at rest. Hover, press and keyboard focus
    reveal the shared interaction-only glass material.
*/
AbstractButton {
    id: chip
    property string iconName: ""
    property string subtitle: ""
    property bool removable: false
    property bool interactive: true
    property bool selected: false
    property color tone: selected ? Theme.accent : Theme.textMuted
    signal removed()

    readonly property bool interacting: (hovered && interactive) || down || visualFocus

    implicitHeight: Theme.controlSmall
    implicitWidth: layout.implicitWidth + leftPadding + rightPadding
    leftPadding: Theme.s2 + 2
    rightPadding: removable ? 2 : Theme.s2 + 2
    hoverEnabled: true
    enabled: interactive || removable
    focusPolicy: interactive ? Qt.StrongFocus : Qt.NoFocus
    Accessible.role: interactive ? Accessible.Button : Accessible.StaticText
    Accessible.name: subtitle ? text + ", " + subtitle : text
    ToolTip.delay: 500

    background: GlassSurface {
        radius: Theme.rPill
        solid: !chip.selected
        glassEnabled: chip.interacting
        tint: chip.selected ? Theme.accent
             : chip.interacting ? Theme.glassTintHover : Theme.surfaceRaised
        fillOpacity: chip.selected ? (chip.interacting ? 0.18 : 0.12)
                   : chip.interacting ? (chip.down ? 0.68 : 0.58) : 1.0
        strongEdge: chip.interacting
        active: chip.visualFocus
        sheen: chip.interacting
        edgeColor: chip.visualFocus ? Theme.accentEdge
                 : chip.selected ? Theme.alpha(Theme.accent, 0.34)
                 : chip.interacting ? Theme.glassEdgeStrong : Theme.borderSubtle
    }

    contentItem: RowLayout {
        id: layout
        spacing: Theme.s2

        Icon {
            visible: chip.iconName !== ""
            name: chip.iconName
            ink: chip.tone
            Layout.preferredWidth: 13; Layout.preferredHeight: 13
        }
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: chip.text
            color: chip.selected ? Theme.textPrimary : Theme.textSecondary
            font.family: Theme.sansFamily; font.pixelSize: Theme.caption
            elide: Text.ElideMiddle
            maximumLineCount: 1
        }
        Text {
            visible: chip.subtitle !== ""
            text: chip.subtitle
            color: Theme.textMuted
            font.family: Theme.sansFamily; font.pixelSize: Theme.micro
            elide: Text.ElideRight
            Layout.maximumWidth: 150
        }
        IconButton {
            visible: chip.removable
            Layout.preferredWidth: 22; Layout.preferredHeight: 22
            iconSize: 11
            iconName: "close"
            tooltip: "Remove " + chip.text
            onClicked: chip.removed()
        }
    }

    MouseArea {
        anchors.fill: parent
        anchors.rightMargin: chip.removable ? 26 : 0
        acceptedButtons: Qt.NoButton
        cursorShape: chip.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
    }
}
