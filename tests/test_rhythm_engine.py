"""
Unit tests for RhythmEngine — the beat-clock / hit-window scoring engine
extracted from EvaluationService in Phase 4.

The engine's clock is driven by a QTimer reading wall-clock deltas. These tests
never start the timer; they drive `_current_beat` directly and call the same
private step functions the timer would, which keeps them fast and deterministic.
"""
import pytest

from logic.services.rhythm_engine import RhythmEngine


def make_notes(spec):
    """spec: list of (pitch, start_beat, duration_beats[, hand])"""
    out = []
    for item in spec:
        pitch, start, dur = item[0], item[1], item[2]
        hand = item[3] if len(item) > 3 else "right"
        out.append({
            "pitch": pitch,
            "start_beat": float(start),
            "duration_beats": float(dur),
            "hand": hand,
        })
    return out


def seek(engine, beat):
    """Moves the playhead and runs the per-tick miss sweep, as the timer would."""
    engine._current_beat = float(beat)
    engine._check_missed_notes()


@pytest.fixture
def engine():
    e = RhythmEngine(beat_signal_interval=0.0)
    yield e
    e.stop()


# ── Hit window ──────────────────────────────────────────────────────────────

def test_hit_inside_window_scores(engine):
    engine.load(make_notes([(60, 0, 1), (62, 1, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.3)  # within +-0.35 of beat 0
    engine.handle_midi_note(60, True)

    assert engine.noteStates[0] == "hit"
    assert engine.noteStates[1] == "pending"


def test_early_hit_inside_window_scores(engine):
    engine.load(make_notes([(60, 4, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 3.7)  # 0.3 beats early
    engine.handle_midi_note(60, True)

    assert engine.noteStates[0] == "hit"


def test_note_outside_window_scores_miss_once_passed(engine):
    engine.load(make_notes([(60, 0, 1), (62, 1, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.5)  # past 0 + 0.35 -> note 0 missed
    assert engine.noteStates[0] == "miss"

    # Playing it now is too late; the note is no longer pending.
    engine.handle_midi_note(60, True)
    assert engine.noteStates[0] == "miss"


def test_wrong_pitch_inside_window_does_not_score(engine):
    engine.load(make_notes([(60, 0, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(61, True)

    assert engine.noteStates[0] == "pending"


def test_hit_window_is_in_beats_not_ms(engine):
    """The window is a beat count, so it is tempo-independent by construction."""
    assert RhythmEngine.HIT_WINDOW_BEATS == 0.35

    engine.load(make_notes([(60, 0, 1)]), tempo_bpm=40)
    engine.start(paused=True)
    seek(engine, 0.34)
    engine.handle_midi_note(60, True)
    assert engine.noteStates[0] == "hit"


# ── Chords score per-note ───────────────────────────────────────────────────

def test_chord_entries_score_independently(engine):
    # A C-major triad: three entries sharing start_beat 0.
    engine.load(make_notes([(60, 0, 1), (64, 0, 1), (67, 0, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(60, True)
    engine.handle_midi_note(67, True)

    assert engine.noteStates == ["hit", "pending", "hit"]

    seek(engine, 0.5)  # playhead passes; the untouched middle note misses
    assert engine.noteStates == ["hit", "miss", "hit"]

    accuracy, hits, misses = engine.result()
    assert (hits, misses) == (2, 1)
    assert accuracy == pytest.approx(2 / 3)


# ── Count-in ────────────────────────────────────────────────────────────────

def test_count_in_emits_no_misses_before_beat_zero(engine):
    engine.load(make_notes([(60, 0, 1), (62, 1, 1)]), tempo_bpm=100, count_in_beats=4)
    engine.start(paused=True)

    assert engine.currentBeat == -4.0

    for b in (-4.0, -3.0, -2.0, -1.0, -0.5, -0.01):
        seek(engine, b)
        assert engine.noteStates == ["pending", "pending"], f"miss marked at beat {b}"


def test_count_in_metronome_tick_numbering(engine):
    ticks = []
    engine.metronomeTick.connect(lambda n, accent: ticks.append((n, accent)))
    engine.load(make_notes([(60, 0, 1)]), tempo_bpm=100, count_in_beats=4)
    engine.start(paused=True)

    # Walk the count-in the way _advance_beat does, without the timer.
    for b in (-4.0, -3.0, -2.0, -1.0, 0.0):
        engine._current_beat = b
        if engine._next_metronome_beat <= -1 and b >= engine._next_metronome_beat:
            n = engine._next_metronome_beat + engine._count_in_beats + 1
            engine.metronomeTick.emit(n, n == 1)
            engine._next_metronome_beat += 1

    assert ticks == [(1, True), (2, False), (3, False), (4, False)]


# ── Loops ───────────────────────────────────────────────────────────────────

def test_loop_wrap_resets_in_loop_states_and_accumulates(engine):
    # Notes at beats 0..3; loop over [1, 3).
    engine.load(make_notes([(60, 0, 1), (62, 1, 1), (64, 2, 1), (65, 3, 1)]), tempo_bpm=100)
    engine.set_loop(1.0, 3.0)
    engine.start(paused=True)

    assert engine.hasLoop

    # Pass 1: hit the note at beat 1, ignore the one at beat 2.
    seek(engine, 1.0)
    engine.handle_midi_note(62, True)
    assert engine.noteStates[1] == "hit"

    seek(engine, 2.5)
    assert engine.noteStates[2] == "miss"

    engine._current_beat = 3.0
    engine._wrap_loop()

    # In-loop notes are pending again for the next pass; the playhead is back at A.
    assert engine.noteStates[1] == "pending"
    assert engine.noteStates[2] == "pending"
    assert engine.currentBeat == 1.0
    assert engine.loopPasses == 1

    # Pass 1 banked 1 hit of 2 in-loop notes.
    assert engine._acc_hits == 1
    assert engine._acc_total == 2

    # Pass 2: hit both.
    seek(engine, 1.0)
    engine.handle_midi_note(62, True)
    seek(engine, 2.0)
    engine.handle_midi_note(64, True)
    engine._current_beat = 3.0
    engine._wrap_loop()

    assert engine.loopPasses == 2
    assert engine._acc_hits == 3
    assert engine._acc_total == 4
    assert engine.accuracy == pytest.approx(0.75)


def test_notes_outside_the_loop_are_not_scored_at_all(engine):
    """A loop-only run must not be penalised for the piece it never reaches."""
    engine.load(make_notes([(60, 0, 1), (62, 1, 1), (65, 3, 1)]), tempo_bpm=100)
    engine.set_loop(1.0, 3.0)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(60, True)
    assert engine.noteStates[0] == "pending"  # outside the loop: not scoreable

    seek(engine, 2.9)  # well past beat 0 and beat 1
    assert engine.noteStates[0] == "pending"  # and never marked missed either
    assert engine.noteStates[1] == "miss"
    assert engine.noteStates[2] == "pending"  # after the loop

    engine._current_beat = 3.0
    engine._wrap_loop()
    assert engine._acc_total == 1  # only the note at beat 1 counted

    accuracy, hits, misses = engine.result()
    assert (hits, misses) == (0, 1)
    assert accuracy == pytest.approx(0.0)


# ── Accuracy & finish ───────────────────────────────────────────────────────

def test_accuracy_math_and_finished_signal(engine):
    results = []
    engine.finished.connect(lambda a, h, m: results.append((a, h, m)))

    engine.load(make_notes([(60, 0, 1), (62, 1, 1), (64, 2, 1), (65, 3, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(60, True)
    seek(engine, 1.0)
    engine.handle_midi_note(62, True)
    seek(engine, 2.0)
    engine.handle_midi_note(64, True)
    seek(engine, 4.0)  # note at beat 3 goes unplayed

    assert engine.accuracy == pytest.approx(0.75)

    engine._finish()
    assert results == [(pytest.approx(0.75), 3, 1)]
    assert not engine.isRunning


def test_live_accuracy_ignores_pending_notes(engine):
    engine.load(make_notes([(60, 0, 1), (62, 8, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(60, True)

    # One resolved note (a hit) and one far-future pending note -> 100%, not 50%.
    assert engine.accuracy == pytest.approx(1.0)


def test_empty_note_list_reports_zero_accuracy(engine):
    engine.load([], tempo_bpm=100)
    engine.start(paused=True)
    assert engine.result() == (0.0, 0, 0)


# ── Pause / resume / reset ──────────────────────────────────────────────────

def test_pause_resume_preserves_beat_and_states(engine):
    engine.load(make_notes([(60, 0, 1), (62, 1, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(60, True)

    engine.pause()
    assert engine.paused
    beat = engine.currentBeat
    states = list(engine.noteStates)

    engine.resume()
    assert not engine.paused
    assert engine.currentBeat == beat
    assert engine.noteStates == states
    engine.pause()


def test_start_resets_states_and_stats(engine):
    engine.load(make_notes([(60, 0, 1), (62, 1, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 5.0)
    assert engine.noteStates == ["miss", "miss"]

    engine.start(paused=True)
    assert engine.noteStates == ["pending", "pending"]
    assert engine.currentBeat == -4.0
    assert engine._acc_hits == 0
    assert engine._acc_total == 0
    assert engine.loopPasses == 0


def test_miss_sweep_walks_a_cursor_instead_of_rescanning(engine):
    """The sweep runs 100x/sec, so it must be amortised O(1), not O(notes)."""
    notes = make_notes([(60 + (i % 12), i * 0.5, 0.5) for i in range(400)])
    engine.load(notes, tempo_bpm=100)
    engine.start(paused=True)

    assert engine._miss_cursor == 0
    seek(engine, 10.0)
    # Only the notes actually passed have been visited.
    assert engine._miss_cursor == 20
    seek(engine, 10.1)  # note 20 is still inside its window: cursor holds
    assert engine._miss_cursor == 20
    seek(engine, 10.4)  # now past it, and only it
    assert engine._miss_cursor == 21


def test_loop_wrap_rewinds_the_miss_cursor(engine):
    engine.load(make_notes([(60, 0, 1), (62, 1, 1), (64, 2, 1), (65, 3, 1)]), tempo_bpm=100)
    engine.set_loop(1.0, 3.0)
    engine.start(paused=True)

    seek(engine, 2.9)
    assert engine._miss_cursor > 1

    engine._current_beat = 3.0
    engine._wrap_loop()

    # Back to the first note at or after the loop start.
    assert engine._miss_cursor == 1

    # And the second pass can still mark those notes missed again.
    seek(engine, 2.9)
    assert engine.noteStates[1] == "miss"
    assert engine.noteStates[2] == "miss"


def test_note_off_does_not_score(engine):
    engine.load(make_notes([(60, 0, 1)]), tempo_bpm=100)
    engine.start(paused=True)

    seek(engine, 0.0)
    engine.handle_midi_note(60, False)
    assert engine.noteStates[0] == "pending"


def test_engine_ignores_input_when_not_running(engine):
    engine.load(make_notes([(60, 0, 1)]), tempo_bpm=100)
    engine._current_beat = 0.0

    engine.handle_midi_note(60, True)
    assert engine.noteStates[0] == "pending"
