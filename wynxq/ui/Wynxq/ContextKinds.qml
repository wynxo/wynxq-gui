pragma Singleton
import QtQuick

/*!
    One mapping from a context kind to the way it is drawn.

    Attachments are shown in more than one place — the composer, the quick bar,
    the folded group in a reopened task — and they have to look the same in all
    of them, so the mapping lives here rather than in each of them.
*/
QtObject {
    function icon(kind) {
        switch (kind) {
        case "image": return "image";
        case "screenshot": return "camera";
        case "window": return "window";
        case "folder": return "folder";
        case "clipboard": return "clipboard";
        default: return "file";
        }
    }
}
