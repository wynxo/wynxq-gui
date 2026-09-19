import QtQuick
import QtQuick.Controls

/*!
    Styled dropdown. The closed app stays solid; opening a menu is itself a
    transient interaction, so the popup may use the glass material while it is
    visible. Menu rows only glass on hover/keyboard highlight.
*/
Popup {
    id: menu
    property var items: []
    property int itemHeight: 32
    property int menuWidth: 232
    property string preferredEdge: "below"
    property int gap: Theme.s1
    signal picked(string id)

    padding: Theme.s1
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent | Popup.CloseOnPressOutside
    width: menuWidth
    implicitHeight: listHeight + Theme.s1 * 2

    readonly property int listHeight: {
        var total = 0;
        for (var i = 0; i < items.length; i++) {
            if (items[i].hidden) continue;
            total += items[i].separator ? 9 : (items[i].detail ? itemHeight + 14 : itemHeight);
        }
        return total;
    }
    readonly property var visibleItems: {
        var out = [];
        for (var i = 0; i < items.length; i++)
            if (!items[i].hidden && !items[i].separator && !items[i].disabled) out.push(items[i].id);
        return out;
    }
    property string highlighted: ""

    property real anchorX: 0
    function place() {
        if (!parent || !Overlay.overlay) return;
        var below = parent.mapToItem(Overlay.overlay, 0, parent.height + gap);
        var above = parent.mapToItem(Overlay.overlay, 0, -implicitHeight - gap);
        var wantAbove = preferredEdge === "above";
        if (wantAbove && above.y < 0 && below.y + implicitHeight <= Overlay.overlay.height) wantAbove = false;
        else if (!wantAbove && below.y + implicitHeight > Overlay.overlay.height && above.y >= 0) wantAbove = true;
        y = wantAbove ? -implicitHeight - gap : parent.height + gap;

        var left = parent.mapToItem(Overlay.overlay, 0, 0).x;
        var wanted = anchorX;
        var overflow = left + wanted + width - Overlay.overlay.width + Theme.s2;
        if (overflow > 0) wanted -= overflow;
        x = Math.max(-left + Theme.s2, wanted);
    }

    onAboutToShow: { highlighted = ""; place(); }

    background: GlassSurface {
        radius: Theme.r3
        tint: Theme.glassTintStrong
        fillOpacity: Theme.glassStrongOpacity
        glassEnabled: true
        backdropBlur: true
        blurAmount: 0.78
        elevated: true
        strongEdge: true
        sheen: true
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.fast }
            NumberAnimation { property: "scale"; from: 0.965; to: 1; duration: Theme.fast; easing.type: Theme.easing }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.fast } }

    function step(delta) {
        var order = visibleItems;
        if (!order.length) return;
        var at = order.indexOf(highlighted);
        highlighted = order[Math.max(0, Math.min(order.length - 1, at < 0 ? 0 : at + delta))];
    }

    contentItem: Column {
        spacing: 0
        focus: true
        Keys.onDownPressed: menu.step(1)
        Keys.onUpPressed: menu.step(-1)
        Keys.onReturnPressed: if (menu.highlighted) { menu.picked(menu.highlighted); menu.close(); }
        Keys.onEnterPressed: if (menu.highlighted) { menu.picked(menu.highlighted); menu.close(); }
        Repeater {
            model: menu.items
            delegate: Loader {
                required property var modelData
                width: menu.menuWidth - Theme.s1 * 2
                active: !modelData.hidden
                sourceComponent: modelData.separator ? separatorItem : entryItem
                onLoaded: if (!modelData.separator) item.entry = modelData
            }
        }
    }

    Component {
        id: separatorItem
        Item {
            height: 9
            Rectangle {
                anchors.centerIn: parent
                width: parent.width - Theme.s3; height: 1
                color: Theme.borderSubtle
            }
        }
    }

    Component {
        id: entryItem
        GlassSurface {
            property var entry: ({})
            readonly property bool on: area.containsMouse || menu.highlighted === entry.id
            readonly property real textLeft: entry.icon ? Theme.s3 + 14 + Theme.s3 : Theme.s3
            height: entry.detail ? menu.itemHeight + 14 : menu.itemHeight
            radius: Theme.r2
            solid: false
            glassEnabled: on && !entry.disabled
            tint: entry.checked ? Theme.accent : Theme.glassTintHover
            fillOpacity: on && !entry.disabled ? 0.52 : entry.checked ? 0.12 : 0.0
            outlineVisible: on && !entry.disabled
            strongEdge: on && !entry.disabled
            sheen: on && !entry.disabled
            opacity: entry.disabled ? 0.4 : 1

            Icon {
                visible: !!entry.icon
                x: Theme.s3
                anchors.verticalCenter: parent.verticalCenter
                name: entry.icon || "chat"
                ink: entry.danger ? Theme.danger
                   : entry.checked ? Theme.textPrimary : Theme.textSecondary
                width: 14; height: 14
            }
            Column {
                x: parent.textLeft
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - x
                       - (keys.visible ? keys.width + Theme.s3 * 2
                          : tick.visible ? tick.width + Theme.s3 * 2 : Theme.s3)
                spacing: 1
                Text {
                    width: parent.width
                    text: entry.label || ""
                    color: entry.danger ? Theme.danger : Theme.textPrimary
                    font.family: Theme.sansFamily; font.pixelSize: Theme.label
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    visible: !!entry.detail
                    text: entry.detail || ""
                    color: Theme.textMuted
                    font.family: Theme.sansFamily; font.pixelSize: Theme.micro
                    elide: Text.ElideRight
                }
            }
            Icon {
                id: tick
                visible: !!entry.checked
                anchors.right: parent.right; anchors.rightMargin: Theme.s3
                anchors.verticalCenter: parent.verticalCenter
                name: "check"; ink: Theme.textMuted
                width: 12; height: 12
            }
            KeyHint {
                id: keys
                anchors.right: parent.right; anchors.rightMargin: Theme.s2
                anchors.verticalCenter: parent.verticalCenter
                keys: entry.shortcut || ""
            }
            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                enabled: !entry.disabled
                cursorShape: Qt.PointingHandCursor
                onClicked: { menu.picked(entry.id); menu.close(); }
            }
            Accessible.role: Accessible.MenuItem
            Accessible.name: entry.label || ""
        }
    }
}
