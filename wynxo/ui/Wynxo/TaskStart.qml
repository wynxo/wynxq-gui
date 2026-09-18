import QtQuick
import QtQuick.Layouts

/*!
    The fresh-task headline.

    Keep the first screen calm: one mode cue, one useful question, one short
    explanation. The composer remains the visual centre of gravity.
*/
Item {
    id: root

    property bool showSculpture: true

    readonly property string mode: bridge ? bridge.taskMode : "chat"
    readonly property bool hasProject: !!(bridge && bridge.projectPath)
    readonly property string modeLabel: mode === "work" ? "WORK" : "CHAT"
    readonly property string headline: mode === "work"
        ? "What should I handle?"
        : "What do you want to figure out?"
    readonly property string detail: mode === "chat"
        ? "Conversation only — no shell, workspace tools, or desktop control."
        : bridge && bridge.desktopEnabled
            ? (hasProject
                ? "Project tools and commands are available. Screen control is on and used only when the task needs visual context."
                : "Commands are available. Screen control is on and used only when the task needs visual context.")
            : (hasProject
                ? "Project tools and commands are available. Screen control is optional and stays off until you enable it."
                : "Commands are available. Screen control is optional and stays off until you enable it.")

    implicitHeight: column.implicitHeight

    Accessible.role: Accessible.StaticText
    Accessible.name: root.modeLabel + ". " + root.headline + (root.detail ? ". " + root.detail : "")

    ColumnLayout {
        id: column
        width: parent.width
        spacing: Theme.s2

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: root.showSculpture ? 138 : 0
            visible: root.showSculpture
            ChromeMark {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 158
                height: 138
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2

            Item { Layout.fillWidth: true }

            Rectangle {
                width: 5
                height: 5
                radius: 3
                color: Theme.accent
                Layout.alignment: Qt.AlignVCenter
            }

            Text {
                text: bridge && bridge.online
                    ? "LOCAL AI  ·  " + (bridge.modelShortName || "OLLAMA")
                    : "OLLAMA OFFLINE"
                color: bridge && bridge.online ? Theme.textMuted : Theme.danger
                font.family: Theme.monoFamily
                font.pixelSize: Theme.micro
                font.weight: Font.DemiBold
                font.letterSpacing: 1.0
            }

            Item { Layout.fillWidth: true }
        }

        Text {
            Layout.fillWidth: true
            text: root.headline
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.textPrimary
            font.family: Theme.sansFamily
            font.pixelSize: root.width < 560 ? 24 : 32
            font.weight: Font.Medium
            font.letterSpacing: -0.45
        }

        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            visible: root.detail !== ""
            text: root.detail
            color: Theme.textMuted
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
            lineHeight: 1.35
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
}
