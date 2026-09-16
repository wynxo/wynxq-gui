pragma Singleton
import QtQuick

/*!
    Lightweight UI mode state for the shell.

    Chat stays conversational. Work is the local agent surface for coding,
    project tools, commands and optional desktop control. Execution autonomy is
    separate state, so changing Manual / Safe / Auto / Full never invents a
    third product mode.
*/
QtObject {
    property string current: "chat"

    function label(mode) {
        if (mode === "work") return "Work";
        return "Chat";
    }
}
