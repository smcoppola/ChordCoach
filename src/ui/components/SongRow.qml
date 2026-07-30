// Catalog browse row — a folder (difficulty / style / composer) or a song.
// Shared by the dashboard's song picker and the Library view's Corpus tab.
import QtQuick 2.15
import QtQuick.Layouts 1.15
import "grade_colors.js" as GradeColors

Rectangle {
    id: row

    // A catalog entry from get_catalog_level() / search_catalog()
    property var entry: null
    property real uiScale: (typeof mainWindow !== "undefined" && mainWindow) ? mainWindow.uiScale : 1.0
    readonly property bool isCategory: !!(entry && entry.isCategory)

    signal activated()

    implicitHeight: (isCategory ? 50 : 70) * uiScale
    radius: 8 * uiScale
    color: entryMouse.containsMouse ? "#1a2a3a" : "#2a2a2a"
    border.color: entryMouse.containsMouse ? "#2196F3" : "#444444"
    border.width: 1

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 2

        RowLayout {
            Layout.fillWidth: true

            Text {
                text: (row.isCategory ? "📁  " : "🎵  ") + ((entry && (entry.title || entry.id)) || "")
                color: "#ffffff"
                font.pixelSize: (row.isCategory ? 16 : 14) * row.uiScale
                font.bold: true
                Layout.fillWidth: true
                elide: Text.ElideRight
            }

            // Item level tag for songs
            Rectangle {
                visible: !row.isCategory
                width: 75 * row.uiScale
                height: 22 * row.uiScale
                radius: 4 * row.uiScale
                color: GradeColors.forGrade(entry ? entry.level : "")

                Text {
                    anchors.centerIn: parent
                    text: (entry && entry.level) || ""
                    color: "white"
                    font.pixelSize: 10 * row.uiScale
                    font.bold: true
                }
            }

            Text {
                visible: row.isCategory
                text: "→"
                color: "#444444"
                font.pixelSize: 18 * row.uiScale
            }
        }

        Text {
            visible: !row.isCategory
            text: (entry && entry.artist) || "Unknown Composer"
            color: "#888888"
            font.pixelSize: 11 * row.uiScale
            Layout.leftMargin: 26 * row.uiScale
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
    }

    MouseArea {
        id: entryMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: row.activated()
    }
}
