import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/*!
    Ways into a task, sitting under the composer.

    Compact text actions, not cards. Each one either fills the composer with a
    prompt or opens the tool it names — nothing here is decorative, and nothing
    is offered that the current task cannot actually use. Idle actions stay
    readable; glass appears only as interaction feedback.
*/
Item {
    id: root
    signal starterChosen(string prompt)
    signal commandInvoked(string action)
    signal modeRequested(string mode)

    readonly property string mode: bridge ? bridge.taskMode : "chat"
    readonly property bool hasProject: !!(bridge && bridge.projectPath)
    // A fresh task can promote itself into Work when a starter needs local
    // tools. A locked Chat task cannot, so it gets conversation-only openings
    // instead of dead buttons for capabilities that are deliberately absent.
    readonly property bool modeOpen: !!(bridge && !bridge.taskModeLocked)
    readonly property bool lockedChat: root.mode === "chat" && !root.modeOpen
    readonly property var recentTask: {
        var groups = bridge ? bridge.taskGroups : [];
        for (var g = 0; g < groups.length; g++) {
            var items = groups[g].items || [];
            for (var i = 0; i < items.length; i++)
                if (!bridge || items[i].id !== bridge.taskId) return items[i];
        }
        return null;
    }

    implicitHeight: flow.implicitHeight

    readonly property var actions: {
        var list = [];

        if (root.recentTask)
            list.push({ label: "Continue " + String(root.recentTask.title || "recent task"),
                        icon: "clock", command: "task:" + root.recentTask.id });

        if (root.lockedChat) {
            list.push({ label: "Explain a concept", icon: "chat",
                        prompt: "Explain this clearly and give me a practical example: " });
            list.push({ label: "Review some code", icon: "code",
                        prompt: "Review this code and tell me what you would change:\n\n" });
            list.push({ label: "Brainstorm", icon: "bolt",
                        prompt: "Help me brainstorm a few strong approaches for this: " });
            return list;
        }

        if (!root.hasProject)
            list.push({ label: "Open project", icon: "folder", command: "project", needs: "work" });
        else {
            list.push({ label: "Quick open", icon: "search", command: "palette", needs: "work" });
            list.push({ label: "Browse files", icon: "folderOpen", command: "files", needs: "work" });
        }

        list.push({ label: "Terminal", icon: "terminal", command: "terminal-panel", needs: "work" });

        if (root.hasProject)
            list.push({ label: "Explain this project", icon: "code", needs: "work",
                        prompt: "Inspect this project and explain how it is put together." });

        list.push({ label: "Read my screen", icon: "eye", needs: "work",
                    prompt: "What is on my screen? Help me with it." });

        list.push({ label: "Run a command", icon: "bolt", needs: "work",
                    prompt: "Check my disk space and explain what you find." });

        return list;
    }

    Flow {
        id: flow
        width: parent.width
        x: Math.max(0, (root.width - childrenRect.width) / 2)
        spacing: Theme.s1

        Repeater {
            model: root.actions
            delegate: AbstractButton {
                id: starter
                required property var modelData
                implicitHeight: 30
                implicitWidth: starterRow.implicitWidth + Theme.s3 * 2
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: modelData.label
                onClicked: {
                    if (modelData.needs && root.modeOpen)
                        root.modeRequested(modelData.needs);
                    if (modelData.command)
                        root.commandInvoked(modelData.command);
                    else
                        root.starterChosen(modelData.prompt);
                }
                background: GlassSurface {
                    radius: Theme.r2
                    solid: false
                    autoGlass: false
                    glassEnabled: starter.hovered || starter.down || starter.visualFocus
                    tint: starter.down ? Theme.glassTintStrong : Theme.glassTintHover
                    fillOpacity: starter.down ? 0.58
                               : starter.hovered ? 0.34
                               : starter.visualFocus ? 0.22 : 0.0
                    outlineVisible: starter.hovered || starter.down || starter.visualFocus
                    strongEdge: starter.hovered || starter.down
                    active: starter.visualFocus
                    sheen: starter.hovered || starter.down
                    edgeColor: starter.visualFocus ? Theme.accentEdge : Theme.glassEdge
                }
                contentItem: Row {
                    id: starterRow
                    anchors.centerIn: parent
                    spacing: Theme.s2
                    Icon {
                        name: starter.modelData.icon
                        ink: starter.hovered || starter.visualFocus
                             ? Theme.textPrimary : Theme.textMuted
                        width: 13; height: 13
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: starter.modelData.label
                        color: starter.hovered || starter.visualFocus
                               ? Theme.textPrimary : Theme.textSecondary
                        font.family: Theme.sansFamily
                        font.pixelSize: Theme.caption
                        font.weight: starter.hovered || starter.visualFocus ? Font.Medium : Font.Normal
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: Qt.PointingHandCursor }
            }
        }
    }
}
