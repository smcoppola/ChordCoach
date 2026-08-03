"""
ScrollClock is the component that makes scrolling smooth, so it gets tested.

It extrapolates the playhead from an anchor on the display's frame clock rather
than consuming beat samples from the backend. The properties that matter:

  * between anchors, velocity is exactly constant (this is what "smooth" means)
  * a drift correction is absorbed gradually and never overshoots
  * a real discontinuity — start, seek, loop wrap — lands immediately

These are checked by driving beatAt() directly with an explicit time, which is
what the frame clock supplies in production.
"""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

BPM_100 = 100.0 / 60.0  # beats per second


@pytest.fixture
def clock(qapp, qml_dir):
    """A live ScrollClock instance, loaded the same way the app loads it."""
    engine = QQmlEngine()
    engine.addImportPath(str(qml_dir.parent))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_dir / "ScrollClock.qml")))

    if component.isError():
        pytest.fail("ScrollClock.qml failed to load:\n" +
                    "\n".join(e.toString() for e in component.errors()))

    obj = component.create()
    assert obj is not None, "ScrollClock.qml produced no object"
    # Keep the engine and component alive for the lifetime of the object.
    obj._engine = engine  # type: ignore[attr-defined]
    obj._component = component  # type: ignore[attr-defined]
    yield obj
    obj.deleteLater()


def _anchor(beat, bps, snap=False, active=True):
    return {"beat": beat, "bps": bps, "snap": snap, "active": active}


def _apply(clock, anchor, at):
    """Applies an anchor at an explicit frame-clock time, as the app does per frame."""
    clock.applyAnchorAt(anchor, at)


def test_extrapolates_at_the_anchor_rate(clock):
    """The whole point: position is a linear function of time between anchors."""
    _apply(clock, _anchor(4.0, BPM_100, snap=True), 0.0)
    t0 = 0.0

    for elapsed in (0.0, 0.25, 1.0, 3.0):
        got = clock.beatAt(t0 + elapsed)
        assert got == pytest.approx(4.0 + elapsed * BPM_100, abs=1e-9)


def test_velocity_is_constant_between_anchors(clock):
    """
    Equal time steps must produce equal position steps.

    This is the property the old Behavior-based path violated: a retargeted
    easing curve restarts, so its velocity oscillated and the music visibly
    surged and stalled. Any reintroduction of easing here fails this test.
    """
    _apply(clock, _anchor(0.0, BPM_100, snap=True), 0.0)
    t0 = 0.0

    dt = 1.0 / 60.0
    positions = [clock.beatAt(t0 + i * dt) for i in range(60)]
    deltas = [b - a for a, b in zip(positions, positions[1:])]

    expected = BPM_100 * dt
    for d in deltas:
        assert d == pytest.approx(expected, rel=1e-9)


def test_seek_lands_immediately(clock):
    """A snap anchor is a discontinuity; sliding into it would be worse."""
    _apply(clock, _anchor(0.0, BPM_100, snap=True), 0.0)
    clock.beatAt(5.0)

    _apply(clock, _anchor(64.0, BPM_100, snap=True), 5.0)
    assert clock.beatAt(5.0) == pytest.approx(64.0, abs=1e-9)


def test_drift_correction_is_absorbed_not_jumped(clock):
    """
    A small correction must not teleport the music.

    The view keeps showing where it already was and walks back to truth, so the
    instant the anchor lands the position is still (nearly) the old one.
    """
    _apply(clock, _anchor(0.0, BPM_100, snap=True), 0.0)
    t0 = 0.0
    predicted = clock.beatAt(t0 + 2.0)

    # Backend says we are 0.1 beats behind where the view thinks it is.
    corrected = predicted - 0.1
    _apply(clock, _anchor(corrected, BPM_100), 2.0)
    t1 = 2.0

    at_anchor = clock.beatAt(t1)
    assert at_anchor == pytest.approx(predicted, abs=1e-6), (
        "a drift correction jumped the playhead instead of absorbing it"
    )


def test_drift_correction_converges_and_holds(clock):
    """After the correction window the clock tracks the corrected anchor exactly."""
    _apply(clock, _anchor(0.0, BPM_100, snap=True), 0.0)
    t0 = 0.0
    predicted = clock.beatAt(t0 + 2.0)

    corrected = predicted - 0.1
    _apply(clock, _anchor(corrected, BPM_100), 2.0)
    t1 = 2.0

    # Well past any correction window.
    for ahead in (5.0, 10.0):
        assert clock.beatAt(t1 + ahead) == pytest.approx(
            corrected + ahead * BPM_100, abs=1e-9
        )


def test_correction_never_reverses_the_music(clock):
    """
    While absorbing drift the playhead must still move forward.

    The correction rate is capped as a fraction of tempo precisely so that
    catching up never stalls or rewinds the notation, which would be far more
    disruptive to read than the drift itself.
    """
    _apply(clock, _anchor(0.0, BPM_100, snap=True), 0.0)
    t0 = 0.0
    predicted = clock.beatAt(t0 + 2.0)

    # A residual just under the snap threshold — the worst case it must absorb.
    _apply(clock, _anchor(predicted - 0.7, BPM_100), 2.0)
    t1 = 2.0

    dt = 1.0 / 60.0
    positions = [clock.beatAt(t1 + i * dt) for i in range(240)]
    for a, b in zip(positions, positions[1:]):
        assert b >= a - 1e-9, "the playhead moved backwards while correcting drift"


def test_large_residual_snaps_rather_than_crawling(clock):
    """Past the threshold an anchor is a jump, not drift, even without the flag."""
    _apply(clock, _anchor(0.0, BPM_100, snap=True), 0.0)
    t0 = 0.0
    clock.beatAt(t0 + 2.0)

    _apply(clock, _anchor(100.0, BPM_100), 2.0)
    assert clock.beatAt(2.0) == pytest.approx(100.0, abs=1e-9)


def test_stopped_transport_holds_position(clock):
    """bps 0 parks the playhead instead of letting it run on."""
    _apply(clock, _anchor(12.5, 0.0, snap=True, active=False), 0.0)
    t0 = 0.0

    for ahead in (0.5, 5.0, 60.0):
        assert clock.beatAt(t0 + ahead) == pytest.approx(12.5, abs=1e-9)
