// Note editor for imported songs: where a note starts, how long it lasts, and
// which hand plays it.
//
// MIDI import guesses at all three — onsets are quantized, durations rounded,
// hands inferred by track or by a Viterbi pass — and a live recording gets
// them wrong in recognisable ways: a note a 16th late, a chord smeared across
// two grid positions, a whole passage shifted, a hand misjudged. This is where
// those are put right. Notes cannot be added and pitch is fixed, so every row
// keeps its original provenance (deletions are flagged `deleted: true` and
// dropped on save; save_user_song_notes refuses an incomplete or empty list).
//
// Three parts, top to bottom:
//   - a notation strip showing the bar the selected note lives in, engraved
//     from the working copy so an unsaved edit is visible as music;
//   - a piano roll (PianoRoll.qml) where notes are dragged, boxed and flipped;
//   - a selection bar with a button for everything the keyboard can do.
//
// The working copy and every editing rule live in NoteEdits.qml (`edits`);
// this file and the roll are views of it. Nothing touches disk until Save,
// which makes Cancel a complete undo.
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

    property var barlines: []
    property string errorText: ""
    readonly property int changedCount: edits.changedCount
    // PianoRoll has a property called `edits` too, so inside it the bare id
    // would resolve to itself; this gives it a qualified name to bind to.
    property alias noteEdits: edits

    // Key, metre and tempo — everything the strip and the preview need that a
    // note does not carry.
    property int keySharps: 0
    property var timeSignatures: []
    property real songBpm: 100.0

    // --- Selection ---------------------------------------------------------
    // The note the strip and the preview follow: the last one clicked.
    readonly property int selectedIdx: edits.primary
    // Mirrors of that note, refreshed explicitly rather than bound: a note is a
    // plain JS object mutated in place, so a binding over it would never
    // re-evaluate.
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
    readonly property color leftColor: "#2196F3"
    readonly property color rightColor: "#FF9800"
    function tint(c, a) { return Qt.rgba(c.r, c.g, c.b, a); }

    signal saved()

    // Sized against the window rather than in fixed pixels, and every internal
    // dimension is a uiScale multiple. Wide, because the roll's whole point is
    // seeing a note against its neighbours.
    readonly property real hostWidth: parent ? parent.width
                                    : ((typeof mainWindow !== "undefined" && mainWindow) ? mainWindow.width : 1280)
    readonly property real hostHeight: parent ? parent.height
                                     : ((typeof mainWindow !== "undefined" && mainWindow) ? mainWindow.height : 800)

    parent: (typeof mainWindow !== "undefined" && mainWindow && mainWindow.contentItem)
            ? mainWindow.contentItem : null
    anchors.centerIn: parent
    width: Math.min(hostWidth * 0.94, 1700 * uiScale)
    height: hostHeight * 0.92
    modal: true
    focus: true
    // Escape only — CloseOnPressOutside would silently discard unsaved edits.
    // And not even Escape once something has changed: it is also the key that
    // lets go of a selection, so a second press must not throw the work away.
    // Cancel is then the one way to discard.
    closePolicy: editor.changedCount > 0 ? Popup.NoAutoClose : Popup.CloseOnEscape

    onOpened: roll.forceActiveFocus()
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
        selBeat = 0.0;
        selDuration = 0.0;

        var svc = (!!appState && !!appState.music21Service) ? appState.music21Service : null;
        var raw = svc ? svc.get_user_song_notes(editor.songId) : [];
        editor.barlines = svc ? svc.get_user_song_barlines(editor.songId) : [];

        var ctx = svc ? svc.get_user_song_notation_context(editor.songId) : null;
        editor.keySharps = ctx ? ctx.key_sharps : 0;
        editor.timeSignatures = ctx ? ctx.time_signatures : [];
        editor.songBpm = ctx ? ctx.bpm : 100.0;

        edits.handFilter = "all";
        edits.load(raw, editor.barlines);

        // Open on the first bar rather than an empty strip.
        editor.stripBar = raw.length > 0 ? 1 : 0;
        measureJump.value = 1;
        editor.syncWindow();
        roll.reload();
        editor.rebuildStrip();
    }

    // --- Selection and the strip -------------------------------------------

    // Runs on every change in `edits`: keeps the strip on the note being
    // worked on. With nothing selected the strip stays where it was — clearing
    // the selection should not blank the music.
    function refreshSelection() {
        var idx = editor.selectedIdx;
        if (idx >= 0 && idx < edits.notes.length) {
            var n = edits.notes[idx];
            editor.selBeat = n.beat;
            editor.selDuration = n.duration;
            if (n.measure !== editor.stripBar) {
                editor.stripBar = n.measure;
                // GO TO BAR doubles as the position readout, so it follows the
                // selection rather than free-running.
                measureJump.value = Math.min(editor.barCount, n.measure);
            }
        }
        editor.syncWindow();
        editor.scheduleStrip();
    }

    // Where the strip is looking. Cheap — assignments and a walk over the
    // barlines — so it runs on every edit, keeping the scroll position and the
    // bar numbering exactly in step with the drag.
    function syncWindow() {
        notationWindow.notes = edits.notes;
        notationWindow.barlines = editor.barlines;
        notationWindow.timeSignatures = editor.timeSignatures;
        notationWindow.bar = editor.stripBar;
        notationWindow.selBeat = editor.selBeat;
        notationWindow.selDuration = editor.selDuration;
        editor.stripBarlines = notationWindow.barlinesInWindow();
    }

    // Re-engraving is the one expensive part — it scans the whole working copy
    // — so it is coalesced: a drag fires far faster than anyone can read the
    // result. Re-assigning an identical window is a no-op inside NotationView,
    // which compares by value, so over-triggering is free.
    function scheduleStrip() { stripTimer.restart(); }

    function rebuildStrip() {
        editor.syncWindow();
        stripNotation.scrollingNotes = notationWindow.build();
    }

    property var stripBarlines: []

    // --- Navigation ---------------------------------------------------------

    function jumpToMeasure(m) {
        var start = notationWindow.barStartBeat(m);
        roll.showBeat(start);
        // Land on the bar's first note when it has one, so the strip, the
        // preview and the keyboard all pick up from there.
        var idx = edits.firstFrom(start);
        if (idx >= 0 && edits.notes[idx].beat < notationWindow.barEndBeat(m) - 1e-6) {
            edits.selectOnly(idx);
        } else {
            edits.clear();
            editor.stripBar = m;
            editor.selBeat = start;
            editor.selDuration = 0.0;
            editor.syncWindow();
            editor.scheduleStrip();
        }
    }

    // --- What is selected, in words -----------------------------------------

    function trim(v) {
        // 1 → "1", 1.5 → "1.5", 1.25 → "1.25"
        return String(Math.round(v * 100) / 100);
    }

    function selectionText() {
        // Named so the binding re-evaluates on every edit.
        var rev = edits.revision;
        var count = edits.selectedCount;
        if (count === 0)
            return "Click a note to select it, or drag across empty space to select several.";
        if (count > 1)
            return count + " notes selected";
        var n = edits.notes[edits.primary];
        if (!n) return "";
        var beatInBar = n.beat - notationWindow.barStartBeat(n.measure) + 1;
        return n.name + "  ·  bar " + n.measure + ", beat " + editor.trim(beatInBar)
             + "  ·  " + editor.trim(n.duration) + (n.duration === 1 ? " beat long" : " beats long")
             + "  ·  " + (n.hand === "left" ? "left hand" : "right hand");
    }

    // --- Preview ------------------------------------------------------------

    function notesInBar(m) {
        if (m <= 0) return [];
        var start = notationWindow.barStartBeat(m);
        var end = notationWindow.barEndBeat(m);
        var out = [];
        for (var i = 0; i < edits.notes.length; i++) {
            var n = edits.notes[i];
            if (n.deleted) continue;
            if (n.beat >= end || (n.beat + n.duration) <= start) continue;
            out.push({ pitch: n.pitch, beat: n.beat, duration: n.duration });
        }
        return out;
    }

    function previewSelectedNote() {
        if (!editor.audioAvailable || editor.selectedIdx < 0) return;
        var n = edits.notes[editor.selectedIdx];
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
        var msg = appState.music21Service.save_user_song_notes(editor.songId, edits.notes);
        if (msg !== "") {
            errorText = msg;
            return;
        }
        editor.saved();
        editor.close();
    }

    NoteEdits {
        id: edits
        grid: editor.grid
        onRevisionChanged: editor.refreshSelection()
    }

    NotationWindow { id: notationWindow }

    Timer {
        id: stripTimer
        interval: 80
        repeat: false
        onTriggered: editor.rebuildStrip()
    }

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

        // A MouseArea takes no keyboard focus, so pressing a chip leaves the
        // roll's shortcuts live.
        MouseArea {
            id: chipMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: chip.clicked()
        }
    }

    // ◀ value ▶
    component Stepper : RowLayout {
        id: stepper
        property real value: 0
        property real step: editor.grid
        property int decimals: 2
        signal stepped(real newValue)

        spacing: 2 * editor.uiScale

        Chip {
            label: "◀"
            onClicked: stepper.stepped(stepper.value - stepper.step)
        }
        Text {
            Layout.preferredWidth: 40 * editor.uiScale
            horizontalAlignment: Text.AlignHCenter
            text: stepper.value.toFixed(stepper.decimals)
            color: "white"
            font.pixelSize: 11 * editor.uiScale
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

    component Gap : Item { Layout.preferredWidth: 10 * editor.uiScale }

    contentItem: ColumnLayout {
        spacing: 8 * editor.uiScale

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

        // ── Toolbar: where you are, what you hear, how much you see ──
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
                text: "of " + editor.barCount
                color: "#666666"
                font.pixelSize: 11 * editor.uiScale
            }

            Gap {}

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

            Gap {}

            // A hand that is filtered out stays on screen, dimmed, but cannot
            // be clicked or boxed — so one hand's passage can be selected and
            // slid without picking up the other's.
            HeaderCell { text: "EDIT" }
            Repeater {
                model: [
                    { mode: "all",   label: "Both hands" },
                    { mode: "right", label: "RH only" },
                    { mode: "left",  label: "LH only" }
                ]
                delegate: Chip {
                    label: modelData.label
                    active: edits.handFilter === modelData.mode
                    accent: modelData.mode === "left" ? editor.leftColor
                          : modelData.mode === "right" ? editor.rightColor : editor.accent
                    onClicked: edits.handFilter = modelData.mode
                }
            }

            Gap {}

            HeaderCell { text: "ZOOM" }
            Chip { label: "−"; onClicked: roll.zoomBy(0.8) }
            Chip { label: "+"; onClicked: roll.zoomBy(1.25) }

            Gap {}

            Chip {
                label: "UNDO"
                enabled: edits.undoDepth > 0
                onClicked: edits.undo()
            }
            Chip {
                label: "REDO"
                enabled: edits.redoDepth > 0
                onClicked: edits.redo()
            }

            Item { Layout.fillWidth: true }

            Text {
                text: editor.audioHint
                visible: editor.audioHint !== ""
                color: "#ffa726"
                font.pixelSize: 10 * editor.uiScale
                elide: Text.ElideRight
                Layout.maximumWidth: 260 * editor.uiScale
                Layout.minimumWidth: 0
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
            // Kept near its floor so the roll gets the room. Below roughly
            // 225px the enhanced style stops fitting note labels inside their
            // capsules and moves them outside; the floor keeps the strip
            // legible on a short window rather than letting it degrade.
            Layout.preferredHeight: Math.max(180 * editor.uiScale,
                                             Math.min(210 * editor.uiScale, editor.height * 0.22))
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

                scrollBeat: editor.stripBar > 0 ? notationWindow.scrollBeat() : 0.0
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
        }

        // ── The piano roll ───────────────────────────────────────────
        PianoRoll {
            id: roll
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            edits: editor.noteEdits
            geometry: notationWindow
            uiScale: editor.uiScale

            onNoteClicked: editor.previewSelectedNote()
            onPreviewNoteRequested: editor.previewSelectedNote()
            onPreviewBarRequested: editor.previewSelectedBar()
        }

        // ── Selection bar ────────────────────────────────────────────
        // Always present, so the roll above never changes height when a
        // selection comes and goes. Every keyboard action has a button here.
        RowLayout {
            id: selectionBar
            Layout.fillWidth: true
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            Layout.preferredHeight: 26 * editor.uiScale
            spacing: 5 * editor.uiScale

            readonly property bool any: edits.selectedCount > 0
            readonly property bool several: edits.selectedCount > 1

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: editor.selectionText()
                color: selectionBar.any ? "white" : "#888888"
                font.pixelSize: 11 * editor.uiScale
                font.bold: selectionBar.any
                elide: Text.ElideRight
            }

            HeaderCell { text: "MOVE" }
            Chip {
                label: "◀"
                enabled: selectionBar.any
                onClicked: { edits.moveBy(-editor.grid); roll.ensureVisible(edits.primary); }
            }
            Chip {
                label: "▶"
                enabled: selectionBar.any
                onClicked: { edits.moveBy(editor.grid); roll.ensureVisible(edits.primary); }
            }

            Gap {}

            HeaderCell { text: "LENGTH" }
            Chip {
                label: "−"
                enabled: selectionBar.any
                onClicked: edits.resizeBy(-editor.grid)
            }
            Chip {
                label: "+"
                enabled: selectionBar.any
                onClicked: edits.resizeBy(editor.grid)
            }

            Gap {}

            HeaderCell { text: "HAND" }
            Chip {
                label: "L"
                accent: editor.leftColor
                enabled: selectionBar.any
                active: selectionBar.any && !selectionBar.several
                        && edits.revision >= 0 && !!edits.notes[edits.primary]
                        && edits.notes[edits.primary].hand === "left"
                onClicked: edits.setHand("left")
            }
            Chip {
                label: "R"
                accent: editor.rightColor
                enabled: selectionBar.any
                active: selectionBar.any && !selectionBar.several
                        && edits.revision >= 0 && !!edits.notes[edits.primary]
                        && edits.notes[edits.primary].hand === "right"
                onClicked: edits.setHand("right")
            }

            Gap {}

            Chip {
                label: "LINE UP"
                enabled: selectionBar.several
                onClicked: edits.alignStarts()
            }
            Chip {
                label: "SAME LENGTH"
                enabled: selectionBar.several
                onClicked: edits.matchLengths()
            }
            Chip {
                label: "SELECT ALL AFTER"
                enabled: selectionBar.any
                onClicked: edits.extendToEnd()
            }
            Chip {
                label: "DELETE"
                accent: editor.danger
                enabled: selectionBar.any
                onClicked: edits.deleteSelection()
            }
            Chip {
                label: "↺ RESET"
                accent: "#888888"
                enabled: selectionBar.any
                onClicked: edits.resetSelection()
            }
        }

        // ── How to ───────────────────────────────────────────────────
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.leftMargin: 14 * editor.uiScale
            Layout.rightMargin: 14 * editor.uiScale
            text: "Drag a note to move it  ·  drag its right end to change length  ·  "
                + "double-click to switch hand  ·  ← → nudge  ·  Alt ← → length  ·  "
                + "L / R hand  ·  A line up  ·  Del delete  ·  Ctrl+Z undo  ·  Ctrl+wheel zoom"
            color: "#666666"
            font.pixelSize: 10 * editor.uiScale
            elide: Text.ElideRight
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
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                elide: Text.ElideRight
            }

            Item { Layout.fillWidth: true; visible: editor.changedCount === 0 }

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
