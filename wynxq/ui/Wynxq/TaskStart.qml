import QtQuick
import QtQuick.Layouts

/*!
    The fresh-task headline.

    Keep the first screen calm: one quiet runtime cue, one useful question and
    one short explanation. The composer is the visual centre of gravity.
*/
Item {
    id: root

    // Kept as a public property because preview scenes toggle it. The refined
    // home no longer adds decorative sculpture or activity data above the
    // composer; short and tall windows intentionally share the same hierarchy.
    property bool showSculpture: true

    function playEntrance() {
        if (Theme.reducedMotion) {
            column.opacity = 1;
            column.scale = 1;
            return;
        }
        column.opacity = 0;
        column.scale = 0.99;
        entrance.restart();
    }

    Component.onCompleted: Qt.callLater(root.playEntrance)

    ParallelAnimation {
        id: entrance
        NumberAnimation {
            target: column; property: "opacity"
            from: 0; to: 1; duration: Theme.slow; easing.type: Theme.easing
        }
        NumberAnimation {
            target: column; property: "scale"
            from: 0.99; to: 1; duration: Theme.slow; easing.type: Theme.easing
        }
    }

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
                ? "Project tools and commands are ready. Screen control is on when visual context is needed."
                : "Commands are ready. Screen control is on when visual context is needed.")
            : (hasProject
                ? "Project tools and commands are ready. Screen control stays off until you enable it."
                : "Commands are ready. Screen control stays off until you enable it.")

    implicitHeight: column.implicitHeight

    Accessible.role: Accessible.StaticText
    Accessible.name: root.modeLabel + ". " + root.headline + (root.detail ? ". " + root.detail : "")

    ColumnLayout {
        id: column
        width: parent.width
        spacing: Theme.s2

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s1
            Item { Layout.fillWidth: true }
            Rectangle {
                width: 5; height: 5; radius: 3
                color: bridge && bridge.online ? Theme.success : Theme.danger
            }
            Text {
                text: bridge && bridge.online
                    ? (bridge.modelShortName || "Ollama") + " · local"
                    : "Ollama offline"
                color: bridge && bridge.online ? Theme.textDisabled : Theme.danger
                font.family: Theme.monoFamily
                font.pixelSize: Theme.micro
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
            font.pixelSize: root.width < 560 ? 22 : 27
            font.weight: Font.Medium
            font.letterSpacing: -0.25
        }

        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            visible: root.detail !== ""
            text: root.detail
            color: Theme.textMuted
            font.family: Theme.sansFamily
            font.pixelSize: Theme.caption
            lineHeight: 1.3
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
}
