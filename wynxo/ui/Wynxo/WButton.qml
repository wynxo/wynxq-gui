import QtQuick
import QtQuick.Controls

/*! Compact tactile button with an opaque base and a glass reflection. */
Button {
    id: control
    property string variant: "secondary"
    property string iconName: ""
    property bool compactPadding: false

    readonly property bool isPrimary: variant === "primary"
    readonly property bool isGhost: variant === "ghost"
    readonly property bool isDanger: variant === "danger"
    readonly property bool interacting: hovered || down || visualFocus
    readonly property color ink: isPrimary ? Theme.onAccent
                               : isDanger ? Theme.danger
                               : isGhost ? (hovered ? Theme.textPrimary : Theme.textSecondary)
                               : Theme.textPrimary

    implicitHeight: Theme.control
    implicitWidth: row.implicitWidth + (compactPadding ? Theme.s3 : Theme.s4) * 2
    hoverEnabled: true
    opacity: enabled ? 1 : 0.42
    scale: down ? 0.97 : 1
    font.family: Theme.sansFamily
    font.pixelSize: Theme.label
    font.weight: Font.Medium
    Accessible.name: text || iconName

    Behavior on scale {
        enabled: !Theme.reducedMotion
        NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
    }

    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: control.text && control.iconName ? Theme.s2 : 0
            Icon {
                visible: control.iconName !== ""
                name: control.iconName
                ink: control.ink
                width: 14; height: 14
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: !!control.text
                text: control.text
                color: control.ink
                font: control.font
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    background: GlassSurface {
        radius: Theme.r2
        solid: !control.isGhost && !control.isDanger
        glassEnabled: control.interacting || (!control.isGhost && !control.isDanger)
        tint: control.isPrimary
              ? (control.down ? Qt.darker(Theme.accent, 1.08)
                 : control.hovered ? Theme.accentHover : Theme.accent)
              : control.isDanger ? Theme.danger
              : control.down ? Theme.glassTintStrong
              : control.hovered ? Theme.glassTintHover
              : Theme.surfaceRaised
        fillOpacity: control.isPrimary ? (control.interacting ? (control.down ? 0.82 : 0.88) : 1.0)
                   : control.isDanger ? (control.interacting ? 0.18 : 0.08)
                   : control.isGhost ? (control.interacting ? 0.46 : 0.0)
                   : control.down ? 0.72
                   : control.hovered ? 0.62 : 1.0
        outlineVisible: !control.isGhost || control.interacting
        strongEdge: control.interacting
        active: control.visualFocus
        elevated: control.isPrimary && control.hovered
        sheen: control.interacting || (!control.isGhost && !control.isDanger)
        edgeColor: control.visualFocus ? Theme.accentEdge
                 : control.isDanger ? Theme.alpha(Theme.danger, control.interacting ? 0.42 : 0.24)
                 : control.isPrimary ? Theme.alpha(Theme.textPrimary, control.interacting ? 0.18 : 0.10)
                 : control.interacting ? Theme.glassEdgeStrong : Theme.borderSubtle
    }
}
