import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Switch with a label and optional description, sized for comfortable hits.

    It never flips itself: `checked` stays bound to the setting, and a click
    only asks for the new value. If the controller refuses one, the switch
    keeps showing the truth instead of drifting out of sync with it.
*/
AbstractButton {
    id: root
    property string description: ""
    signal switched(bool value)

    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : Theme.disabledOpacity
    implicitHeight: Math.max(Theme.control, layout.implicitHeight)
    implicitWidth: 260
    Accessible.role: Accessible.CheckBox
    Accessible.name: text
    Accessible.description: description
    Accessible.checked: checked
    onClicked: root.switched(!root.checked)

    Behavior on opacity {
        enabled: !Theme.reducedMotion
        NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
    }

    background: Item {}

    contentItem: RowLayout {
        id: layout
        spacing: Theme.s4

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Text {
                Layout.fillWidth: true
                text: root.text
                color: Theme.textPrimary
                font.family: Theme.sansFamily; font.pixelSize: Theme.label
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                visible: root.description !== ""
                text: root.description
                color: Theme.textMuted
                font.family: Theme.sansFamily; font.pixelSize: Theme.caption
                wrapMode: Text.WordWrap; lineHeight: 1.35
            }
        }

        GlassSurface {
            Layout.preferredWidth: 38
            Layout.preferredHeight: 22
            Layout.alignment: Qt.AlignVCenter
            radius: height / 2
            scale: root.down ? Theme.pressScale : 1
            Behavior on scale {
                enabled: !Theme.reducedMotion
                NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
            }
            solid: true
            glassEnabled: root.checked || root.hovered || root.visualFocus
            tint: root.checked ? Theme.accent
                  : root.hovered ? Theme.glassTintHover : Theme.surfaceHover
            fillOpacity: root.checked ? (root.hovered ? 0.92 : 0.84)
                       : root.hovered ? 0.64 : 1.0
            active: root.visualFocus
            strongEdge: root.hovered || root.visualFocus
            sheen: root.checked || root.hovered || root.visualFocus
            edgeColor: root.visualFocus ? Theme.accentEdge
                     : root.checked ? Theme.alpha(Theme.textPrimary, 0.22)
                     : root.hovered ? Theme.glassEdgeStrong : Theme.borderSubtle

            Rectangle {
                width: 16; height: 16; radius: height / 2
                y: 3
                x: root.checked ? parent.width - width - 3 : 3
                color: root.checked ? Theme.onAccent : Theme.textSecondary
                border.width: 1
                border.color: root.checked
                              ? Theme.alpha(Theme.textInverse, 0.20)
                              : Theme.alpha(Theme.textPrimary, 0.16)
                Behavior on x { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.fast; easing.type: Theme.easing } }
                Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 2
                    height: 5
                    radius: 3
                    color: Theme.alpha(root.checked ? Theme.textInverse : Theme.textPrimary, 0.12)
                }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        cursorShape: Qt.PointingHandCursor
    }
}
