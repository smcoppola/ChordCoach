"""
End-to-end check of the scroll pipeline: PlaybackService -> ScrollClock.

The two halves are tested separately elsewhere. This wires the real service to
the real QML clock and asserts the property that actually matters to a player
reading the music: the playhead advances smoothly, in time with the audio, and
never stalls or jumps while the transport is running.

The backend clock is stepped manually rather than left to a QTimer, so the test
is deterministic and does not depend on timer delivery under load.
"""

import pytest

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from logic.services.playback_service import PlaybackService


BPM = 120.0
BPS = BPM / 60.0


@pytest.fixture
def clock(qapp, qml_dir):
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_dir / "ScrollClock.qml")))
    if component.isError():
        pytest.fail("\n".join(e.toString() for e in component.errors()))
    obj = component.create()
    obj._engine = engine          # type: ignore[attr-defined]
    obj._component = component    # type: ignore[attr-defined]
    yield obj
    obj.deleteLater()


@pytest.fixture
def service(qapp):
    svc = PlaybackService()
    steps = [
        {"offset": float(i), "pitches": [60 + (i % 12)], "durations": [1.0],
         "hands": ["right"], "velocities": [80]}
        for i in range(64)
    ]
    svc.load(steps, tempo_map=[{"offset": 0.0, "bpm": BPM}])
    return svc


def _pump(service, clock, seconds, fps=60.0):
    """
    Advances the backend clock and samples the view once per frame.

    Returns the beat the view displayed on each frame.
    """
    frames = int(seconds * fps)
    dt = 1.0 / fps
    beats = []
    t = 0.0

    for _ in range(frames):
        t += dt
        # Advance the transport's own beat as its timer would.
        service._playback_beat += dt * BPS
        service._emit_scroll_anchor(now=t)
        clock.applyAnchorAt(service.scrollAnchor, t)
        beats.append(clock.beatAt(t))

    return beats


def test_view_tracks_the_transport(service, clock):
    """The displayed playhead must match where the audio actually is."""
    service.play()
    clock.applyAnchorAt(service.scrollAnchor, 0.0)

    beats = _pump(service, clock, seconds=4.0)

    # After 4 seconds at 120 BPM the transport is 8 beats in; the view must agree.
    assert beats[-1] == pytest.approx(service.playbackBeat, abs=0.05), (
        "the notation drifted away from the transport it is supposed to follow"
    )


def test_playhead_never_stalls_or_reverses(service, clock):
    """
    Every frame must advance by very nearly the same amount.

    This is the regression test for the original bug. The old path pushed beat
    samples at 30 Hz through a 150 ms easing Behavior that restarted on each
    one, so the per-frame delta oscillated and the music surged and stalled.
    """
    service.play()
    clock.applyAnchorAt(service.scrollAnchor, 0.0)

    beats = _pump(service, clock, seconds=5.0)
    deltas = [b - a for a, b in zip(beats, beats[1:])]

    expected = BPS / 60.0
    assert min(deltas) > 0.0, "the playhead stalled or reversed on some frame"

    worst = max(abs(d - expected) for d in deltas)
    assert worst < expected * 0.05, (
        f"per-frame advance varied by {worst / expected:.1%} of a frame step; "
        "scrolling is not running at a constant velocity"
    )


def test_seek_is_reflected_immediately(service, clock):
    """A seek is a discontinuity — the view must land on it, not slide there."""
    service.play()
    clock.applyAnchorAt(service.scrollAnchor, 0.0)
    _pump(service, clock, seconds=2.0)

    service.seek(40.0)
    clock.applyAnchorAt(service.scrollAnchor, 2.0)

    assert clock.beatAt(2.0) == pytest.approx(40.0, abs=1e-6)


def test_pause_parks_the_playhead(service, clock):
    """After pause the view must hold position rather than keep scrolling."""
    service.play()
    clock.applyAnchorAt(service.scrollAnchor, 0.0)
    _pump(service, clock, seconds=1.0)

    service.pause()
    clock.applyAnchorAt(service.scrollAnchor, 1.0)
    parked = clock.beatAt(1.0)

    for ahead in (0.5, 5.0, 30.0):
        assert clock.beatAt(1.0 + ahead) == pytest.approx(parked, abs=1e-9), (
            "the notation kept scrolling after playback was paused"
        )


def test_anchors_are_published_sparingly(service):
    """
    The anchor is a correction channel, not a position feed.

    If this starts firing per tick the QML binding cost returns and the design
    has quietly reverted to pushing samples.
    """
    service.play()
    start_seq = service.scrollAnchor["seq"]

    t = 0.0
    for _ in range(300):  # 3 seconds of 10 ms ticks
        t += 0.01
        service._playback_beat += 0.01 * BPS
        # Mirrors the policy in _on_tick: re-anchor only on a speed change or
        # once the periodic correction is due.
        if (abs(service._beats_per_second() - service._last_anchor_bps) > 1e-6
                or (t - service._last_anchor_time) >= 0.25):
            service._emit_scroll_anchor(now=t)

    emitted = service.scrollAnchor["seq"] - start_seq
    assert emitted <= 15, (
        f"{emitted} anchors in 3 seconds — the backend is streaming positions again"
    )
