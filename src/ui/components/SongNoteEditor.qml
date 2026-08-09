// Per-note editor for imported songs: beat, duration and hand.
//
// MIDI import guesses at all three — onsets are quantized, durations rounded,
// hands inferred by track or by a Viterbi pass — and this is where a wrong
// guess gets corrected. Modify only: notes cannot be added or removed, and
// pitch is fixed, so the note count that goes back to Python always matches
// the one that came out (save_user_song_notes refuses the save otherwise).
//
// A song is thousands of rows, and a row on its own — a pitch, two numbers —
// says nothing about where in the music it sits. So the table is anchored three
// ways: a selected row, a notation strip showing the bar that row lives in, and
// a preview that plays the note or the bar. Everything below hangs off
// `selectedIdx`.
//
// `allNotes` is the working copy and the source of truth; `noteModel` is only
// a filtered projection of it for the ListView. Nothing touches disk until
// Save, which makes Cancel a complete undo.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import ChordCoach 1.0

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

    // Key, metre and tempo — everything the strip and the preview need that a
    // note row does not carry.
    property int keySharps: 0
    property var timeSignatures: []
    property real songBpm: 100.0

    // --- Selection ---------------------------------------------------------
    // Identity is the index into allNotes, never into noteModel: allNotes is
    // never reordered, so a selection survives a filter change for free.
    property int selectedIdx: -1
    // Mirrors of the selected note, refreshed explicitly rather than bound.
    // allNotes[i] is a plain JS object mutated in place, so a binding over it
    // would never re-evaluate — the same reason the rows below are updated with
    // setProperty instead of bindings.
    property real selBeat: 0.0
    property real selDuration: 0.0
    property int stripBar: 0

    readonly property int barCount: editor.barlines.length + 1

    // --- Audio -------------------------------------------------------------
    readonly property bool midiOutEnabled: (!!appState && !!appState.settingsService)
                                           ? appState.settingsService.midiOutEnabled : false
    readonly property bool midiConnected: !!appState ? appState.midiConnected : false
    // A trainer transport can be running behind this modal popup; two schedulers
    // on one MIDI channel is a mess, so the preview stands down.
    readonly property bool transportBusy: (!!appState && !!appState.playback)
                                          ? appState.playback.isPlaying : false
    readonly property bool audioAvailable: midiOutEnabled && midiConnected && !transportBusy
    readonly property string audioHint: !midiOutEnabled ? "MIDI Output is disabled in settings."
                                      : !midiConnected ? "No MIDI hardware output device connected."
                                      : transportBusy ? "Pause playback to preview."
                                      : ""

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

    onOpened: noteList.forceActiveFocus()
    // An abandoned preview schedule would keep sounding after the popup is gone.
    onClosed: editor.stopPreview()

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
        selectedIdx = -1;
        stripBar = 0;
        selBeat = 0.0;
        selDuration = 0.0;

        var svc = (!!appState && !!appState.music21Service) ? appState.music21Service : null;
        var raw = svc ? svc.get_user_song_notes(editor.songId) : [];
        editor.barlines = svc ? svc.get_user_song_barlines(editor.songId) : [];

        var ctx = svc ? svc.get_user_song_notation_context(editor.songId) : null;
        editor.keySharps = ctx ? ctx.key_sharps : 0;
        editor.timeSignatures = ctx ? ctx.time_signatures : [];
        editor.songBpm = ctx ? ctx.bpm : 100.0;

        // Copy into plain JS objects. Values handed back across the Qt boundary
        // are not reliably mutable in place, and every edit below mutates.
        var working = [];
        var original = [];
        for (var i = 0; i < raw.length; i++) {
            var r = raw[i];
            working.push({ beat: r.beat, duration: r.duration, hand: r.hand,
                           pitch: r.pitch, name: r.name, measure: r.measure,
                           finger: r.finger,
                           step_index: r.step_index, note_index: r.note_index });
            original.push({ beat: r.beat, duration: r.duration, hand: r.hand });
        }
        editor.allNotes = working;
        editor.pristineNotes = original;
        editor.rebuildRows();
        editor.rebuildStrip();
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
    //
    // `bar`/`barLabel` are the bar the note was in when the list was built, and
    // are deliberately never updated afterwards: the section headers below are
    // grouped on them, and a note dragged across a barline would otherwise
    // split its bar's run in three and re-flow the list mid-edit. The BAR
    // column still shows the note's current bar, so a moved note reads as "was
    // in bar 7, now in bar 9".
    function rebuildRows() {
        noteModel.clear();
        var bar = 1, bi = 0;
        for (var i = 0; i < editor.allNotes.length; i++) {
            // pristineNotes is beat-sorted, so one walking cursor numbers every
            // row instead of re-scanning the barlines per note.
            var pb = editor.pristineNotes[i].beat;
            while (bi < editor.barlines.length && editor.barlines[bi] <= pb + 1e-6) { bar++; bi++; }
            if (!passesFilter(i)) continue;
            var n = editor.allNotes[i];
            noteModel.append({ idx: i, beat: n.beat, duration: n.duration,
                               hand: n.hand, name: n.name, measure: n.measure,
                               bar: bar, barLabel: "BAR " + bar,
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

    // --- Selection and the strip -------------------------------------------

    function selectRow(row) {
        if (row < 0 || row >= noteModel.count) return;
        noteList.currentIndex = row;
        editor.selectedIdx = noteModel.get(row).idx;
        editor.refreshSelection();
    }

    function refreshSelection() {
        if (editor.selectedIdx < 0 || editor.selectedIdx >= editor.allNotes.length) {
            editor.stripBar = 0;
            return;
        }
        var n = editor.allNotes[editor.selectedIdx];
        editor.selBeat = n.beat;
        editor.selDuration = n.duration;
        if (n.measure !== editor.stripBar) {
            editor.stripBar = n.measure;
            // GO TO BAR doubles as the position readout, so it follows the
            // selection rather than free-running.
            measureJump.value = n.measure;
        }
        editor.syncWindow();
        editor.scheduleStrip();
    }

    // -1 when the current filter is hiding that note.
    function rowForIdx(idx) {
        for (var r = 0; r < noteModel.count; r++) if (noteModel.get(r).idx === idx) return r;
        return -1;
    }

    // Where the strip is looking. Cheap — assignments and a walk over the
    // barlines — so it runs on every edit, keeping the scroll position and the
    // bar numbering exactly in step with the click.
    function syncWindow() {
        notationWindow.notes = editor.allNotes;
        notationWindow.barlines = editor.barlines;
        notationWindow.timeSignatures = editor.timeSignatures;
        notationWindow.bar = editor.stripBar;
        notationWindow.selBeat = editor.selBeat;
        notationWindow.selDuration = editor.selDuration;
        editor.stripBarlines = notationWindow.barlinesInWindow();
    }

    // Re-engraving is the one expensive part — it scans the whole working copy
    // — so it is coalesced: a held-down stepper fires far faster than anyone
    // can read the result. Re-assigning an identical window is a no-op inside
    // NotationView, which compares by value, so over-triggering is free.
    function scheduleStrip() { stripTimer.restart(); }

    function rebuildStrip() {
        editor.syncWindow();
        stripNotation.scrollingNotes = notationWindow.build();
    }

    property var stripBarlines: []

    // --- Editing ------------------------------------------------------------
    // Each of these selects the row it touches first, so nudging a note always
    // anchors the strip on it — without firing audio on every nudge.

    function setBeat(row, idx, value) {
        editor.selectRow(row);
        var v = snap(value, 0);
        editor.allNotes[idx].beat = v;
        editor.allNotes[idx].measure = measureFor(v);
        noteModel.setProperty(row, "beat", v);
        noteModel.setProperty(row, "measure", editor.allNotes[idx].measure);
        noteModel.setProperty(row, "changed", rowIsChanged(idx));
        recount();
        editor.refreshSelection();
    }

    function setDuration(row, idx, value) {
        editor.selectRow(row);
        var v = snap(value, editor.grid);
        editor.allNotes[idx].duration = v;
        noteModel.setProperty(row, "duration", v);
        noteModel.setProperty(row, "changed", rowIsChanged(idx));
        recount();
        editor.refreshSelection();
    }

    function setHand(row, idx, value) {
        editor.selectRow(row);
        editor.allNotes[idx].hand = value;
        noteModel.setProperty(row, "hand", value);
        noteModel.setProperty(row, "changed", rowIsChanged(idx));
        recount();
        // A hand change moves the note to the other staff, so the strip must
        // re-engrave even though nothing about its timing moved.
        editor.refreshSelection();
    }

    function resetRow(row, idx) {
        editor.selectRow(row);
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
        editor.refreshSelection();
    }

    // --- Navigation ---------------------------------------------------------

    function jumpToMeasure(m) {
        var target = -1;
        for (var row = 0; row < noteModel.count; row++) {
            if (noteModel.get(row).bar >= m) { target = row; break; }
        }
        // Past the last bar: land on the last note rather than doing nothing,
        // so the stepper visibly clamps instead of appearing broken.
        if (target < 0) target = noteModel.count - 1;
        if (target < 0) return;
        noteList.positionViewAtIndex(target, ListView.Beginning);
        // The sticky section label floats over the top row.
        noteList.contentY = Math.max(0, noteList.contentY - noteList.sectionHeaderHeight);
        editor.selectRow(target);
    }

    // --- Preview ------------------------------------------------------------

    function notesInBar(m) {
        if (m <= 0) return [];
        var start = notationWindow.barStartBeat(m);
        var end = notationWindow.barEndBeat(m);
        var out = [];
        for (var i = 0; i < editor.allNotes.length; i++) {
            var n = editor.allNotes[i];
            if (n.beat >= end || (n.beat + n.duration) <= start) continue;
            out.push({ pitch: n.pitch, beat: n.beat, duration: n.duration });
        }
        return out;
    }

    function previewSelectedNote() {
        if (!editor.audioAvailable || editor.selectedIdx < 0) return;
        var n = editor.allNotes[editor.selectedIdx];
        appState.hardware.play_preview([{ pitch: n.pitch, beat: n.beat, duration: n.duration }],
                                       n.beat, n.beat + n.duration, editor.songBpm);
    }

    function previewSelectedBar() {
        if (!editor.audioAvailable || editor.stripBar <= 0) return;
        var notes = editor.notesInBar(editor.stripBar);
        if (notes.length === 0) return;
        appState.hardware.play_preview(notes,
                                       notationWindow.barStartBeat(editor.stripBar),
                                       notationWindow.barEndBeat(editor.stripBar),
                                       editor.songBpm);
    }

    function stopPreview() {
        if (!!appState && !!appState.hardware) appState.hardware.stop_preview();
    }

    function save() {
        errorText = "";
        editor.stopPreview();
        var msg = appState.music21Service.save_user_song_notes(editor.songId, editor.allNotes);
        if (msg !== "") {
            errorText = msg;
            return;
        }
        editor.saved();
        editor.close();
    }

    ListModel { id: noteModel }

    NotationWindow { id: notationWindow }

    Timer {
        id: stripTimer
        interval: 80
        repeat: false
        onTriggered: editor.rebuildStrip()
    }

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
        // `enabled` is Item's own, and it propagates to the MouseArea below, so
        // a disabled chip stops responding without any extra wiring.
        opacity: chip.enabled ? 1.0 : 0.4
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

        // ── Filter bar ───────────────────────────────────────────────
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
                        // The selection is kept even when the filter hides it —
                        // losing your place because you looked at one hand is
                        // exactly what this editor should not do. Only the row
                        // highlight goes away.
                        var r = editor.rowForIdx(editor.selectedIdx);
                        noteList.currentIndex = r;
                        if (r >= 0) noteList.positionViewAtIndex(r, ListView.Contain);
                    }
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

        // ── Notation strip ───────────────────────────────────────────
        // A few bars around the selection, engraved from the working copy, so
        // an unsaved edit is visible in the music before it is committed.
        Rectangle {
            id: stripFrame
            Layout.fillWidth: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            // Below roughly 225px the enhanced style stops fitting note labels
            // inside their capsules and moves them outside; the floor keeps the
            // strip legible on a short window rather than letting it degrade.
            Layout.preferredHeight: Math.max(180 * editor.uiScale,
                                             Math.min(240 * editor.uiScale, editor.height * 0.26))
            radius: 8 * editor.uiScale
            // NotationView paints dark ink with no background of its own.
            color: "#fcfcfc"
            border.color: "#333333"
            clip: true

            // Mirrors STAFF_SPACE_RATIO / STAFF_SEPARATION_SPACES in
            // notation_view.py, exactly as EnhancedSheetMusic.qml does, so the
            // barline overlay lines up with the painted staff. Change them in
            // both places or the overlay desyncs.
            readonly property real lineSpacing: height * 0.0525
            readonly property real trebleCenterY: (height * 0.5) - (lineSpacing * 4.0)
            readonly property real bassCenterY: (height * 0.5) + (lineSpacing * 4.0)
            readonly property real noteStartX: width * 0.28
            readonly property real pixelsPerBeat: width * 0.10

            NotationView {
                id: stripNotation
                anchors.fill: parent

                displayMode: "trainer"
                isScrollingMode: true
                notationStyle: (!!appState && !!appState.settingsService)
                               ? appState.settingsService.notationStyle.toLowerCase() : "enhanced"
                notationColorMode: (!!appState && !!appState.settingsService)
                                   ? appState.settingsService.notationColorMode.toLowerCase() : "pedagogical"
                songKeySharps: editor.keySharps

                scrollBeat: editor.selectedIdx >= 0 ? notationWindow.scrollBeat() : 0.0
                // The loop band is the selection highlight: it marks a beat
                // range across both staves, which is the right shape for an
                // editor whose subject is when a note starts and how long it
                // lasts. -1 disables it.
                loopStartBeat: editor.selectedIdx >= 0 ? editor.selBeat : -1.0
                loopEndBeat: editor.selectedIdx >= 0 ? editor.selBeat + editor.selDuration : -1.0
            }

            // Barlines and bar numbers. Drawn here rather than by the engine:
            // the enhanced style skips barline items entirely, and nothing in
            // notation_view.py numbers a bar.
            Repeater {
                model: editor.stripBarlines

                delegate: Item {
                    readonly property real lineX: stripFrame.noteStartX
                                                  + (modelData.beat - stripNotation.scrollBeat) * stripFrame.pixelsPerBeat
                    readonly property bool isCurrent: modelData.bar === editor.stripBar

                    visible: lineX >= stripFrame.width * 0.15 && lineX <= stripFrame.width

                    Rectangle {
                        x: parent.lineX
                        y: stripFrame.trebleCenterY - (stripFrame.lineSpacing * 2.0)
                        width: Math.max(1, editor.uiScale)
                        height: (stripFrame.bassCenterY - stripFrame.trebleCenterY)
                                + (stripFrame.lineSpacing * 4.0)
                        color: parent.isCurrent ? editor.accent : "#999999"
                    }
                    Text {
                        x: parent.lineX + 3 * editor.uiScale
                        y: stripFrame.trebleCenterY - (stripFrame.lineSpacing * 4.4)
                        text: modelData.bar
                        color: parent.isCurrent ? editor.accent : "#999999"
                        font.pixelSize: 10 * editor.uiScale
                        font.bold: parent.isCurrent
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: editor.selectedIdx < 0
                text: "Click a note below to see it in the score."
                color: "#999999"
                font.pixelSize: 12 * editor.uiScale
            }
        }

        // ── Position and preview ─────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            spacing: 6 * editor.uiScale

            HeaderCell { text: "GO TO BAR" }
            Stepper {
                id: measureJump
                value: 1
                step: 1
                decimals: 0
                onStepped: (v) => {
                    measureJump.value = Math.min(editor.barCount, Math.max(1, v));
                    editor.jumpToMeasure(measureJump.value);
                }
            }
            Text {
                text: editor.stripBar > 0
                      ? "bar " + editor.stripBar + " of " + editor.barCount
                      : editor.barCount + " bars"
                color: "#666666"
                font.pixelSize: 11 * editor.uiScale
            }

            Item { Layout.preferredWidth: 18 * editor.uiScale }

            Chip {
                label: "♪ NOTE"
                accent: "#2196F3"
                enabled: editor.audioAvailable && editor.selectedIdx >= 0
                onClicked: editor.previewSelectedNote()
            }
            Chip {
                label: "▶ BAR"
                accent: "#2196F3"
                enabled: editor.audioAvailable && editor.stripBar > 0
                onClicked: editor.previewSelectedBar()
            }

            Item { Layout.fillWidth: true }

            Text {
                text: editor.audioHint
                visible: editor.audioHint !== ""
                color: "#ffa726"
                font.pixelSize: 10 * editor.uiScale
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
            focus: true
            // ListView, not Repeater: a song is easily thousands of notes and
            // only ListView creates delegates lazily.
            model: noteModel
            cacheBuffer: 400 * editor.uiScale
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            readonly property real sectionHeaderHeight: 22 * editor.uiScale

            // Sticky bar headers. The pin comes from CurrentLabelAtStart —
            // headerPositioning governs the list-wide header, not section
            // labels. Grouped on barLabel, which is the bar the note was in
            // when the list was built and never changes afterwards, so a run
            // can never split.
            section.property: "barLabel"
            section.criteria: ViewSection.FullString
            section.labelPositioning: ViewSection.CurrentLabelAtStart | ViewSection.NextLabelAtEnd
            section.delegate: Rectangle {
                width: ListView.view.width
                height: noteList.sectionHeaderHeight
                // Opaque: a sticky label floats over the rows beneath it.
                color: "#1c1c1e"
                z: 3

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    x: 4 * editor.uiScale
                    text: section
                    color: "#4CAF50"
                    font.pixelSize: 9 * editor.uiScale
                    font.bold: true
                    font.letterSpacing: 2 * editor.uiScale
                }
            }

            onCurrentIndexChanged: if (currentIndex >= 0) editor.selectRow(currentIndex)

            Keys.onSpacePressed: editor.previewSelectedNote()
            Keys.onReturnPressed: editor.previewSelectedBar()

            delegate: Rectangle {
                id: noteRow
                width: ListView.view.width
                height: 38 * editor.uiScale
                radius: 6 * editor.uiScale
                color: model.changed ? editor.tint(editor.accent, 0.12)
                                     : (index % 2 === 0 ? "#2a2a2a" : "#242426")
                border.color: noteRow.ListView.isCurrentItem ? "#2196F3"
                            : (model.changed ? editor.accent : "transparent")

                // Declared before the RowLayout so it sits underneath the Chip
                // and Stepper mouse areas: clicking the row body selects and
                // previews, clicking a control just does its own job.
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        editor.selectRow(index);
                        editor.previewSelectedNote();
                    }
                }

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
                onClicked: {
                    editor.stopPreview();
                    editor.close();
                }
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
