// Projects the song editor's working copy into a short span of notation.
//
// The editor holds thousands of flat per-note rows and must show the bar you
// are working in *as you edit it*, before anything is saved. Rebuilding the
// whole song for the strip would re-engrave thousands of items on every nudge,
// so this cuts a window of a few bars around the selection instead — the array
// it produces is tens of items, which is what makes a rebuild per keystroke
// affordable.
//
// The item format is NotationView's `scrollingNotes` contract. The reference
// producer is _setup_song_target in logic/services/chord_trainer.py (the
// barline/time-signature/sort details live there); the consumer is
// _render_scrolling_array in ui/notation_view.py. This builder deliberately
// emits a subset: the editor's rows carry no rests, dynamics, ties, beams,
// tuplets or spellings, and it emits no barlines either because the strip draws
// those itself as an overlay (the enhanced style skips barline items entirely,
// so they cannot be relied on for bar numbering).
//
// Split out of SongNoteEditor.qml so the windowing rules are testable — see
// tests/test_strip_window.py, which drives build() directly.

import QtQuick

QtObject {
    id: root

    // --- Input ---------------------------------------------------------------

    // The editor's working copy: [{pitch, beat, duration, hand, finger}, ...].
    property var notes: []

    // Beat offsets of the barlines, as stored on the record. barlines[i] begins
    // measure i + 2; measure 1 begins at beat 0.
    property var barlines: []

    // 1-based measure the selection sits in. 0 means nothing is selected, which
    // is a real state — the editor opens that way — and yields an empty window.
    property int bar: 0

    property real selBeat: 0.0
    property real selDuration: 0.0

    // [{offset, numerator, denominator}, ...], ascending. Used for the strip's
    // header and to size a bar that has no barline after it.
    property var timeSignatures: []

    // Fallback bar length when the metre is unknown.
    property real defaultBarBeats: 4.0

    // --- Tuning --------------------------------------------------------------

    // How far past its own downbeat a selection may sit before the window
    // anchors on the note rather than the bar. Beyond this the note has been
    // dragged well past where its bar starts and anchoring on the bar would
    // leave it off the right-hand edge.
    property real anchorSlackBeats: 6.0

    // Beats of the previous bar kept visible to the left of the anchor.
    property real leadInBeats: 1.0

    // --- Metre ---------------------------------------------------------------

    function timeSignatureAt(beat) {
        var sig = { numerator: 4, denominator: 4 };
        var list = root.timeSignatures || [];
        for (var i = 0; i < list.length; i++) {
            var ts = list[i];
            if (!ts || ts.numerator === undefined || ts.denominator === undefined)
                continue;
            if (!(ts.numerator > 0) || !(ts.denominator > 0))
                continue;
            if ((ts.offset || 0.0) <= beat + 1e-6)
                sig = { numerator: ts.numerator, denominator: ts.denominator };
            else
                break;
        }
        return sig;
    }

    function barBeatsAt(beat) {
        var sig = root.timeSignatureAt(beat);
        var beats = sig.numerator * 4.0 / sig.denominator;
        return beats > 0 ? beats : root.defaultBarBeats;
    }

    // --- Bar geometry --------------------------------------------------------

    function barStartBeat(m) {
        if (m <= 1)
            return 0.0;
        var lines = root.barlines || [];
        if (m - 2 < lines.length)
            return lines[m - 2];
        // Past the last stored barline: keep extending in the final metre, so a
        // note dragged beyond the end of the song still lands in a plausible bar
        // instead of collapsing onto the last barline.
        var last = lines.length > 0 ? lines[lines.length - 1] : 0.0;
        var lastBar = lines.length + 1;
        return last + (m - lastBar) * root.barBeatsAt(last);
    }

    function barEndBeat(m) {
        var lines = root.barlines || [];
        if (m - 1 < lines.length)
            return lines[m - 1];
        var start = root.barStartBeat(m);
        return start + root.barBeatsAt(start);
    }

    // --- The window ----------------------------------------------------------

    // One bar either side of the current one, widened so the selection is always
    // inside it however far it has been dragged.
    function windowStart() {
        var w0 = root.barStartBeat(Math.max(1, root.bar - 1));
        return Math.min(w0, root.selBeat);
    }

    function windowEnd() {
        var w1 = root.barEndBeat(root.bar + 1);
        return Math.max(w1, root.selBeat + root.selDuration);
    }

    // The beat NotationView should scroll to. Anchoring on the bar's downbeat
    // keeps the bar in a stable place on screen while you edit inside it.
    function scrollBeat() {
        if (root.bar <= 0)
            return 0.0;
        var barStart = root.barStartBeat(root.bar);
        var anchor = (root.selBeat - barStart > root.anchorSlackBeats) ? root.selBeat : barStart;
        return anchor - root.leadInBeats;
    }

    // --- Projection ----------------------------------------------------------

    // Mirrors the ordering in _setup_song_target: by beat, then time signatures
    // ahead of dynamics ahead of barlines ahead of notes, then by pitch. Only
    // the time-signature and note branches can occur here, but the full order is
    // kept so the two producers cannot drift.
    function _compare(a, b) {
        var ab = a.start_beat || 0.0, bb = b.start_beat || 0.0;
        if (ab !== bb) return ab - bb;
        var at = a.is_time_sig ? 0 : 1, bt = b.is_time_sig ? 0 : 1;
        if (at !== bt) return at - bt;
        var ad = a.is_dynamic ? 0 : 1, bd = b.is_dynamic ? 0 : 1;
        if (ad !== bd) return ad - bd;
        var al = a.is_barline ? 0 : 1, bl = b.is_barline ? 0 : 1;
        if (al !== bl) return al - bl;
        return (a.pitch || 0) - (b.pitch || 0);
    }

    function build() {
        if (root.bar <= 0)
            return [];

        var w0 = root.windowStart();
        var w1 = root.windowEnd();

        // NotationView reads the FIRST is_time_sig item in the array to draw the
        // static header, so the window always opens with the metre in force —
        // otherwise a window starting mid-piece would be labelled 4/4. It sits
        // at beat 0 and is never drawn inline, because _draw_scrolling_item only
        // draws a signature whose start_beat is greater than zero.
        var header = root.timeSignatureAt(w0);
        var out = [{
            "is_time_sig": true,
            "start_beat": 0.0,
            "numerator": header.numerator,
            "denominator": header.denominator
        }];

        // Metre changes that fall inside the window still need drawing inline.
        var sigs = root.timeSignatures || [];
        for (var s = 0; s < sigs.length; s++) {
            var ts = sigs[s];
            if (!ts) continue;
            var off = ts.offset || 0.0;
            if (off > w0 + 1e-6 && off < w1 && ts.numerator > 0 && ts.denominator > 0) {
                out.push({
                    "is_time_sig": true,
                    "start_beat": off,
                    "numerator": ts.numerator,
                    "denominator": ts.denominator
                });
            }
        }

        // A linear scan, deliberately: `notes` is beat-sorted when the editor
        // loads it but is never re-sorted afterwards, because re-sorting would
        // move rows out from under the cursor mid-edit. A bisect would therefore
        // be silently wrong as soon as anything is dragged.
        var list = root.notes || [];
        for (var i = 0; i < list.length; i++) {
            var n = list[i];
            if (!n) continue;
            var beat = n.beat || 0.0;
            var duration = n.duration || 0.0;
            // Overlap, not onset: a note held over from the previous bar is part
            // of what you are looking at, and dropping it would silently remove
            // the context that explains the bar.
            if (beat >= w1 || (beat + duration) <= w0)
                continue;
            out.push({
                "pitch": n.pitch,
                "spelling": null,
                "hand": n.hand === "left" ? "L" : "R",
                "finger": n.finger !== undefined ? n.finger : 1,
                "tie": null,
                "beam": null,
                "tuplet": null,
                "start_beat": beat,
                "duration_beats": duration
            });
        }

        out.sort(root._compare);
        return out;
    }

    // The barlines the strip's overlay should draw, each tagged with the measure
    // it begins so the overlay can number them.
    function barlinesInWindow() {
        if (root.bar <= 0)
            return [];

        var w0 = root.windowStart();
        var w1 = root.windowEnd();
        var out = [];

        if (w0 <= 1e-6)
            out.push({ "beat": 0.0, "bar": 1 });

        var lines = root.barlines || [];
        for (var i = 0; i < lines.length; i++) {
            var b = lines[i];
            if (b >= w0 - 1e-6 && b <= w1 + 1e-6)
                out.push({ "beat": b, "bar": i + 2 });
        }
        return out;
    }
}
