import QtQuick
import QtQuick.Controls

/*!
    The task: one column, one comfortable reading measure.

    Auto-scroll follows the newest output only while you are already at the
    bottom. Scroll up and it stops, immediately and for good, until you come
    back down or ask to jump — reading earlier output is never interrupted.
*/
ListView {
    id: list
    property bool following: true
    signal linkClicked(string link)

    clip: true
    spacing: Theme.s4
    topMargin: Theme.s5
    bottomMargin: Theme.s5
    boundsBehavior: Flickable.StopAtBounds
    cacheBuffer: 1200
    reuseItems: true

    // positionViewAtEnd exposes the last item, while atYEnd also includes the
    // empty bottom margin. Both positions mean the reader has reached the end.
    readonly property bool atBottom: atYEnd || contentHeight + topMargin + bottomMargin <= height
        || contentY + height >= originY + contentHeight - 1

    ScrollBar.vertical: WScrollBar {
        policy: ScrollBar.AsNeeded
        onPressedChanged: {
            if (pressed) list.following = false;
            else list.following = list.atBottom;
        }
    }

    onMovementStarted: following = false
    onMovementEnded: following = atBottom
    // ListView estimates heights until its delegates are laid out. Following
    // synchronously from contentHeightChanged can use that old estimate and
    // leave the actual last message out of view. Coalesce after layout instead.
    onContentHeightChanged: scheduleFollow()
    onCountChanged: scheduleFollow()
    onHeightChanged: scheduleFollow()
    onWidthChanged: scheduleFollow()
    onVisibleChanged: if (visible) scheduleFollow()

    function followTail() {
        if (!following || !visible || height <= 0) return;
        forceLayout();
        positionViewAtEnd();
    }
    function scheduleFollow() { if (following) Qt.callLater(followTail); }
    function jumpToEnd() { following = true; scheduleFollow(); }

    delegate: Item {
        id: rowItem
        required property int index
        required property string kind
        required property string body
        required property string thought
        required property var blocks
        required property string tail
        required property string tailKind
        required property string tailLanguage
        required property string tailLabel
        required property var steps
        required property var attachments
        required property bool streaming
        required property real thinkSeconds
        required property bool thinkDone
        readonly property bool wideAnswer: {
            if (kind !== "assistant") return false;
            if (tailKind === "code") return true;
            var items = blocks || [];
            for (var i = 0; i < items.length; i++)
                if (items[i].kind === "code") return true;
            var prose = String(body || "") + "\n" + String(tail || "");
            return prose.indexOf("|---") >= 0 || prose.indexOf("| ---") >= 0;
        }

        width: list.width
        // The delegate follows the loaded turn's natural content height. Do
        // not let a transient Loader height become permanent ListView padding.
        height: loader.item ? Math.ceil(loader.item.implicitHeight) : 0
        ListView.onPooled: {
            if (loader.item && loader.item.resetTransientState)
                loader.item.resetTransientState();
        }

        Loader {
            id: loader
            // Prose keeps a comfortable reading measure. Code and tables can
            // breathe without turning every normal answer into a wide page.
            width: Math.min(parent.width - Theme.s4,
                            rowItem.wideAnswer ? Theme.wideReadingWidth : Theme.readingWidth)
            height: item ? Math.ceil(item.implicitHeight) : 0
            anchors.horizontalCenter: parent.horizontalCenter
            sourceComponent: kind === "user" ? userTurn : kind === "activity" ? activityTurn : assistantTurn
        }

        Component {
            id: userTurn
            UserMessage {
                body: rowItem.body
                attachments: rowItem.attachments
                row: rowItem.index
                onEdited: function(text) { if (bridge) bridge.editMessage(rowItem.index, text); }
            }
        }
        Component {
            id: assistantTurn
            AssistantMessage {
                body: rowItem.body
                thought: rowItem.thought
                blocks: rowItem.blocks
                tail: rowItem.tail
                tailKind: rowItem.tailKind
                tailLanguage: rowItem.tailLanguage
                tailLabel: rowItem.tailLabel
                streaming: rowItem.streaming
                thinkSeconds: rowItem.thinkSeconds
                thinkDone: rowItem.thinkDone
                latest: rowItem.index === list.count - 1
                row: rowItem.index
                onLinkClicked: function(link) { list.linkClicked(link); }
                onBranched: if (bridge) bridge.branchFrom(rowItem.index)
            }
        }
        Component {
            id: activityTurn
            RunActivity {
                steps: rowItem.steps
                live: bridge && bridge.busy && rowItem.index === list.count - 1
            }
        }
    }

    add: Transition {
        enabled: !Theme.reducedMotion
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.base; easing.type: Theme.easing }
            NumberAnimation { property: "scale"; from: 0.985; to: 1; duration: Theme.base; easing.type: Theme.easing }
        }
    }
}
