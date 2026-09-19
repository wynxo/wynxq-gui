import QtQuick

Rectangle {
    property bool vertical: false
    implicitHeight: vertical ? 16 : 1
    implicitWidth: vertical ? 1 : 40
    color: Theme.borderSubtle
}
