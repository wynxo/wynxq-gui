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

    Rectangle {
        anchors.fill: parent
        radius: Theme.r2
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderSubtle
    }

    GlassSurface {
        y: 3; height: parent.height - 6
        radius: Theme.r1
        tint: Theme.surfaceSelected
        fillOpacity: 1
        glassEnabled: false
        sheen: false
        edgeColor: Theme.glassEdgeStrong
        width: root.segmentWidth
        x: 3 + root.segmentWidth * root.currentIndex
        Behavior on x { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.base; easing.type: Theme.easing } }
    }

    Row {
        id: row
        anchors.fill: parent
        anchors.margins: 3
        Repeater {
            id: repeater
            model: root.options
            delegate: AbstractButton {
                required property var modelData
                required property int index
                width: root.width > 0 ? root.segmentWidth : implicitWidth
                height: parent.height
                hoverEnabled: true
                text: modelData.label
                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.label
                Accessible.checked: index === root.currentIndex
                onClicked: root.selected(modelData.id)
                ToolTip.visible: hovered && !!modelData.detail
                ToolTip.text: modelData.detail || ""
                ToolTip.delay: 600

                background: Rectangle {
                    radius: Theme.r1
                    color: "transparent"
                    border.width: parent.visualFocus ? 2 : 0
                    border.color: Theme.accentEdge
                }
                contentItem: Text {
                    text: modelData.label
                    color: index === root.currentIndex ? Theme.textPrimary
                         : parent.hovered ? Theme.textSecondary : Theme.textMuted
                    font.family: Theme.sansFamily
                    font.pixelSize: Theme.caption
                    font.weight: index === root.currentIndex ? Font.DemiBold : Font.Medium
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    Behavior on color { enabled: !Theme.reducedMotion; ColorAnimation { duration: Theme.fast } }
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
