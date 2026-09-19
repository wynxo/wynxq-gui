import QtQuick
import QtQuick.Controls

/*! Square icon-only control. Resting state is flat; glass is interaction feedback. */
Button {
    id: control
    property string iconName: "plus"
    property color tint: Theme.textSecondary
    property color activeTint: Theme.textPrimary
    property bool active: false
    property real iconSize: Math.round(width * 0.46)
    property real iconWeight: iconSize <= 13 ? 2.0 : 1.6
    property string tooltip: ""
    property string shortcut: ""
    readonly property bool interacting: hovered || down || visualFocus

    implicitWidth: Theme.control
    implicitHeight: Theme.control
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : 0.34

    // Hover scaling made dense toolbars look like they were wobbling as the
    // pointer crossed them. Keep the control geometrically stable and reserve
    // motion for the physical press itself.
    scale: down ? 0.96 : 1
    Accessible.name: tooltip || iconName

    Behavior on scale {
        enabled: !Theme.reducedMotion
        NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
    }
    Behavior on opacity {
        enabled: !Theme.reducedMotion
        NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
    }

    ToolTip.visible: hovered && enabled && tooltip.length > 0
    ToolTip.text: shortcut ? tooltip + " · " + shortcut : tooltip
    ToolTip.delay: 500

    contentItem: Item {
        Icon {
            name: control.iconName
            ink: control.active || control.hovered || control.visualFocus
                 ? control.activeTint : control.tint
            weight: control.iconWeight
            width: control.iconSize; height: control.iconSize
            anchors.centerIn: parent
            Behavior on ink { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
        }
    }

    background: GlassSurface {
        radius: Theme.r2
        solid: false
        glassEnabled: control.interacting
        tint: control.active ? Theme.accent
             : control.down ? Theme.glassTintStrong
             : control.hovered || control.visualFocus ? Theme.glassTintHover : Theme.glassTint
        fillOpacity: control.down ? 0.72
                   : control.hovered ? 0.52
                   : control.visualFocus ? 0.42
                   : control.active ? 0.12 : 0.0
        outlineVisible: control.interacting || control.active
        strongEdge: control.interacting
        active: control.visualFocus
        sheen: control.interacting
        edgeColor: control.visualFocus ? Theme.accentEdge
                 : control.active && !control.interacting ? Theme.alpha(Theme.accent, 0.28)
                 : control.interacting ? Theme.glassEdgeStrong : "transparent"
    }
}
