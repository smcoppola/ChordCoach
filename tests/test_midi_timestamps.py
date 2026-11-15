"""
MIDI events carry the time the key was pressed, not the time Python got to them.

The C++ layer stamps each message on its input thread; MidiHardwareService turns
that into a `time.perf_counter()` value and everything that scores timing
(RhythmEngine, MetronomeService, the trainer's latency) reads it.
"""
import time
from unittest.mock import MagicMock

import pytest

from hardware.midi_hardware_service import MidiHardwareService
from logic.services import metronome_service, rhythm_engine
from logic.services.metronome_service import MetronomeService
from logic.services.rhythm_engine import RhythmEngine


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ── Hardware service: C++ stamp → perf_counter ──────────────────────────────

class FakeHw:
    """Stands in for chordcoach_hw: its own clock, unrelated to perf_counter."""

    def __init__(self, now):
        self._now = now

    def now(self):
        return self._now


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    import hardware.midi_hardware_service as mod
    monkeypatch.setattr(mod.time, "perf_counter", c)
    return c


def collect(svc):
    notes, timed, pedal = [], [], []
    svc.midiNoteReceived.connect(lambda p, on: notes.append((p, on)))
    svc.midiNoteTimed.connect(lambda p, on, t: timed.append((p, on, t)))
    svc.sustainPedalTimed.connect(lambda down, t: pedal.append((down, t)))
    return notes, timed, pedal


def test_a_stamped_note_is_timed_by_its_age(qapp, clock):
    svc = MidiHardwareService(FakeHw(now=50.250), None)
    notes, timed, _ = collect(svc)

    # Stamped 30 ms before the callback got the GIL.
    svc._on_raw_midi_data(0.0, [0x90, 60, 100], 50.220)

    assert notes == [(60, True)]
    assert timed == [(60, True, pytest.approx(1000.0 - 0.030))]


def test_note_off_and_zero_velocity_are_timed_too(qapp, clock):
    svc = MidiHardwareService(FakeHw(now=10.0), None)
    _, timed, _ = collect(svc)

    svc._on_raw_midi_data(0.0, [0x80, 60, 0], 9.990)
    svc._on_raw_midi_data(0.0, [0x90, 62, 0], 9.995)

    assert [(p, on) for p, on, _ in timed] == [(60, False), (62, False)]
    assert timed[0][2] == pytest.approx(1000.0 - 0.010)
    assert timed[1][2] == pytest.approx(1000.0 - 0.005)


def test_the_pedal_is_timed(qapp, clock):
    svc = MidiHardwareService(FakeHw(now=10.0), None)
    _, _, pedal = collect(svc)

    svc._on_raw_midi_data(0.0, [0xB0, 64, 127], 9.980)

    assert pedal == [(True, pytest.approx(1000.0 - 0.020))]


def test_without_a_stamp_the_callback_time_is_used(qapp, clock):
    """An extension built before timestamps calls back with two arguments."""
    svc = MidiHardwareService(MagicMock(spec=[]), None)
    _, timed, _ = collect(svc)

    svc._on_raw_midi_data(0.0, [0x90, 60, 100])

    assert timed == [(60, True, pytest.approx(1000.0))]


@pytest.mark.parametrize("stamp", [10.5, -5.0])
def test_an_impossible_age_is_not_trusted(qapp, clock, stamp):
    """A stamp from the future, or absurdly old, falls back to the callback time."""
    svc = MidiHardwareService(FakeHw(now=10.0), None)
    _, timed, _ = collect(svc)

    svc._on_raw_midi_data(0.0, [0x90, 60, 100], stamp)

    assert timed == [(60, True, pytest.approx(1000.0))]


# ── RhythmEngine: score at the event's beat ─────────────────────────────────

def notes_of(spec):
    return [{"pitch": p, "start_beat": float(s), "duration_beats": float(d), "hand": "right"}
            for p, s, d in spec]


