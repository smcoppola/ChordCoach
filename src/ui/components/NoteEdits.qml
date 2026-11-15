// The song editor's working copy, and every rule for changing it.
//
// SongNoteEditor.qml and PianoRoll.qml are views: they turn clicks, drags and
// keys into calls here and redraw when `revision` moves. Keeping the rules in
// one object with no visuals is what makes them testable without a mouse — see
// tests/test_note_edits.py.
//
// The contract with Python is unchanged from the table editor this replaced:
// editing is modify-only. Notes are never added, removed or re-pitched, and
// `notes` is never reordered, so the list that goes back to
// save_user_song_notes is the one that came out of get_user_song_notes with
// only beat, duration and hand altered.

import QtQuick

QtObject {
    id: root

    // --- State ---------------------------------------------------------------

    // [{beat, duration, hand, pitch, name, measure, finger, step_index,
    //   note_index}, ...] — plain JS objects, mutated in place. Nothing bound to
    // a note can see that happen, which is what `revision` is for.
    property var notes: []
    // [{beat, duration, hand}, ...] as loaded, index-aligned with `notes`.
    property var pristine: []
    // Beat offsets of the barlines; barlines[i] begins measure i + 2.
    property var barlines: []

    // Every position and length is a multiple of this — the 16th-note grid
    // midi_ingestor quantizes to. Python snaps again on save.
    property real grid: 0.25

    // "all", "left" or "right". A hand that is filtered out is still drawn
    // (dimmed) but cannot be clicked or selected, so one hand's passage can be
    // boxed and slid without picking up the other's.
    property string handFilter: "all"
    onHandFilterChanged: root.revision++

    // Note index -> true. Replaced, never mutated, and always alongside a
    // `revision` bump.
    property var selected: ({})
    property int selectedCount: 0
    // The note last clicked: what the notation strip follows and what
    // matchLengths copies from. -1 when nothing is selected.
    property int primary: -1

    // Bumped on every change to a note or to the selection. Views re-read on it.
    property int revision: 0
    property int changedCount: 0
    property int undoDepth: 0
    property int redoDepth: 0

    readonly property int undoLimit: 200
    property var _undo: []
    property var _redo: []
    // The selected notes as they were when a drag began, or null.
    property var _gesture: null

    // --- Loading -------------------------------------------------------------

    function load(rows, barlineBeats) {
        var lines = [];
        var lineCount = barlineBeats ? barlineBeats.length : 0;
        for (var b = 0; b < lineCount; b++) lines.push(barlineBeats[b]);
        // Set first: the rows are numbered against it below, so a bar number
        // never depends on what the caller happened to put in `measure`.
        root.barlines = lines;

        var working = [], original = [];
        var count = rows ? rows.length : 0;
        for (var i = 0; i < count; i++) {
            var r = rows[i];
            // Copied: values handed across the Qt boundary are not reliably
            // mutable in place, and every edit below mutates.
            working.push({ beat: r.beat, duration: r.duration, hand: r.hand,
                           pitch: r.pitch, name: r.name,
                           measure: root.measureFor(r.beat),
                           finger: r.finger,
                           step_index: r.step_index, note_index: r.note_index });
            original.push({ beat: r.beat, duration: r.duration, hand: r.hand });
        }
        root.notes = working;
        root.pristine = original;
        root.selected = ({});
        root.selectedCount = 0;
        root.primary = -1;
        root._undo = [];
        root._redo = [];
        root.undoDepth = 0;
        root.redoDepth = 0;
        root._gesture = null;
        root.changedCount = 0;
        root.revision++;
    }

    // --- Small helpers -------------------------------------------------------

    function _round(v) { return Math.round(v * 10000) / 10000; }

    function _snapDelta(d) { return Math.round(d / root.grid) * root.grid; }

    function measureFor(beat) {
        var lines = root.barlines;
        var lo = 0, hi = lines.length;
        while (lo < hi) {
            var mid = (lo + hi) >> 1;
            if (lines[mid] <= beat + 1e-6) lo = mid + 1;
            else hi = mid;
        }
        return lo + 1;
    }

    function _selectable(i) {
        return root.handFilter === "all" || root.notes[i].hand === root.handFilter;
    }

    function isSelected(i) { return root.selected[i] === true; }

    function isChanged(i) {
        var a = root.notes[i], b = root.pristine[i];
        return a.beat !== b.beat || a.duration !== b.duration || a.hand !== b.hand;
    }

    // Ascending.
    function selectedIndices() {
        var out = [];
        var sel = root.selected;
        for (var k in sel) out.push(parseInt(k));
        out.sort(function (a, b) { return a - b; });
        return out;
    }

    function _recount() {
        var c = 0;
        for (var i = 0; i < root.notes.length; i++) if (root.isChanged(i)) c++;
        root.changedCount = c;
    }

    function _touch() {
        root._recount();
        root.revision++;
    }

    // --- Selection -----------------------------------------------------------

    function _setSelection(indices, primaryIdx) {
        var sel = {};
        for (var i = 0; i < indices.length; i++) sel[indices[i]] = true;
        root.selected = sel;
        root.selectedCount = indices.length;
        if (indices.length === 0)
            root.primary = -1;
        else if (primaryIdx !== undefined && sel[primaryIdx] === true)
            root.primary = primaryIdx;
        else if (sel[root.primary] !== true)
            root.primary = indices[0];
        root.revision++;
    }

    function selectOnly(i) {
        if (i < 0 || i >= root.notes.length) return;
        root._setSelection([i], i);
    }

    function toggle(i) {
        if (i < 0 || i >= root.notes.length) return;
        var current = root.selectedIndices();
        var at = current.indexOf(i);
        if (at >= 0) {
            current.splice(at, 1);
            root._setSelection(current);
        } else {
            current.push(i);
            root._setSelection(current, i);
        }
    }

    function setPrimary(i) {
        if (root.selected[i] !== true || root.primary === i) return;
        root.primary = i;
        root.revision++;
    }

    function clear() {
        if (root.selectedCount === 0) return;
        root._setSelection([]);
    }

    function selectAll() {
        var out = [];
        for (var i = 0; i < root.notes.length; i++) if (root._selectable(i)) out.push(i);
        root._setSelection(out);
    }

    // Every note that overlaps the beat range and sits in the pitch range.
    // Corners may come in either order — a box can be dragged in any direction.
    function selectBox(beatA, beatB, pitchA, pitchB, add) {
        var b0 = Math.min(beatA, beatB), b1 = Math.max(beatA, beatB);
        var p0 = Math.min(pitchA, pitchB), p1 = Math.max(pitchA, pitchB);
        var out = add ? root.selectedIndices() : [];
        var seen = add ? root.selected : {};
        for (var i = 0; i < root.notes.length; i++) {
            var n = root.notes[i];
            if (n.pitch < p0 || n.pitch > p1) continue;
            if (n.beat >= b1 || (n.beat + n.duration) <= b0) continue;
            if (!root._selectable(i) || seen[i] === true) continue;
            out.push(i);
        }
        root._setSelection(out);
    }

    // Every note starting at or after `beat`: the way to slide a whole passage.
    function selectFrom(beat) {
        var out = [];
        for (var i = 0; i < root.notes.length; i++) {
            if (root.notes[i].beat >= beat - 1e-6 && root._selectable(i)) out.push(i);
        }
        root._setSelection(out);
    }

    function selectionStart() {
        var m = -1;
        var sel = root.selected;
        for (var k in sel) {
            var b = root.notes[k].beat;
            if (m < 0 || b < m) m = b;
        }
        return m;
    }

    function extendToEnd() {
        if (root.selectedCount === 0) return;
        var keep = root.primary;
        root.selectFrom(root.selectionStart());
        if (root.selected[keep] === true) root.setPrimary(keep);
    }

    // --- Undo ----------------------------------------------------------------

    function _snapshot(indices) {
        var out = [];
        for (var i = 0; i < indices.length; i++) {
            var n = root.notes[indices[i]];
            out.push({ i: indices[i], beat: n.beat, duration: n.duration, hand: n.hand });
        }
        return out;
    }

    function _restore(states) {
        for (var i = 0; i < states.length; i++) {
            var s = states[i];
            var n = root.notes[s.i];
            n.beat = s.beat;
            n.duration = s.duration;
            n.hand = s.hand;
            n.measure = root.measureFor(s.beat);
        }
        root._touch();
    }

    // Records one undo step for whatever changed since `before` was taken.
    function _commit(before) {
        var changedBefore = [], changedAfter = [];
        for (var i = 0; i < before.length; i++) {
            var s = before[i];
            var n = root.notes[s.i];
            if (n.beat !== s.beat || n.duration !== s.duration || n.hand !== s.hand) {
                changedBefore.push(s);
                changedAfter.push({ i: s.i, beat: n.beat, duration: n.duration, hand: n.hand });
            }
        }
        if (changedBefore.length === 0) return;
        var stack = root._undo;
        stack.push({ before: changedBefore, after: changedAfter });
        if (stack.length > root.undoLimit) stack.shift();
        root._undo = stack;
        root._redo = [];
        root.undoDepth = stack.length;
        root.redoDepth = 0;
    }

    function undo() {
        var stack = root._undo;
        if (root._gesture !== null || stack.length === 0) return;
        var step = stack.pop();
        var redoStack = root._redo;
        redoStack.push(step);
        root._undo = stack;
        root._redo = redoStack;
        root.undoDepth = stack.length;
        root.redoDepth = redoStack.length;
        root._restore(step.before);
    }

    function redo() {
        var redoStack = root._redo;
        if (root._gesture !== null || redoStack.length === 0) return;
        var step = redoStack.pop();
        var stack = root._undo;
        stack.push(step);
        root._undo = stack;
        root._redo = redoStack;
        root.undoDepth = stack.length;
        root.redoDepth = redoStack.length;
        root._restore(step.after);
    }

    // --- Drags ---------------------------------------------------------------
    // A drag reports its total distance from where it began, not increments, so
    // the result never depends on how many mouse events it took to get there —
    // and the whole drag is one undo step.

    function beginGesture() {
        if (root._gesture !== null) return;
        root._gesture = root._snapshot(root.selectedIndices());
    }

    // Returns the delta actually applied, after snapping and clamping.
    function gestureMove(delta) {
        var g = root._gesture;
        if (g === null || g.length === 0) return 0;
        var d = root._snapDelta(delta);
        // The group stops when its earliest note reaches beat 0, and keeps its
        // shape: clamping each note separately would squash a chord flat.
        var first = g[0].beat;
        for (var i = 1; i < g.length; i++) if (g[i].beat < first) first = g[i].beat;
        if (d < -first) d = -first;
        for (var j = 0; j < g.length; j++) {
            var n = root.notes[g[j].i];
            n.beat = root._round(g[j].beat + d);
            n.duration = g[j].duration;
            n.measure = root.measureFor(n.beat);
        }
        root._touch();
        return d;
    }

    function gestureResize(delta) {
        var g = root._gesture;
        if (g === null || g.length === 0) return 0;
        var d = root._snapDelta(delta);
        for (var j = 0; j < g.length; j++) {
            var n = root.notes[g[j].i];
            n.beat = g[j].beat;
            n.measure = root.measureFor(n.beat);
            n.duration = Math.max(root.grid, root._round(g[j].duration + d));
        }
        root._touch();
        return d;
    }

    function endGesture() {
        var g = root._gesture;
        if (g === null) return;
        root._gesture = null;
        root._commit(g);
    }

    function cancelGesture() {
        var g = root._gesture;
        if (g === null) return;
        root._gesture = null;
        root._restore(g);
    }

    // --- Edits on the selection ----------------------------------------------

    function moveBy(delta) {
        if (root.selectedCount === 0 || root._gesture !== null) return;
        root.beginGesture();
        root.gestureMove(delta);
        root.endGesture();
    }

    function resizeBy(delta) {
        if (root.selectedCount === 0 || root._gesture !== null) return;
        root.beginGesture();
        root.gestureResize(delta);
        root.endGesture();
    }

    // Puts every selected note on the earliest selected start: a chord whose
    // notes landed on neighbouring 16ths becomes one chord.
    function alignStarts() {
        if (root.selectedCount < 2 || root._gesture !== null) return;
        var indices = root.selectedIndices();
        var before = root._snapshot(indices);
        var target = root.selectionStart();
        for (var i = 0; i < indices.length; i++) {
            var n = root.notes[indices[i]];
            n.beat = target;
            n.measure = root.measureFor(target);
        }
        root._commit(before);
        root._touch();
    }

    // Gives every selected note the primary note's length.
    function matchLengths() {
        if (root.selectedCount < 2 || root.primary < 0 || root._gesture !== null) return;
        var indices = root.selectedIndices();
        var before = root._snapshot(indices);
        var target = root.notes[root.primary].duration;
        for (var i = 0; i < indices.length; i++) root.notes[indices[i]].duration = target;
        root._commit(before);
        root._touch();
    }

    function setHand(hand) {
        if (root.selectedCount === 0 || root._gesture !== null) return;
        var value = (hand === "left") ? "left" : "right";
        var indices = root.selectedIndices();
        var before = root._snapshot(indices);
        for (var i = 0; i < indices.length; i++) root.notes[indices[i]].hand = value;
        root._commit(before);
        root._touch();
    }

    // One note, whatever is selected: the double-click.
    function flipHand(i) {
        if (i < 0 || i >= root.notes.length || root._gesture !== null) return;
        var before = root._snapshot([i]);
        root.notes[i].hand = (root.notes[i].hand === "left") ? "right" : "left";
        root._commit(before);
        root._touch();
    }

    function resetSelection() {
        if (root.selectedCount === 0 || root._gesture !== null) return;
        var indices = root.selectedIndices();
        var before = root._snapshot(indices);
        for (var i = 0; i < indices.length; i++) {
            var n = root.notes[indices[i]], p = root.pristine[indices[i]];
            n.beat = p.beat;
            n.duration = p.duration;
            n.hand = p.hand;
            n.measure = root.measureFor(p.beat);
        }
        root._commit(before);
        root._touch();
    }

    // --- What the view asks --------------------------------------------------
    // All linear scans, deliberately: `notes` is beat-sorted when loaded but is
    // never re-sorted, so a bisect would be silently wrong after the first drag.

    // The note under a point, or -1. Where notes overlap (two dragged onto the
    // same key and beat) a selected one wins, so what you are holding stays held.
    function noteAt(beat, pitch) {
        var found = -1;
        for (var i = 0; i < root.notes.length; i++) {
            var n = root.notes[i];
            if (n.pitch !== pitch) continue;
            if (beat < n.beat || beat >= n.beat + n.duration) continue;
            if (!root._selectable(i)) continue;
            if (root.selected[i] === true) return i;
            found = i;
        }
        return found;
    }

    // Indices of the notes overlapping [beat0, beat1), ascending.
    function indicesInRange(beat0, beat1) {
        var out = [];
        for (var i = 0; i < root.notes.length; i++) {
            var n = root.notes[i];
            if (n.beat >= beat1 || (n.beat + n.duration) <= beat0) continue;
            out.push(i);
        }
        return out;
    }

    // The earliest selectable note starting at or after `beat`, or -1.
    function firstFrom(beat) {
        var found = -1, foundBeat = 0;
        for (var i = 0; i < root.notes.length; i++) {
            var b = root.notes[i].beat;
            if (b < beat - 1e-6 || !root._selectable(i)) continue;
            if (found < 0 || b < foundBeat) { found = i; foundBeat = b; }
        }
        return found;
    }

    function pitchRange() {
        if (root.notes.length === 0) return { lo: 60, hi: 72 };
        var lo = 127, hi = 0;
        for (var i = 0; i < root.notes.length; i++) {
            var p = root.notes[i].pitch;
            if (p < lo) lo = p;
            if (p > hi) hi = p;
        }
        return { lo: lo, hi: hi };
    }

    function endBeat() {
        var end = 0;
        for (var i = 0; i < root.notes.length; i++) {
            var e = root.notes[i].beat + root.notes[i].duration;
            if (e > end) end = e;
        }
        return end;
    }
}
