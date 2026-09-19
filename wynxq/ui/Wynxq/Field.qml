import QtQuick
import QtQuick.Controls

/*! Dense single-line field. Solid at rest; focus reveals the glass treatment. */
TextField {
    id: field
    property string iconName: ""
    property bool mono: false
    implicitHeight: Theme.control
    color: Theme.textPrimary
    placeholderTextColor: Theme.textMuted
    selectionColor: Theme.accent
    selectedTextColor: Theme.onAccent
    font.family: mono ? Theme.monoFamily : Theme.sansFamily
    font.pixelSize: Theme.label
    leftPadding: iconName ? Theme.s3 + 20 : Theme.s3
    rightPadding: Theme.s3
    selectByMouse: true
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : Theme.disabledOpacity
    Accessible.name: placeholderText

    Behavior on opacity {
        enabled: !Theme.reducedMotion
        NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
    }

    background: GlassSurface {
        radius: Theme.r2
        solid: true
        glassEnabled: field.activeFocus || field.hovered
        tint: field.activeFocus ? Theme.glassTintStrong
              : field.hovered ? Theme.glassTintHover : Theme.surfaceSunken
        fillOpacity: field.activeFocus ? 0.74
                   : field.hovered ? 0.60 : 1.0
        active: field.activeFocus
        strongEdge: field.activeFocus || field.hovered
        sheen: field.activeFocus || field.hovered
        edgeColor: field.activeFocus ? Theme.accentEdge
                 : field.hovered ? Theme.glassEdgeStrong : Theme.borderSubtle
    }

    Icon {
        visible: field.iconName !== ""
        name: field.iconName
        ink: field.activeFocus ? Theme.textSecondary : Theme.textMuted
        width: 13; height: 13
        x: Theme.s3
        anchors.verticalCenter: parent.verticalCenter
        Behavior on ink { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
    }
}
