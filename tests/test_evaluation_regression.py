"""
Regression tests for EvaluationService after Phase 4 moved its beat clock and
hit-window scoring into RhythmEngine.

The onboarding flow must be behaviour-identical. These tests:
  1. Pin the public QML contract (signals / properties / slots) that
     OnboardingOverlay.qml binds to.
  2. Drive the refactored service through real level-1 data from
     sequences.json with a simulated clock and injected note events, and
     compare the outcome against a standalone re-implementation of the
     pre-refactor scoring logic computed from the same file.
"""
import json
from pathlib import Path

import pytest

from logic.services import rhythm_engine
from logic.services.evaluation_service import EvaluationService

REPO_ROOT = Path(__file__).resolve().parents[1]
SEQUENCES_PATH = REPO_ROOT / "src" / "resources" / "sequences.json"

# The pre-refactor constants, restated here so the tests fail if they drift.
HIT_WINDOW_BEATS = 0.35
ADVANCE_THRESHOLD = 0.70
FAIL_THRESHOLD = 0.60
COUNT_IN_BEATS = 4


# ── Helpers ─────────────────────────────────────────────────────────────────

class FakeClock:
    """Monotonic stand-in for time.perf_counter, advanced by the test."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeDB:
    """EvaluationService only stores the handle; nothing here is called."""
    pass


def load_sequences():
    if not SEQUENCES_PATH.exists():
        pytest.skip(f"{SEQUENCES_PATH} not present")
    with open(SEQUENCES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def reference_score(notes, events):
    """
    Standalone re-implementation of EvaluationService's ORIGINAL scoring, as it
    stood before the RhythmEngine extraction:

      - a tick sweep marks any pending note whose start_beat + window the
        playhead has passed as "miss"
      - a note-on scores the FIRST pending note of that pitch within
        abs(beat - start_beat) <= window
      - level accuracy is hits / total notes

    `events` is a list of (beat, pitch) note-ons in beat order.
    """
    states = ["pending"] * len(notes)

    def sweep(beat):
        for i, n in enumerate(notes):
            if states[i] == "pending" and beat > n["start_beat"] + HIT_WINDOW_BEATS:
                states[i] = "miss"

    for beat, pitch in sorted(events, key=lambda e: e[0]):
        sweep(beat)
        for i, n in enumerate(notes):
            if states[i] != "pending":
                continue
            if n["pitch"] != pitch:
                continue
            if abs(beat - n["start_beat"]) <= HIT_WINDOW_BEATS:
                states[i] = "hit"
                break

    # End of the level: the playhead has run past every note.
    for i in range(len(notes)):
        if states[i] == "pending":
            states[i] = "miss"

    hits = states.count("hit")
    total = len(states)
    return states, hits, (hits / total if total else 0.0)


def run_level(service, clock, events, max_beats):
    """
    Runs the service's real clock loop by hand: 10 ms steps through
    RhythmEngine._advance_beat, injecting each scripted note-on the first time
    the playhead reaches its beat. Returns the metronome ticks seen.
    """
    engine = service._engine
    engine._last_tick_time = clock.t

    pending = sorted(events, key=lambda e: e[0])
    idx = 0
    start_level = service.currentLevel

    while engine.isRunning and engine.currentBeat < max_beats:
        clock.advance(0.010)
        engine._advance_beat()

        while idx < len(pending) and engine.currentBeat >= pending[idx][0]:
            beat, pitch = pending[idx]
            service.handle_midi_note(pitch, True)
            service.handle_midi_note(pitch, False)
            idx += 1

        # Stop as soon as the level ladder moved on; the next level restarts
        # the engine and would otherwise keep this loop running.
        if service.currentLevel != start_level:
            break


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    """QTimer.isActive() needs a QCoreApplication; no event loop is ever run."""
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def service(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(rhythm_engine.time, "perf_counter", clock)
    svc = EvaluationService(FakeDB(), REPO_ROOT)
    svc.clock = clock  # convenience handle for tests
    # Capture each level's result at the moment it is scored: _start_level
    # resets `accuracy` to 0 when the ladder advances, exactly as it always has.
    svc.level_results = []
    svc._engine.finished.connect(
        lambda a, h, m: svc.level_results.append((a, h, m)))
    yield svc
    svc._engine.stop()


# ── 1. Public QML contract ──────────────────────────────────────────────────

def test_qml_signal_property_and_slot_surface_is_unchanged():
    for name in ("sequenceChanged", "beatChanged", "levelChanged",
                 "evaluationFinished", "metronomeTick", "noteStateChanged",
                 "pausedChanged"):
        assert hasattr(EvaluationService, name), f"lost signal {name}"

    for name in ("isRunning", "currentBeat", "currentLevel", "assessedLevel",
                 "accuracy", "tempo", "sequenceTitle", "sequenceNotes",
                 "noteStates", "paused"):
        assert hasattr(EvaluationService, name), f"lost property {name}"

    for name in ("startEvaluation", "stopEvaluation", "togglePause",
                 "restartLevel", "resume", "handle_midi_note"):
        assert hasattr(EvaluationService, name), f"lost slot/method {name}"


def test_sequences_json_still_loads_with_fingerings(service):
    assert len(service._sequences) > 0
    for seq in service._sequences:
        for note in seq.get("notes", []):
            assert "finger" in note
            assert 1 <= note["finger"] <= 5


def test_thresholds_preserved(service):
    assert service._advance_threshold == ADVANCE_THRESHOLD
    assert service._fail_threshold == FAIL_THRESHOLD


# ── 2. Scripted level-1 runs vs. the pre-refactor reference ─────────────────

def script_for(notes, play_count):
    """Note-ons dead on the beat for the first `play_count` notes."""
    return [(n["start_beat"], n["pitch"]) for n in notes[:play_count]]


def level_end_beat(notes):
    last = notes[-1]
    return last["start_beat"] + last["duration_beats"] + 3.0


def test_level_one_perfect_run_matches_reference_and_advances(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]
    events = script_for(notes, len(notes))

    _states, ref_hits, ref_accuracy = reference_score(notes, events)
    assert ref_accuracy == pytest.approx(1.0)

    service.startEvaluation(paused=True)
    assert service.currentLevel == 1
    assert service.currentBeat == -float(COUNT_IN_BEATS)

    run_level(service, service.clock, events, level_end_beat(notes))

    accuracy, hits, _misses = service.level_results[0]
    assert accuracy == pytest.approx(ref_accuracy)
    assert hits == ref_hits
    # >= 0.70 passes: the level is banked and the ladder moves up.
    assert service.assessedLevel == 1
    assert service.currentLevel == 2


def test_level_one_borderline_run_matches_reference_and_stops(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]
    total = len(notes)

    # Aim for accuracy in [0.60, 0.70): counts as a pass but ends the ladder.
    play_count = next(
        (k for k in range(total + 1) if FAIL_THRESHOLD <= k / total < ADVANCE_THRESHOLD),
        None,
    )
    if play_count is None:
        pytest.skip("level 1 note count cannot land in the borderline band")

    events = script_for(notes, play_count)
    _states, ref_hits, ref_accuracy = reference_score(notes, events)

    finished = []
    service.evaluationFinished.connect(lambda: finished.append(True))

    service.startEvaluation(paused=True)
    run_level(service, service.clock, events, level_end_beat(notes))

    assert service.accuracy == pytest.approx(ref_accuracy)
    assert service._engine.result()[1] == ref_hits
    assert service.assessedLevel == 1
    assert service.currentLevel == 1
    assert not service.isRunning
    assert finished == [True]


def test_level_one_failed_run_matches_reference_and_assesses_zero(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]

    _states, ref_hits, ref_accuracy = reference_score(notes, [])
    assert ref_hits == 0
    assert ref_accuracy == pytest.approx(0.0)

    finished = []
    service.evaluationFinished.connect(lambda: finished.append(True))

    service.startEvaluation(paused=True)
    run_level(service, service.clock, [], level_end_beat(notes))

    assert service.accuracy == pytest.approx(0.0)
    assert service.assessedLevel == 0
    assert not service.isRunning
    assert finished == [True]


def test_late_notes_outside_the_window_match_reference(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]

    # Every note played half a beat late — outside the +-0.35 beat window.
    events = [(n["start_beat"] + 0.5, n["pitch"]) for n in notes]
    ref_states, ref_hits, ref_accuracy = reference_score(notes, events)
    assert ref_accuracy < FAIL_THRESHOLD  # sloppy timing must not pass

    service.startEvaluation(paused=True)
    run_level(service, service.clock, events, level_end_beat(notes))

    accuracy, hits, _misses = service.level_results[0]
    assert accuracy == pytest.approx(ref_accuracy)
    assert hits == ref_hits
    assert list(service.noteStates) == ref_states


def test_per_note_states_match_reference_exactly(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]

    # Play every other note, on the beat.
    events = [(n["start_beat"], n["pitch"]) for i, n in enumerate(notes) if i % 2 == 0]
    ref_states, _ref_hits, _ref_accuracy = reference_score(notes, events)

    service.startEvaluation(paused=True)
    run_level(service, service.clock, events, level_end_beat(notes))

    assert list(service.noteStates) == ref_states


# ── 3. Count-in and transport ───────────────────────────────────────────────

def test_count_in_emits_four_metronome_ticks_before_beat_zero(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]

    ticks = []
    service.metronomeTick.connect(lambda n: ticks.append((n, service.currentBeat)))

    service.startEvaluation(paused=True)
    run_level(service, service.clock, [], 0.0)

    assert [n for n, _b in ticks] == [1, 2, 3, 4]
    for _n, beat in ticks:
        assert beat < 0.0
    # No note may be scored during the count-in.
    assert all(s == "pending" for s in service.noteStates)


def test_toggle_pause_and_resume_track_paused_property(service):
    service.startEvaluation(paused=False)
    assert service.isRunning
    assert not service.paused

    service.togglePause()
    assert service.paused

    service.resume()
    assert not service.paused

    service.togglePause()
    assert service.paused


def test_restart_level_rewinds_to_the_count_in(service):
    sequences = load_sequences()
    notes = sequences[0]["notes"]

    service.startEvaluation(paused=True)
    run_level(service, service.clock, script_for(notes, 1), 1.0)
    assert service.currentBeat > -float(COUNT_IN_BEATS)

    service.restartLevel()
    assert service.currentLevel == 1
    assert service.currentBeat == -float(COUNT_IN_BEATS)
    assert all(s == "pending" for s in service.noteStates)
    service._engine.stop()


def test_stop_evaluation_clears_sequence_and_states(service):
    service.startEvaluation(paused=True)
    assert len(service.sequenceNotes) > 0

    service.stopEvaluation()
    assert not service.isRunning
    assert not service.paused
    assert service.sequenceNotes == []
    assert list(service.noteStates) == []


def test_input_is_ignored_when_not_running(service):
    service.startEvaluation(paused=True)
    service.stopEvaluation()
    service.handle_midi_note(60, True)  # must not raise or score
    assert list(service.noteStates) == []
