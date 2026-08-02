// Difficulty + hand-mode chooser for imported (`user::`) songs.
// Extracted verbatim from DashboardView's difficultyPicker so the dashboard's
// quick picker and the Library view drive the exact same routing.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Popup {
    id: dialog

    property string pendingSongId: ""
    property string handMode: "auto"
    property real uiScale: (typeof mainWindow !== "undefined" && mainWindow) ? mainWindow.uiScale : 1.0

    // QML reads an 8-digit hex as #AARRGGBB, so "#4CAF5030" is a brown at 19%
    // alpha rather than a translucent green. Build tints from the accent instead.
    readonly property color accent: "#4CAF50"
    function tint(a) { return Qt.rgba(dialog.accent.r, dialog.accent.g, dialog.accent.b, a); }

    // Emitted once a song has actually been requested — hosts use it to raise
    // their own "Loading Song…" state.
    signal playStarted(string songId, int level)

    width: 340 * uiScale
    modal: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    onOpened: handMode = (!!appState && !!appState.music21Service)
              ? appState.music21Service.get_user_song_hand_mode(pendingSongId) : "auto"

    function play(level) {
        var baseId = pendingSongId;
        appState.music21Service.mark_song_played(baseId);
        dialog.playStarted(baseId, level);
        if (level > 0 && typeof appState.music21Service.request_song_level === "function") {
            appState.music21Service.request_song_level(baseId + "::L" + level);
        } else {
            appState.music21Service.songRequested(
                level > 0 ? baseId + "::L" + level : baseId);
        }
        dialog.close();
    }

    background: Rectangle {
        color: "#1c1c1e"
        radius: 12 * dialog.uiScale
        border.color: "#4CAF50"
    }

    contentItem: ColumnLayout {
        spacing: 8

        Text {
            text: "CHOOSE DIFFICULTY"
            color: "#666666"
            font.pixelSize: 11 * dialog.uiScale
            font.bold: true
            font.letterSpacing: 3 * dialog.uiScale
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 8 * dialog.uiScale
        }

        // Hand-assignment override (persists per song)
        Text {
            text: "HANDS"
            color: "#666666"
            font.pixelSize: 9 * dialog.uiScale
            font.bold: true
            font.letterSpacing: 2 * dialog.uiScale
            Layout.alignment: Qt.AlignHCenter
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 6 * dialog.uiScale

            Repeater {
                // "Manual" is set by the note editor, not picked here — it is
                // shown so the state is visible, and clicking any other chip
                // re-infers every hand and discards those edits.
                model: [
                    { mode: "auto",  label: "Auto" },
                    { mode: "split", label: "Split C4" },
                    { mode: "right", label: "RH only" },
                    { mode: "left",  label: "LH only" },
                    { mode: "manual", label: "Manual" }
                ]
                delegate: Rectangle {
                    // The Manual chip only exists while the song is in that
                    // state, and is a status readout rather than a control —
                    // picking it would rebuild the score from the coarser
                    // grouped form and flatten the per-note durations the
                    // editor just set.
                    readonly property bool isStatusOnly: modelData.mode === "manual"
                    visible: !isStatusOnly || dialog.handMode === "manual"
                    property bool isActive: dialog.handMode === modelData.mode
                    Layout.preferredWidth: handChipLabel.implicitWidth + 16 * dialog.uiScale
                    Layout.preferredHeight: 24 * dialog.uiScale
                    radius: 12 * dialog.uiScale
                    color: isActive ? dialog.tint(0.19) : (handChipMouse.containsMouse ? "#333333" : "#2a2a2a")
                    border.color: isActive ? "#4CAF50" : "#444444"

                    Text {
                        id: handChipLabel
                        anchors.centerIn: parent
                        text: modelData.label
                        color: isActive ? "#4CAF50" : "#aaaaaa"
                        font.pixelSize: 10 * dialog.uiScale
                        font.bold: isActive
                    }

                    MouseArea {
                        id: handChipMouse
                        anchors.fill: parent
                        enabled: !isStatusOnly
                        hoverEnabled: !isStatusOnly
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            dialog.handMode = modelData.mode;
                            appState.music21Service.set_user_song_hand_mode(
                                dialog.pendingSongId, modelData.mode);
                        }
                    }
                }
            }
        }

        Repeater {
            model: [
                { level: 0, label: "Original", desc: "No adjustment — play it as imported" },
                { level: 4, label: "Level 4", desc: "Light touch: extreme stretches tamed" },
                { level: 3, label: "Level 3", desc: "Smaller chords, easier reaches" },
                { level: 2, label: "Level 2", desc: "Simple chords, thinned fast runs" },
                { level: 1, label: "Level 1", desc: "Simplest: melody + bass, slow pace" }
            ]
            delegate: Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 52 * dialog.uiScale
                Layout.leftMargin: 8 * dialog.uiScale
                Layout.rightMargin: 8 * dialog.uiScale
                radius: 8 * dialog.uiScale
                color: levelMouse.containsMouse ? dialog.tint(0.13) : "#2a2a2a"
                border.color: levelMouse.containsMouse ? "#4CAF50" : "#444444"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8 * dialog.uiScale
                    spacing: 2
                    Text {
                        text: modelData.label
                        color: "white"
                        font.bold: true
                        font.pixelSize: 13 * dialog.uiScale
                    }
                    Text {
                        text: modelData.desc
                        color: "#888888"
                        font.pixelSize: 10 * dialog.uiScale
                    }
                }

                MouseArea {
                    id: levelMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: dialog.play(modelData.level)
                }
            }
        }

        Item { Layout.preferredHeight: 4 * dialog.uiScale }
    }
}
