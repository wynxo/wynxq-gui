import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    One confirmation dialog for the whole app: a sentence, an optional field,
    and two buttons that always sit in the same place.
*/
Sheet {
    id: root
    property string message: ""
    property string detail: ""            // A path or URL, set in mono.
    property string confirmText: "Confirm"
    property string confirmVariant: "primary"
    property bool withInput: false
    property alias inputText: field.text
    signal confirmed()

    width: Math.min(460, parent ? parent.width - Theme.s7 : 460)
    height: headerHeight + column.implicitHeight + Theme.s5 * 2

    function show() {
        open();
        if (withInput) { field.forceActiveFocus(); field.selectAll(); }
    }

    function commit() {
        if (withInput && field.text.trim().length === 0) return;
        root.confirmed();
        root.close();
    }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: Theme.s5
        anchors.rightMargin: Theme.s5
        anchors.bottomMargin: Theme.s5
        spacing: Theme.s4

        Text {
            Layout.fillWidth: true
            visible: root.message !== ""
            text: root.message
            color: Theme.textSecondary
            font.family: Theme.sansFamily; font.pixelSize: Theme.label
            wrapMode: Text.WordWrap; lineHeight: 1.45
        }

        Text {
            Layout.fillWidth: true
            visible: root.detail !== ""
            text: root.detail
            color: Theme.textMuted
            font.family: Theme.monoFamily; font.pixelSize: Theme.caption
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 3
            elide: Text.ElideRight
        }

        Field {
            id: field
            Layout.fillWidth: true
            visible: root.withInput
            Layout.preferredHeight: visible ? Theme.control + 6 : 0
            onAccepted: root.commit()
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.s1
            spacing: Theme.s2
            Item { Layout.fillWidth: true }
            WButton { text: "Cancel"; variant: "ghost"; onClicked: root.close() }
            WButton {
                text: root.confirmText
                variant: root.confirmVariant
                enabled: !root.withInput || field.text.trim().length > 0
                onClicked: root.commit()
            }
        }
    }
}
