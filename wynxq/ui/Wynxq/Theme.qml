pragma Singleton
import QtQuick

/*!
    Wynxq's interface tokens. The only place colour, spacing, radius, type and
    motion are decided.

    The workspace remains a near-black graphite room, but chrome and controls
    use a restrained glass material: translucent tint, a bright top edge, an
    inner reflection and soft depth. It is intentionally limited to interactive
    surfaces so the conversation stays calm and readable instead of turning the
    whole app into decorative glassmorphism.
*/
QtObject {
    id: theme

    property var bridge: null
    readonly property bool ready: bridge !== null

    readonly property string colorScheme: ready ? bridge.colorScheme : "Dark"
    function paletteColor(dark, black, midnight) {
        return colorScheme === "Black" ? black : colorScheme === "Midnight" ? midnight : dark;
    }

    // ---------------------------------------------------------- foundation
    // Opaque fallbacks remain the readability baseline. GlassSurface layers
    // translucency over these values without weakening text contrast.
    readonly property color background: paletteColor("#171717", "#090909", "#141518")
    readonly property color backgroundSoft: paletteColor("#121212", "#050505", "#101114")
    readonly property color surface: paletteColor("#1e1e1e", "#141414", "#1d1f24")
    readonly property color surfaceRaised: paletteColor("#252525", "#1c1c1c", "#24272d")
    readonly property color surfaceHover: paletteColor("#2d2d2d", "#262626", "#2d3037")
    readonly property color surfacePressed: paletteColor("#363636", "#303030", "#353941")
    readonly property color surfaceSelected: paletteColor("#303030", "#292929", "#30343c")
    readonly property color surfaceSunken: paletteColor("#0e0e0e", "#000000", "#0d0e11")
    readonly property color scrim:           "#cc070707"

    // Aliases kept so a component can say what it means.
    readonly property color surfaceElevated: surfaceRaised
    readonly property color panel:           backgroundSoft

    readonly property color borderSubtle: paletteColor("#303030", "#242424", "#292d34")
    readonly property color border: paletteColor("#404040", "#353535", "#393e47")
    readonly property color borderStrong: paletteColor("#565656", "#494949", "#4c525d")

    // ------------------------------------------------------ liquid glass
    // Cross-platform approximation of the macOS material vocabulary. The
    // values deliberately stay neutral; accent is reserved for focus/action.
    readonly property color glassTint: paletteColor("#272727", "#1d1d1d", "#27292e")
    readonly property color glassTintStrong: paletteColor("#303030", "#252525", "#303238")
    readonly property color glassTintHover: paletteColor("#383838", "#303030", "#383b42")
    readonly property color glassEdge:        Qt.rgba(1, 1, 1, 0.10)
    readonly property color glassEdgeStrong:  Qt.rgba(1, 1, 1, 0.18)
    readonly property color glassInner:       Qt.rgba(1, 1, 1, 0.045)
    readonly property color glassSpecular:    Qt.rgba(1, 1, 1, 0.12)
    readonly property color glassSpecularHot: Qt.rgba(1, 1, 1, 0.19)
    readonly property color glassLowlight:    Qt.rgba(0, 0, 0, 0.28)
    readonly property color glassShadow:      Qt.rgba(0, 0, 0, 0.72)
    readonly property real glassThinOpacity: 0.46
    readonly property real glassOpacity: 0.68
    readonly property real glassStrongOpacity: 0.88

    readonly property color textPrimary:   "#f2f2f2"
    readonly property color textSecondary: "#cccccc"
    readonly property color textMuted:     "#aaaaaa"
    readonly property color textDisabled:  "#858585"
    readonly property color textInverse:   "#111111"

    // Platinum matches the controller default; Appearance can replace it.
    readonly property color accent: ready && bridge.accentColor ? bridge.accentColor : "#e9e3d6"
    readonly property color accentHover: Qt.lighter(accent, 1.08)
    readonly property color accentMuted: Qt.rgba(accent.r, accent.g, accent.b, 0.12)
    readonly property color accentEdge: Qt.rgba(accent.r, accent.g, accent.b, 0.44)
    readonly property color onAccent: (accent.r * 0.299 + accent.g * 0.587 + accent.b * 0.114) > 0.56
                                      ? "#101010" : "#f7f6f2"

    readonly property color success: "#7acb96"
    readonly property color warning: "#d7ab5d"
    readonly property color danger:  "#e58476"
    readonly property color info:    "#82abdd"
    readonly property color successMuted: "#17231c"
    readonly property color warningMuted: "#282116"
    readonly property color dangerMuted:  "#2a1a18"
    readonly property color infoMuted:    "#161d26"

    // Diff ink. Restrained: a changed line should read as changed, not alarm.
    readonly property color diffAddInk:    "#8fcf9f"
    readonly property color diffRemoveInk: "#e08d80"
    readonly property color diffAddFill:    "#152018"
    readonly property color diffRemoveFill: "#221515"
    readonly property color diffHunk:      "#7d9cc4"

    readonly property var codePalette: ({
        "text": "#e0dfda", "keyword": "#d5a6e6", "string": "#9dca9d",
        "number": "#dbaa7a", "comment": "#898983", "function": "#8dbbdd",
        "builtin": "#84c9bf", "punctuation": "#9c9c95"
    })

    // Terminal ink, resolved in Python against this map so ANSI keeps meaning
    // without inventing sixteen colours the rest of the app does not know.
    readonly property var terminalPalette: ({
        "text": "#d8d7d2", "black": "#a0a6b2", "red": "#e58476", "green": "#7acb96",
        "yellow": "#d7ab5d", "blue": "#82abdd", "magenta": "#c2a0e4", "cyan": "#7fc8bf",
        "white": "#d8d7d2", "brightBlack": "#b0afa8", "brightRed": "#f09c8e",
        "brightGreen": "#94daaa", "brightYellow": "#e6c179", "brightBlue": "#9dc0e8",
        "brightMagenta": "#d4b6ee", "brightCyan": "#98dad1", "brightWhite": "#f2f2f2",
        "dim": "#a0a6b2"
    })

    // -------------------------------------------------------------- rhythm
    readonly property bool compact: ready && bridge.density === "Compact"
    readonly property real scale: compact ? 0.94 : 1.0

    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24
    readonly property int s7: 32
    readonly property int s8: 48

    // Slightly rounder continuous-feeling geometry makes the glass read as a
    // material while keeping dense tooling compact.
    readonly property int r1: 7
    readonly property int r2: 10
    readonly property int r3: 14
    readonly property int r4: 18
    readonly property int rPill: 999

    readonly property int control: compact ? 30 : 32
    readonly property int controlSmall: compact ? 26 : 28
    readonly property int rowHeight: compact ? 32 : 35
    readonly property int denseRow: compact ? 24 : 26
    readonly property int gutter: compact ? 16 : 22
    readonly property int readingWidth: 780
    readonly property int wideReadingWidth: 940
    readonly property int focusEditorWidth: 1160
    readonly property int headerHeight: compact ? 42 : 46
    readonly property int railWidth: 44

    // ---------------------------------------------------------- typography
    readonly property string sansFamily: ready && bridge.systemFont ? systemSans : "Inter"
    readonly property string monoFamily: "JetBrains Mono"
    property string systemSans: "Inter"

    readonly property int display: Math.round(30 * scale)
    readonly property int title:   Math.round(17 * scale)
    readonly property int heading: Math.round(14 * scale)
    readonly property int body:    Math.round(14 * scale)
    readonly property int label:   Math.round(12.5 * scale)
    readonly property int caption: Math.round(11.5 * scale)
    readonly property int micro:   Math.round(10 * scale)
    readonly property int code:    Math.round(12 * scale)

    // ------------------------------------------------------------- motion
    readonly property bool reducedMotion: ready && bridge.reducedMotion
    readonly property int fast: reducedMotion ? 0 : 110
    readonly property int base: reducedMotion ? 0 : 170
    readonly property int slow: reducedMotion ? 0 : 230
    readonly property int easing: Easing.OutCubic

    // Shared micro-interaction vocabulary. Keeping these values here prevents
    // individual controls from slowly drifting into different products.
    readonly property real pressScale: 0.97
    readonly property real disabledOpacity: 0.42
    readonly property int tooltipDelay: 500
    readonly property real popupScale: 0.97
    readonly property real popupBlur: 0.76
    readonly property real floatingControlFill: 0.62
    readonly property real floatingControlHoverFill: 0.80

    function stateColor(name) {
        if (name === "done") return success;
        if (name === "failed") return danger;
        if (name === "cancelled" || name === "declined") return warning;
        if (name === "waiting") return warning;
        if (name === "queued") return textMuted;
        return accent;
    }

    // Activity states are also carried by a word and an icon; this is the
    // shared vocabulary so a state never means two things in two panels.
    function stateLabel(name) {
        if (name === "done") return "done";
        if (name === "failed") return "failed";
        if (name === "cancelled" || name === "declined") return "cancelled";
        if (name === "waiting") return "waiting for you";
        if (name === "queued") return "queued";
        return "running";
    }

    function stateIcon(name) {
        if (name === "done") return "check";
        if (name === "failed") return "warning";
        if (name === "cancelled" || name === "declined") return "close";
        if (name === "waiting") return "lock";
        if (name === "queued") return "clock";
        return "bolt";
    }

    // One family of shapes for file kinds, so the tree, the changes list and
    // the context panel never disagree about what a `.py` file looks like.
    function kindIcon(kind) {
        if (kind === "folder") return "folder";
        if (kind === "code") return "code";
        if (kind === "config") return "sliders";
        if (kind === "doc") return "file";
        if (kind === "image") return "image";
        if (kind === "diff") return "branch";
        if (kind === "link") return "globe";
        return "file";
    }

    function alpha(base, amount) {
        return Qt.rgba(base.r, base.g, base.b, amount);
    }
}
