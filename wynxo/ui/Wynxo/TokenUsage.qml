import QtQuick
import QtQuick.Controls

/*!
    A deliberately non-interactive composer summary.

    Detailed accounting belongs in Settings → Usage. This surface answers only
    two questions without stealing space from the prompt: how fast the current
    generation is moving, and how many exact tokens have been recorded for this
    conversation. Provisional throughput is marked as approximate.
*/
Item {
    id: root
    objectName: "tokenUsage"
    property bool compact: false
    readonly property real liveRate: bridge ? Number(bridge.liveTokenRate || 0) : 0
    readonly property bool rateExact: bridge ? !!bridge.liveTokenRateExact : false
    readonly property int chatTokens: bridge ? Math.max(0, Number(bridge.conversationTokens || 0)) : 0
    implicitWidth: stats.implicitWidth
    implicitHeight: 30

    function formatCount(value) {
        var count = Math.max(0, Math.round(Number(value) || 0));
        if (count >= 1000000000) return (count / 1000000000).toFixed(count >= 10000000000 ? 1 : 2) + "B";
        if (count >= 1000000) return (count / 1000000).toFixed(count >= 10000000 ? 1 : 2) + "M";
        if (count >= 1000) return (count / 1000).toFixed(count >= 10000 ? 1 : 2) + "K";
        return String(count);
    }

    Row {
        id: stats
        anchors.centerIn: parent
        spacing: Theme.s2

        Text {
            text: root.liveRate > 0
                ? (root.rateExact ? "" : "≈") + root.liveRate.toFixed(1) + (root.compact ? "/s" : " tok/s")
                : (root.compact ? "—/s" : "— tok/s")
            color: bridge && bridge.busy ? Theme.textSecondary : Theme.textMuted
            font.family: Theme.monoFamily
            font.pixelSize: Theme.caption
            anchors.verticalCenter: parent.verticalCenter
        }

        Rectangle {
            width: 1
            height: 12
            color: Theme.borderSubtle
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.formatCount(root.chatTokens) + (root.compact ? " tok" : " tokens")
            color: Theme.textSecondary
            font.family: Theme.monoFamily
            font.pixelSize: Theme.caption
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    HoverHandler { id: usageHover }
    ToolTip.visible: usageHover.hovered
    ToolTip.delay: 550
    ToolTip.text: root.liveRate > 0 && !root.rateExact
        ? "Live generation speed is approximate until Ollama reports final metrics. Chat total is exact recorded input + output from completed runs."
        : "Generation speed · exact recorded input + output tokens for this chat"

    Accessible.role: Accessible.StaticText
    Accessible.name: (root.liveRate > 0
        ? (root.rateExact ? "" : "approximately ") + root.liveRate.toFixed(1) + " tokens per second; "
        : "generation speed unavailable; ")
        + root.chatTokens + " recorded tokens in this chat"
}
