import QtQuick
import QtQuick.Controls

/*! Segmented selector with a sliding indicator. Model entries: {id,label,detail}. */
Item {
    id: root
    property var options: []
    property string current: ""
    signal selected(string value)

    implicitHeight: Theme.control
    implicitWidth: row.implicitWidth + 6
    Accessible.role: Accessible.Grouping

    readonly property int currentIndex: {
        for (var i = 0; i < options.length; i++)
            if (options[i].id === current) return i;
        return 0;
    }
    readonly property real segmentWidth: repeater.count > 0 ? (width - 6) / repeater.count : 0

    GlassSurface {
        anchors.fill: parent
        radius: Theme.r2
        tint: Theme.surface
        fillOpacity: 1
        solid: true
        glassEnabled: false
        sheen: false
        edgeColor: Theme.borderSubtle
    }

    GlassSurface {
        y: 3
        height: parent.height - 6
        width: root.segmentWidth
        x: 3 + root.segmentWidth * root.currentIndex
        radius: Theme.r1
        tint: Theme.surfaceSelected
        fillOpacity: 1
        solid: true
        glassEnabled: false
        sheen: false
        edgeColor: Theme.glassEdgeStrong
        Behavior on x {
            enabled: !Theme.reducedMotion
            NumberAnimation { duration: Theme.base; easing.type: Theme.easing }
        }
    }

    Row {
        id: row
        anchors.fill: parent
        anchors.margins: 3

        Repeater {
            id: repeater
            model: root.options

            delegate: AbstractButton {
                id: segment
                required property var modelData
                required property int index
                width: root.width > 0 ? root.segmentWidth : implicitWidth
                height: parent.height
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                text: modelData.label
                scale: down ? Theme.pressScale : 1

                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.label
                Accessible.checked: index === root.currentIndex
                onClicked: root.selected(modelData.id)

                ToolTip.visible: hovered && !!modelData.detail
                ToolTip.text: modelData.detail || ""
                ToolTip.delay: Theme.tooltipDelay

                Behavior on scale {
                    enabled: !Theme.reducedMotion
                    NumberAnimation { duration: Theme.fast; easing.type: Theme.easing }
                }

                background: GlassSurface {
                    radius: Theme.r1
                    solid: false
                    glassEnabled: segment.hovered || segment.down || segment.visualFocus
                    tint: segment.down ? Theme.glassTintStrong : Theme.glassTintHover
                    fillOpacity: segment.down ? 0.46
                               : segment.hovered ? 0.28
                               : segment.visualFocus ? 0.20 : 0.0
                    outlineVisible: segment.visualFocus
                    strongEdge: segment.visualFocus
                    active: segment.visualFocus
                    sheen: segment.hovered || segment.down
                    edgeColor: segment.visualFocus ? Theme.accentEdge : "transparent"
                }

                contentItem: Text {
                    text: segment.modelData.label
                    color: segment.index === root.currentIndex ? Theme.textPrimary
                         : segment.hovered ? Theme.textSecondary : Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    font.weight: segment.index === root.currentIndex ? Font.DemiBold : Font.Medium
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    Behavior on color {
                        enabled: !Theme.reducedMotion
                        ColorAnimation { duration: Theme.fast }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.NoButton
                    cursorShape: Qt.PointingHandCursor
                }
            }
        }
    }
}