@pytest.fixture
def engine(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(rhythm_engine.time, "perf_counter", c)
    e = RhythmEngine(beat_signal_interval=0.0)
    e.clock = c
    yield e
    e.stop()


def run_to(engine, beat):
    """Starts the real clock and steps it to `beat` in 10 ms ticks (120 BPM)."""
    engine.start()
    engine._current_beat = 0.0
    engine._last_tick_time = engine.clock.t
    while engine._current_beat < beat - 1e-9:
        engine.clock.t += 0.010
        engine._advance_beat()


def test_a_note_delivered_late_scores_where_it_was_played(engine):
    engine.load(notes_of([(60, 2, 1), (62, 8, 1)]), tempo_bpm=120)
    pressed_at = None
    engine.start()
    engine._current_beat = 0.0
    engine._last_tick_time = engine.clock.t
    # Play up to beat 2.1, remember the moment, then let the main thread
    # "stall": the clock runs on to beat 3 before the note is delivered.
    while engine._current_beat < 3.0 - 1e-9:
        engine.clock.t += 0.010
        engine._advance_beat()
        if pressed_at is None and engine._current_beat >= 2.1:
            pressed_at = engine.clock.t

    assert engine.noteStates[0] == "miss"  # the sweep has already passed it

    engine.handle_midi_note(60, True, pressed_at)

    assert engine.noteStates[0] == "hit"
    assert engine.result()[1] == 1


def test_a_note_played_too_late_stays_missed_however_it_is_stamped(engine):
    engine.load(notes_of([(60, 2, 1), (62, 8, 1)]), tempo_bpm=120)
    run_to(engine, 3.0)
    assert engine.noteStates[0] == "miss"

    engine.handle_midi_note(60, True, engine.clock.t - 0.050)  # beat 2.9

    assert engine.noteStates[0] == "miss"


def test_the_event_time_decides_between_two_notes(engine):
    """Played at beat 1.0, delivered at 1.5: without the stamp it would be
    out of the first note's window."""
    engine.load(notes_of([(60, 1, 0.5), (62, 8, 1)]), tempo_bpm=120)
    run_to(engine, 1.3)
    played = engine.clock.t - 0.150  # 0.3 beats ago at 120 BPM
    run_extra = 0.2
    target = engine._current_beat + run_extra
    while engine._current_beat < target - 1e-9:
        engine.clock.t += 0.010
        engine._advance_beat()

    engine.handle_midi_note(60, True, played)

    assert engine.noteStates[0] == "hit"


def test_without_an_event_time_the_playhead_is_used(engine):
    engine.load(notes_of([(60, 2, 1), (62, 8, 1)]), tempo_bpm=120)
    run_to(engine, 2.2)

    engine.handle_midi_note(60, True)

    assert engine.noteStates[0] == "hit"


def test_a_paused_engine_ignores_the_event_time(engine):
    """While paused the playhead is not moving, so there is nothing to rewind."""
    engine.load(notes_of([(60, 0, 1), (62, 8, 1)]), tempo_bpm=120)
    engine.start(paused=True)
    engine._current_beat = 0.2

    engine.handle_midi_note(60, True, engine.clock.t - 5.0)

    assert engine.noteStates[0] == "hit"


# ── Metronome: offset at the event time ─────────────────────────────────────

def test_the_metronome_offset_is_measured_at_the_event(qapp, monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(metronome_service.time, "perf_counter", c)
    m = MetronomeService()
    m.start(120, 4)  # beat 0 lands 2 s from now
    try:
        c.t += 2.0 + 0.5 + 0.200  # delivered 200 ms after beat 1
        assert m.get_timing_offset_ms(1) == pytest.approx(200.0)
        # ...but it was played 20 ms early.
        assert m.get_timing_offset_ms(1, c.t - 0.220) == pytest.approx(-20.0)
    finally:
        m.stop()


# ── Trainer: latency from the event time ────────────────────────────────────

@pytest.fixture
def trainer(qapp):
    from logic.services.chord_trainer import ChordTrainerService
    db = MagicMock()
    db.get_app_setting.side_effect = lambda k, d="": d
    t = ChordTrainerService(db, None, None, MagicMock())
    yield t
    t.stop_session()


C_MAJOR = {"exercise_type": "chord", "exercise_name": "C Major",
           "root_idx": 0, "chord_type": "Major"}


def test_the_trainer_clock_is_the_event_time_while_handling_a_note(trainer):
    trainer.present_exercise(dict(C_MAJOR))
    seen = []
    trainer._exercise.on_note_on = lambda pitch: seen.append(trainer._now())
    stamp = time.perf_counter() - 0.5

    trainer.handle_midi_note(60, True, stamp)

    assert seen == [stamp]
    # Outside an event it is simply now.
    assert trainer._now() == pytest.approx(time.perf_counter(), abs=0.05)


def test_the_hold_starts_when_the_last_key_went_down(trainer):
    trainer.present_exercise(dict(C_MAJOR, hold_ms=2000))
    base = time.perf_counter()
    trainer.handle_midi_note(60, True, base)
    trainer.handle_midi_note(64, True, base + 0.010)
    trainer.handle_midi_note(67, True, base + 0.020)

    assert trainer._is_holding
    assert trainer._hold_start_time == pytest.approx((base + 0.020) * 1000.0)
    assert trainer._first_note_time == pytest.approx(base * 1000.0)
    assert trainer._is_simultaneous


def test_latency_is_measured_to_the_key_press_not_its_delivery(trainer):
    trainer.present_exercise(dict(C_MAJOR))
    trainer._prompt_time = time.perf_counter() - 3.0  # shown three seconds ago
    played = trainer._prompt_time + 1.0               # answered after one

    for p in (60, 64, 67):
        trainer.handle_midi_note(p, True, played)

    latency = trainer.db.record_chord_attempt.call_args[0][2]
    assert latency == pytest.approx(1000.0, abs=1.0)


def test_a_pedal_event_is_timed_by_its_stamp(trainer):
    stamp = time.perf_counter() - 0.250
    trainer.handle_pedal_event(True, stamp)
    assert trainer._pedal_down_time == pytest.approx(stamp * 1000.0)
