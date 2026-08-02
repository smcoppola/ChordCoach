// Per-note editor for imported songs: beat, duration and hand.
//
// MIDI import guesses at all three — onsets are quantized, durations rounded,
// hands inferred by track or by a Viterbi pass — and this is where a wrong
// guess gets corrected. Modify only: notes cannot be added or removed, and
// pitch is fixed, so the note count that goes back to Python always matches
// the one that came out (save_user_song_notes refuses the save otherwise).
//
// `allNotes` is the working copy and the source of truth; `noteModel` is only
// a filtered projection of it for the ListView. Nothing touches disk until
// Save, which makes Cancel a complete undo.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Popup {
    id: editor

    property string songId: ""
    property string songTitle: ""
    property real uiScale: (typeof mainWindow !== "undefined" && mainWindow) ? mainWindow.uiScale : 1.0

    // Every position and duration is a multiple of this, matching the 16th-note
    // grid midi_ingestor quantizes to on import. Python snaps again on save, so
    // a value can never reach the record off-grid.
    readonly property real grid: 0.25

    property var allNotes: []       // working copy — full song, in save order
    property var pristineNotes: []  // as loaded, for per-row reset and change detection
    property var barlines: []
    property int changedCount: 0
    property string handFilter: "all"
    property string errorText: ""

    // Tints are built with Qt.rgba rather than an 8-digit hex literal: QML
    // reads #AABBCCDD as #AARRGGBB, so "#4CAF5018" is a brown at 30% alpha,
    // not a translucent green.
    readonly property color accent: "#4CAF50"
    readonly property color danger: "#F44336"
    function tint(c, a) { return Qt.rgba(c.r, c.g, c.b, a); }

    signal saved()

    // Sized against the window rather than in fixed pixels, and every internal
    // dimension is a uiScale multiple.
    width: Math.min(mainWindow.width * 0.86, 1150 * uiScale)
    height: mainWindow.height * 0.86
    modal: true
    // Escape only — CloseOnPressOutside would silently discard unsaved edits.
    closePolicy: Popup.CloseOnEscape

    function show(song) {
        editor.songId = song.id;
        editor.songTitle = song.title || "";
        editor.load();
        editor.open();
    }

    function load() {
        errorText = "";
        handFilter = "all";
        changedCount = 0;

        var svc = (!!appState && !!appState.music21Service) ? appState.music21Service : null;
        var raw = svc ? svc.get_user_song_notes(editor.songId) : [];
        editor.barlines = svc ? svc.get_user_song_barlines(editor.songId) : [];

        // Copy into plain JS objects. Values handed back across the Qt boundary
        // are not reliably mutable in place, and every edit below mutates.
        var working = [];
        var original = [];
        for (var i = 0; i < raw.length; i++) {
            var r = raw[i];
            working.push({ beat: r.beat, duration: r.duration, hand: r.hand,
                           pitch: r.pitch, name: r.name, measure: r.measure,
                           step_index: r.step_index, note_index: r.note_index });
            original.push({ beat: r.beat, duration: r.duration, hand: r.hand });
        }
        editor.allNotes = working;
        editor.pristineNotes = original;
        editor.rebuildRows();
    }

    function measureFor(beat) {
        var m = 1;
        for (var i = 0; i < editor.barlines.length; i++) {
            if (editor.barlines[i] <= beat + 1e-6) m++;
            else break;
        }
        return m;
    }

    function rowIsChanged(i) {
        var a = editor.allNotes[i], b = editor.pristineNotes[i];
        return a.beat !== b.beat || a.duration !== b.duration || a.hand !== b.hand;
    }

    function passesFilter(i) {
        return editor.handFilter === "all" || editor.allNotes[i].hand === editor.handFilter;
    }

    // Rebuilds the visible projection. Called on load and whenever the hand
    // filter changes — never on an edit, so a row cannot jump out from under
    // the cursor mid-adjustment.
    function rebuildRows() {
        noteModel.clear();
        for (var i = 0; i < editor.allNotes.length; i++) {
            if (!passesFilter(i)) continue;
            var n = editor.allNotes[i];
            noteModel.append({ idx: i, beat: n.beat, duration: n.duration,
                               hand: n.hand, name: n.name, measure: n.measure,
                               changed: rowIsChanged(i) });
        }
    }

    function recount() {
        var c = 0;
        for (var i = 0; i < editor.allNotes.length; i++) if (rowIsChanged(i)) c++;
        editor.changedCount = c;
    }

    function snap(v, minimum) {
        return Math.max(minimum, Math.round(v / editor.grid) * editor.grid);
    }

    function setBeat(row, idx, value) {
        var v = snap(value, 0);
        editor.allNotes[idx].beat = v;
        editor.allNotes[idx].measure = measureFor(v);
        noteModel.setProperty(row, "beat", v);
        noteModel.setProperty(row, "measure", editor.allNotes[idx].measure);
        noteModel.setProperty(row, "changed", rowIsChanged(idx));
        recount();
    }

    function setDuration(row, idx, value) {
        var v = snap(value, editor.grid);
        editor.allNotes[idx].duration = v;
        noteModel.setProperty(row, "duration", v);
        noteModel.setProperty(row, "changed", rowIsChanged(idx));
        recount();
    }

    function setHand(row, idx, value) {
        editor.allNotes[idx].hand = value;
        noteModel.setProperty(row, "hand", value);
        noteModel.setProperty(row, "changed", rowIsChanged(idx));
        recount();
    }

    function resetRow(row, idx) {
        var p = editor.pristineNotes[idx];
        editor.allNotes[idx].beat = p.beat;
        editor.allNotes[idx].duration = p.duration;
        editor.allNotes[idx].hand = p.hand;
        editor.allNotes[idx].measure = measureFor(p.beat);
        noteModel.setProperty(row, "beat", p.beat);
        noteModel.setProperty(row, "duration", p.duration);
        noteModel.setProperty(row, "hand", p.hand);
        noteModel.setProperty(row, "measure", editor.allNotes[idx].measure);
        noteModel.setProperty(row, "changed", false);
        recount();
    }

    function jumpToMeasure(m) {
        for (var row = 0; row < noteModel.count; row++) {
            if (noteModel.get(row).measure >= m) {
                noteList.positionViewAtIndex(row, ListView.Beginning);
                return;
            }
        }
    }

    function save() {
        errorText = "";
        var msg = appState.music21Service.save_user_song_notes(editor.songId, editor.allNotes);
        if (msg !== "") {
            errorText = msg;
            return;
        }
        editor.saved();
        editor.close();
    }

    ListModel { id: noteModel }

    // How many notes the current filter is showing, out of allNotes.length.
    property alias visibleCount: noteModel.count

    background: Rectangle {
        color: "#1c1c1e"
        radius: 12 * editor.uiScale
        border.color: "#4CAF50"
    }

    // ── Small reusable bits ──────────────────────────────────────────
    component Chip : Rectangle {
        id: chip
        property string label: ""
        property bool active: false
        property color accent: "#4CAF50"
        signal clicked()

        implicitWidth: chipLabel.implicitWidth + 16 * editor.uiScale
        implicitHeight: 24 * editor.uiScale
        radius: 12 * editor.uiScale
        color: chip.active ? Qt.rgba(chip.accent.r, chip.accent.g, chip.accent.b, 0.19)
                           : (chipMouse.containsMouse ? "#333333" : "#2a2a2a")
        border.color: chip.active ? chip.accent : "#444444"

        Text {
            id: chipLabel
            anchors.centerIn: parent
            text: chip.label
            color: chip.active ? chip.accent : "#aaaaaa"
            font.pixelSize: 10 * editor.uiScale
            font.bold: chip.active
        }

        MouseArea {
            id: chipMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
        }
    }

    // ◀ value ▶ — the only way to change a number, so an off-grid value is
    // unreachable from the UI by construction.
    component Stepper : RowLayout {
        id: stepper
        property real value: 0
        property real step: editor.grid
        property int decimals: 2
        property bool highlighted: false
        signal stepped(real newValue)

        spacing: 2 * editor.uiScale

        Chip {
            label: "◀"
            onClicked: stepper.stepped(stepper.value - stepper.step)
        }
        Text {
            Layout.preferredWidth: 46 * editor.uiScale
            horizontalAlignment: Text.AlignHCenter
            text: stepper.value.toFixed(stepper.decimals)
            color: stepper.highlighted ? "#4CAF50" : "white"
            font.pixelSize: 11 * editor.uiScale
            font.bold: stepper.highlighted
        }
        Chip {
            label: "▶"
            onClicked: stepper.stepped(stepper.value + stepper.step)
        }
    }

    component HeaderCell : Text {
        color: "#666666"
        font.pixelSize: 9 * editor.uiScale
        font.bold: true
        font.letterSpacing: 2 * editor.uiScale
    }

    contentItem: ColumnLayout {
        spacing: 10 * editor.uiScale

        // ── Title ────────────────────────────────────────────────────
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 6 * editor.uiScale
            text: "EDIT NOTES"
            color: "#666666"
            font.pixelSize: 11 * editor.uiScale
            font.bold: true
            font.letterSpacing: 3 * editor.uiScale
        }
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            text: editor.songTitle
            color: "white"
            font.pixelSize: 16 * editor.uiScale
            font.bold: true
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
        }

        // ── Filter / navigation bar ──────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            spacing: 6 * editor.uiScale

            HeaderCell { text: "HAND" }
            Repeater {
                model: [
                    { mode: "all",   label: "All" },
                    { mode: "right", label: "RH" },
                    { mode: "left",  label: "LH" }
                ]
                delegate: Chip {
                    label: modelData.label
                    active: editor.handFilter === modelData.mode
                    onClicked: {
                        editor.handFilter = modelData.mode;
                        editor.rebuildRows();
                    }
                }
            }

            Item { Layout.preferredWidth: 18 * editor.uiScale }

            HeaderCell { text: "GO TO BAR" }
            Stepper {
                id: measureJump
                value: 1
                step: 1
                decimals: 0
                onStepped: (v) => {
                    measureJump.value = Math.max(1, v);
                    editor.jumpToMeasure(measureJump.value);
                }
            }

            Item { Layout.fillWidth: true }

            Text {
                Layout.rightMargin: 14 * editor.uiScale
                text: editor.handFilter === "all"
                      ? editor.visibleCount + " notes"
                      : editor.visibleCount + " of " + editor.allNotes.length + " notes"
                color: "#666666"
                font.pixelSize: 11 * editor.uiScale
            }
            Text {
                text: editor.changedCount === 0
                      ? "No changes"
                      : editor.changedCount + (editor.changedCount === 1 ? " note changed" : " notes changed")
                color: editor.changedCount === 0 ? "#666666" : "#4CAF50"
                font.pixelSize: 11 * editor.uiScale
                font.bold: editor.changedCount > 0
            }
        }

        // ── Column headings ──────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 22 * editor.uiScale
            Layout.rightMargin: 22 * editor.uiScale
            spacing: 8 * editor.uiScale

            HeaderCell { text: "BAR"; Layout.preferredWidth: 44 * editor.uiScale }
            HeaderCell { text: "NOTE"; Layout.preferredWidth: 52 * editor.uiScale }
            HeaderCell { text: "BEAT"; Layout.preferredWidth: 150 * editor.uiScale }
            HeaderCell { text: "LENGTH"; Layout.preferredWidth: 150 * editor.uiScale }
            HeaderCell { text: "HAND" }
            Item { Layout.fillWidth: true }
        }

        // ── The notes ────────────────────────────────────────────────
        ListView {
            id: noteList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            clip: true
            // ListView, not Repeater: a song is easily thousands of notes and
            // only ListView creates delegates lazily.
            model: noteModel
            cacheBuffer: 400 * editor.uiScale
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            delegate: Rectangle {
                id: noteRow
                width: ListView.view.width
                height: 38 * editor.uiScale
                radius: 6 * editor.uiScale
                color: model.changed ? editor.tint(editor.accent, 0.12)
                                     : (index % 2 === 0 ? "#2a2a2a" : "#242426")
                border.color: model.changed ? editor.accent : "transparent"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8 * editor.uiScale
                    // Clears the overlaid scrollbar, which would otherwise sit
                    // on top of the reset chip at the end of the row.
                    anchors.rightMargin: 22 * editor.uiScale
                    spacing: 8 * editor.uiScale

                    Text {
                        Layout.preferredWidth: 44 * editor.uiScale
                        text: model.measure
                        color: "#888888"
                        font.pixelSize: 11 * editor.uiScale
                    }
                    Text {
                        Layout.preferredWidth: 52 * editor.uiScale
                        text: model.name
                        color: "white"
                        font.pixelSize: 12 * editor.uiScale
                        font.bold: true
                    }
                    Stepper {
                        Layout.preferredWidth: 150 * editor.uiScale
                        value: model.beat
                        highlighted: model.changed
                        onStepped: (v) => editor.setBeat(index, model.idx, v)
                    }
                    Stepper {
                        Layout.preferredWidth: 150 * editor.uiScale
                        value: model.duration
                        highlighted: model.changed
                        onStepped: (v) => editor.setDuration(index, model.idx, v)
                    }
                    Chip {
                        label: "L"
                        accent: "#2196F3"
                        active: model.hand === "left"
                        onClicked: editor.setHand(index, model.idx, "left")
                    }
                    Chip {
                        label: "R"
                        accent: "#FF9800"
                        active: model.hand === "right"
                        onClicked: editor.setHand(index, model.idx, "right")
                    }

                    Item { Layout.fillWidth: true }

                    Chip {
                        label: "↺ reset"
                        accent: "#888888"
                        visible: model.changed
                        onClicked: editor.resetRow(index, model.idx)
                    }
                }
            }
        }

        // ── Error banner ─────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            Layout.preferredHeight: editor.errorText === "" ? 0 : 32 * editor.uiScale
            visible: editor.errorText !== ""
            radius: 6 * editor.uiScale
            color: editor.tint(editor.danger, 0.13)
            border.color: editor.danger

            Text {
                anchors.fill: parent
                anchors.margins: 8 * editor.uiScale
                text: editor.errorText
                color: editor.danger
                font.pixelSize: 11 * editor.uiScale
                verticalAlignment: Text.AlignVCenter
                wrapMode: Text.WordWrap
            }
        }

        // ── Footer ───────────────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            Layout.bottomMargin: 10 * editor.uiScale
            spacing: 8 * editor.uiScale

            Text {
                text: "Changing a hand switches this song to manual hand assignment."
                color: "#666666"
                font.pixelSize: 10 * editor.uiScale
                visible: editor.changedCount > 0
            }

            Item { Layout.fillWidth: true }

            Chip {
                label: "CANCEL"
                accent: "#888888"
                onClicked: editor.close()
            }
            Chip {
                label: "SAVE"
                accent: "#4CAF50"
                active: editor.changedCount > 0
                onClicked: editor.save()
            }
        }
    }
}
