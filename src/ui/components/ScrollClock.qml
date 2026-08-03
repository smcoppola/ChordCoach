// Frame-locked playhead clock.
//
// The beat position the notation scrolls to must advance by exactly the right
// amount on every displayed frame. A backend timer cannot supply that: it
// samples on its own schedule, and any value it pushes is already stale by an
// unknown fraction of a frame. Feeding those samples through a QML Behavior
// made it worse — a Behavior retargeted before it finishes restarts its easing
// curve, so a continuously moving target produces a sawtooth velocity that
// reads as judder.
//
// So the backend stops streaming positions and publishes an *anchor* instead:
// "at this moment the playhead was at beat B, advancing at R beats/second".
// This clock samples the display's own frame clock and extrapolates. Velocity
// is constant by construction between anchors, which is what makes the motion
// smooth.
//
// Anchors also arrive periodically as corrections, because the frame clock and
// the audio clock drift (a stalled compositor, an occluded window). Corrections
// are never applied as a jump; the residual is slewed out at a bounded rate so
// the music stays readable while the error is absorbed. Only a genuine
// discontinuity — start, seek, loop wrap — snaps.

import QtQuick

Item {
    id: root

    // --- Input ---------------------------------------------------------------

    // {beat: real, bps: real, snap: bool, seq: int} published by the backend.
    // seq must change on every anchor, including ones that repeat a value.
    property var anchor: null

    // Gates the frame clock. Nothing should run it when no transport is moving:
    // a running FrameAnimation keeps the whole render loop awake.
    property bool active: false

    // --- Output --------------------------------------------------------------

    // The extrapolated beat, updated once per displayed frame.
    property real beat: 0.0

    // --- Tuning --------------------------------------------------------------

    // Past this residual an anchor is a discontinuity, not drift, so it snaps.
    // Below it the error is absorbed silently.
    property real snapThresholdBeats: 0.75

    // Floor on how long a correction takes. Short enough to stay in sync,
    // long enough that a small residual is not a visible twitch.
    property real minCorrectionSeconds: 0.15

    // Ceiling on how much a correction may distort playback speed. At 0.25 the
    // music never scrolls more than 25% off tempo while absorbing drift, so a
    // correction is felt as nothing at all rather than as a lurch.
    property real maxCorrectionRate: 0.25

    // --- Internal ------------------------------------------------------------

    property real _anchorBeat: 0.0
    property real _anchorClock: 0.0
    property real _bps: 0.0
    property real _offset: 0.0          // residual still to be slewed out
    property real _offsetClock: 0.0
    property real _offsetSeconds: 0.0
    property int  _seenSeq: -1
    // Distinct from _seenSeq: that one deduplicates repeated anchor deliveries,
    // this one records whether there is a previous position worth preserving.
    // The first anchor has nothing to slew from, so it always lands directly.
    property bool _initialised: false

    function _residualAt(t) {
        if (root._offset === 0.0 || root._offsetSeconds <= 0.0)
            return 0.0;
        var k = (t - root._offsetClock) / root._offsetSeconds;
        if (k >= 1.0)
            return 0.0;
        // Linear decay, deliberately not eased: a linear ramp holds the velocity
        // error constant for the whole correction. An eased ramp would vary it,
        // which is the acceleration the eye picks up as jitter.
        return root._offset * (1.0 - k);
    }

    function beatAt(t) {
        return root._anchorBeat + (t - root._anchorClock) * root._bps + root._residualAt(t);
    }

    // `t` is the frame-clock time the anchor is being applied at. It is passed
    // in rather than read from frameClock so the extrapolation is a pure
    // function of (anchor, time) — which is both easier to reason about and
    // what lets tests drive it without a running render loop.
    function applyAnchorAt(a, t) {
        if (!a)
            return;

        var newBeat = a.beat !== undefined ? a.beat : 0.0;
        var newBps = a.bps !== undefined ? a.bps : 0.0;
        var predicted = root._initialised ? root.beatAt(t) : newBeat;
        var residual = predicted - newBeat;
        root._initialised = true;

        root._anchorBeat = newBeat;
        root._anchorClock = t;
        root._bps = newBps;

        if (a.snap || Math.abs(residual) > root.snapThresholdBeats) {
            // A real jump: start, seek, loop wrap. Land on it immediately —
            // sliding into a seek target would be worse than the cut.
            root._offset = 0.0;
            root._offsetSeconds = 0.0;
        } else {
            // Drift. Keep the position the viewer can currently see and walk it
            // back to truth slowly enough that the walk itself is invisible.
            root._offset = residual;
            var rate = Math.abs(newBps) * root.maxCorrectionRate;
            root._offsetSeconds = rate > 0.0
                ? Math.max(root.minCorrectionSeconds, Math.abs(residual) / rate)
                : root.minCorrectionSeconds;
        }
        root._offsetClock = t;
        root.beat = root.beatAt(t);
    }

    onAnchorChanged: {
        if (anchor && anchor.seq !== undefined && anchor.seq === root._seenSeq)
            return;
        if (anchor && anchor.seq !== undefined)
            root._seenSeq = anchor.seq;
        applyAnchorAt(anchor, frameClock.elapsedTime);
    }

    FrameAnimation {
        id: frameClock
        running: root.active
        onTriggered: root.beat = root.beatAt(elapsedTime)
    }
}
