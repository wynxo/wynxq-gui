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
    readonly property int contextUsed: bridge ? Math.max(0, Number(bridge.contextUsed || 0)) : 0
    readonly property int contextTotal: bridge ? Math.max(0, Number(bridge.numCtx || 0)) : 0
    readonly property real contextFraction: contextTotal > 0 ? Math.min(1, contextUsed / contextTotal) : 0
    readonly property bool showRate: !!(bridge && bridge.busy && liveRate > 0)
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
            visible: root.showRate
            text: (root.rateExact ? "" : "≈") + root.liveRate.toFixed(1) + (root.compact ? "/s" : " tok/s")
            color: Theme.textSecondary
            font.family: Theme.monoFamily
            font.pixelSize: Theme.caption
            anchors.verticalCenter: parent.verticalCenter
        }

        Rectangle {
            visible: root.showRate
            width: 1
            height: 12
            color: Theme.borderSubtle
            anchors.verticalCenter: parent.verticalCenter
        }

        Text {
            text: root.formatCount(root.chatTokens) + (root.compact ? " chat" : " chat tokens")
            color: Theme.textSecondary
            font.family: Theme.monoFamily
            font.pixelSize: Theme.caption
            anchors.verticalCenter: parent.verticalCenter
        }

        Rectangle {
            visible: root.contextTotal > 0 && !root.compact
            width: 34
            height: 4
            radius: 2
            color: Theme.surfaceSunken
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                width: Math.max(parent.height, parent.width * root.contextFraction)
                height: parent.height
                radius: parent.radius
                color: root.contextFraction > 0.88 ? Theme.warning : Theme.accent
            }
        }
    }

    HoverHandler { id: usageHover }
    ToolTip.visible: usageHover.hovered
    ToolTip.delay: 550
    ToolTip.text: (root.showRate && !root.rateExact
        ? "Live generation speed is approximate until Ollama reports final metrics. "
        : "") + "Chat total: " + root.formatCount(root.chatTokens)
        + (root.contextTotal > 0 ? " · context: " + root.formatCount(root.contextUsed)
            + " / " + root.formatCount(root.contextTotal) : "")

    Accessible.role: Accessible.StaticText
    Accessible.name: (root.liveRate > 0
        ? (root.rateExact ? "" : "approximately ") + root.liveRate.toFixed(1) + " tokens per second; "
        : "generation speed unavailable; ")
        + root.chatTokens + " recorded tokens in this chat"
}
