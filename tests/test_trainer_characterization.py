"""
Characterization tests for ChordTrainerService's note handling.

These pin what the trainer does today with real key presses — chord matching,
holds, pentascales, progressions, self-paced songs, and the gates that keep
input out while the coach speaks — so the class can be split up without
anyone noticing at the keyboard. They describe current behaviour, not ideal
behaviour: where that behaviour is surprising, the test says so.

Exercises are applied through `apply()` below and nowhere else, so when the
way an exercise reaches the trainer changes, only that helper has to follow.
Nothing here needs a coach, a database or MIDI hardware.
"""
from unittest.mock import MagicMock

import pytest
from PySide6.QtTest import QTest

from logic.services.chord_trainer import ChordTrainerService, LessonState

C4, D4, E4, F4, G4 = 60, 62, 64, 65, 67
A4, B4, C5, D5 = 69, 71, 72, 74


# ── Test doubles and helpers ────────────────────────────────────────────────

class StubMusic21:
    def __init__(self, song):
        self.song = song

    def get_user_song_pref(self, song_id, key, default=""):
        return default

    def set_user_song_pref(self, song_id, key, value):
        pass

    def load_song_as_steps(self, piece_name):
        return self.song


class StubPlayback:
    isPlaying = False
    handFilter = "both"
    tempoScale = 1.0
    loopStartBeat = -1.0
    loopEndBeat = -1.0

    def load(self, *args, **kwargs):
        pass

    def setLoop(self, *args):
        pass

    def was_just_sent(self, pitch, window_ms=80.0):
        return False


def three_step_song():
    """Three right-hand steps: C+E, then D, then E+G."""
    pitch_sets = [[C4, E4], [D4], [E4, G4]]
    steps = []
    for i, pitches in enumerate(pitch_sets):
        n = len(pitches)
        steps.append({
            "offset": float(i), "duration": 1.0, "pitches": pitches,
            "hands": ["right"] * n, "fingers": [1] * n, "durations": [1.0] * n,
            "spellings": [None] * n, "ties": [None] * n, "beams": [None] * n,
        })
    return {
        "steps": steps, "title": "Three Steps", "composer": "Test", "key": "C major",
        "key_sharps": 0, "tempo_map": [{"offset": 0.0, "bpm": 80.0}],
        "time_signatures": [{"offset": 0.0, "numerator": 4, "denominator": 4}],
        "barlines": [], "pedal_events": [], "dynamics": [],
    }


def make_db():
    db = MagicMock()
    db.get_app_setting.side_effect = lambda key, default="": default
    return db


class Recorder:
    """Collects the trainer's outward signals."""

    def __init__(self, trainer):
        self.successes = []
        self.failures = 0
        trainer.chordSuccess.connect(lambda name, ms: self.successes.append(name))
        trainer.chordFailed.connect(self._failed)

    def _failed(self):
        self.failures += 1


def press(trainer, *pitches):
    for p in pitches:
        trainer.handle_midi_note(p, True)


def release(trainer, *pitches):
    for p in pitches:
        trainer.handle_midi_note(p, False)


def apply(trainer, exercise):
    """
    Puts `exercise` (a LessonSequencer-shaped dict) in front of the student,
    with the same normalisation (aliases, inversions) the lesson path applies.
    """
    trainer.present_exercise(dict(exercise))


@pytest.fixture
def trainer(qapp):
    t = ChordTrainerService(make_db(), None, None, StubMusic21(three_step_song()))
    t.set_playback_service(StubPlayback())
    t.rec = Recorder(t)
    yield t
    t._song.engine.stop()
    t._hold_tick_timer.stop()


def c_major(**extra):
    ex = {"exercise_type": "chord", "exercise_name": "C Major", "root_idx": 0,
          "chord_type_name": "Major", "octave": 4, "track": "technique",
          "milestone_id": ""}
    ex.update(extra)
    return ex


# ── Chords ──────────────────────────────────────────────────────────────────

def test_chord_completes_on_the_exact_pitches(trainer):
    apply(trainer, c_major())
    assert trainer.targetPitches == [C4, E4, G4]
    assert trainer.targetChord == "C Major"

    press(trainer, C4, E4)
    assert trainer.rec.successes == []
    press(trainer, G4)
    assert trainer.rec.successes == ["C Major"]


def test_chord_names_and_formula(trainer):
    apply(trainer, c_major(root_idx=9, chord_type_name="Minor"))
    assert trainer.targetChord == "A Minor"
    assert trainer.targetFormulaText == "Root + 3 + 4"
    assert trainer.targetPitches == [A4, C5, 76]


def test_chord_type_aliases_are_normalised(trainer):
    apply(trainer, c_major(root_idx=7, chord_type_name="Dom7"))
    assert trainer.targetChord == "G Dominant 7th"
    assert trainer.targetPitches == [G4, B4, D5, 77]


def test_inversion_rotates_the_voicing(trainer):
    apply(trainer, c_major(inversion=1))
    assert trainer.targetChord == "C Major (1st inv)"
    assert trainer.targetPitches == [E4, G4, C5]

    press(trainer, E4, G4, C5)
    assert trainer.rec.successes == ["C Major (1st inv)"]


def test_unknown_chord_type_is_rejected(trainer):
    assert trainer.present_exercise(c_major(chord_type_name="Sus4")) is False
    assert trainer.targetPitches == []


def test_right_notes_in_the_wrong_octave_neither_complete_nor_fail(trainer):
    apply(trainer, c_major())
    press(trainer, C4 + 12, E4 + 12, G4 + 12)
    QTest.qWait(400)
    assert trainer.rec.successes == []
    assert trainer.rec.failures == 0
    assert not trainer.mistakeActive  # pitch classes are right


def test_wrong_chord_of_the_right_size_fails_after_a_grace_period(trainer):
    apply(trainer, c_major())
    press(trainer, D4, F4, A4)
    assert trainer.rec.failures == 0  # not yet: allows for key slop
    assert trainer.mistakeActive
    QTest.qWait(400)
    assert trainer.rec.failures == 1
    name, success, _latency, wrong_notes, simultaneous = trainer.db.record_chord_attempt.call_args.args
    assert (name, success, wrong_notes, simultaneous) == ("C Major", False, 3, False)


def test_wrong_chord_of_a_different_size_never_fails(trainer):
    apply(trainer, c_major())
    press(trainer, D4, F4)
    QTest.qWait(400)
    assert trainer.rec.failures == 0


def test_wrong_notes_are_counted_against_the_attempt(trainer):
    apply(trainer, c_major())
    press(trainer, D4)
    release(trainer, D4)
    press(trainer, C4, E4, G4)
    assert trainer.rec.successes == ["C Major"]
    args = trainer.db.record_chord_attempt.call_args.args
    assert args[0] == "C Major" and args[1] is True and args[3] == 1


def test_free_practice_moves_to_a_new_chord_after_success(trainer):
    trainer.start_session()
    apply(trainer, c_major())
    press(trainer, C4, E4, G4)
    release(trainer, C4, E4, G4)
    QTest.qWait(450)
    assert trainer.isActive
    assert trainer.targetPitches  # a fresh random target
    assert trainer.targetChord


# ── Holds ───────────────────────────────────────────────────────────────────

def test_held_chord_completes_only_after_the_hold(trainer):
    apply(trainer, c_major(hold_ms=250))
    press(trainer, C4, E4, G4)
    assert trainer.rec.successes == []
    QTest.qWait(150)
    assert 0.0 < trainer.holdProgress < 1.0
    QTest.qWait(250)
    assert trainer.rec.successes == ["C Major"]


def test_letting_go_during_a_hold_resets_it(trainer):
    apply(trainer, c_major(hold_ms=400))
    press(trainer, C4, E4, G4)
    QTest.qWait(100)
    release(trainer, C4, E4, G4)
    QTest.qWait(250)  # past the 150 ms bounce allowance
    assert trainer.holdProgress == 0.0
    QTest.qWait(200)
    assert trainer.rec.successes == []


# ── Pentascales ─────────────────────────────────────────────────────────────

def pentascale(**extra):
    ex = {"exercise_type": "pentascale", "exercise_name": "C Pentascale",
          "root_idx": 0, "scale_type": "Major", "direction": "ascending",
          "octave": 4, "track": "technique", "milestone_id": ""}
    ex.update(extra)
    return ex


def test_pentascale_advances_note_by_note_and_completes(trainer):
    hits = []
    trainer.pentascaleNoteHit.connect(lambda i, fb: hits.append(i))
    apply(trainer, pentascale())
    assert trainer.pentascaleNotes == [C4, D4, E4, F4, G4]

    for p in (C4, D4, E4, F4, G4):
        press(trainer, p)
        release(trainer, p)
    assert hits == [0, 1, 2, 3, 4]
    assert trainer.rec.successes == []  # completion is deferred so the last dot can turn green
    QTest.qWait(700)
    assert trainer.rec.successes == ["Excellent Timing!"]


def test_pentascale_allows_legato(trainer):
    """
    The next note scores while the previous one is still down. Only one note
    of overlap is tolerated, though, and the index moves on the instant the
    new note scores — so the held note is then two behind and reads as a
    mistake until it is let go.
    """
    apply(trainer, pentascale())
    press(trainer, C4)
    assert not trainer.mistakeActive
    press(trainer, D4)  # C still held
    assert trainer.currentNoteIndex == 2
    assert trainer.mistakeActive
    release(trainer, C4)
    assert not trainer.mistakeActive


def test_pentascale_wrong_note_does_not_advance(trainer):
    apply(trainer, pentascale())
    press(trainer, E4)
    assert trainer.currentNoteIndex == 0
    assert trainer.mistakeActive
    release(trainer, E4)
    for p in (C4, D4, E4, F4, G4):
        press(trainer, p)
        release(trainer, p)
    QTest.qWait(700)
    assert trainer.rec.successes == ["Good Pace"]  # one wrong note


def test_descending_pentascale(trainer):
    apply(trainer, pentascale(direction="descending", scale_type="Minor"))
    assert trainer.pentascaleNotes == [G4, F4, 63, D4, C4]


# ── Progressions ────────────────────────────────────────────────────────────

def test_progression_steps_through_each_chord(trainer):
    apply(trainer, {
        "exercise_type": "progression", "exercise_name": "I-IV-V",
        "track": "technique", "milestone_id": "", "progression_steps": [
            {"root_idx": 0, "chord_type_name": "Major", "numeral": "I"},
            {"root_idx": 5, "chord_type_name": "Major", "numeral": "IV"},
            {"root_idx": 7, "chord_type_name": "Major", "numeral": "V"},
        ]})
    assert trainer.progressionNumerals == ["I", "IV", "V"]
    assert trainer.targetChord == "C Major (I)"

    press(trainer, C4, E4, G4)
    release(trainer, C4, E4, G4)
    assert trainer.currentProgressionIndex == 1
    assert trainer.targetChord == "F Major (IV)"
    assert trainer.scrollBeat == 1.0

    press(trainer, F4, A4, C5)
    release(trainer, F4, A4, C5)
    press(trainer, G4, B4, D5)
    assert trainer.rec.successes == ["C Major (I)", "F Major (IV)", "G Major (V)"]


# ── Self-paced songs ────────────────────────────────────────────────────────

def test_song_starts_self_paced_on_the_first_step(trainer):
    trainer.start_song("user::three-steps")
    assert trainer.pacingMode == "self_paced"
    assert trainer.exerciseType == "song_application"
    assert trainer.targetPitches == [C4, E4]
    assert trainer.scrollBeat == 0.0
    assert not trainer.coachNeeded


def test_song_advances_as_soon_as_each_step_is_played(trainer):
    trainer.start_song("user::three-steps")
    press(trainer, C4, E4)
    assert trainer.targetPitches == [D4]  # no key release needed
    assert trainer.scrollBeat == 1.0


def test_song_tolerates_a_note_held_over_from_the_last_step(trainer):
    """
    Holding E from the first step while playing D is not a mistake, but the
    step only completes once the held-over note is let go: completion needs
    the held keys to equal the step exactly.
    """
    trainer.start_song("user::three-steps")
    press(trainer, C4, E4)
    release(trainer, C4)
    press(trainer, D4)  # E4 still down
    assert not trainer.mistakeActive
    assert trainer._song.wrong_notes == 0
    assert trainer.targetPitches == [D4]

    release(trainer, E4)
    assert trainer.targetPitches == [E4, G4]


def test_song_counts_wrong_notes(trainer):
    trainer.start_song("user::three-steps")
    press(trainer, B4)
    assert trainer.mistakeActive
    assert trainer._song.wrong_notes == 1
    assert trainer.targetPitches == [C4, E4]


def test_song_plays_to_completion(trainer):
    trainer.start_song("user::three-steps")
    for step in ([C4, E4], [D4], [E4, G4]):
        press(trainer, *step)
        release(trainer, *step)
    assert trainer.isSongCompleted
    # Parked half a beat past the end of the last note, so every note greys out.
    assert trainer.scrollBeat == 3.5


# ── Gates: coach speech and key release ─────────────────────────────────────

def in_lesson(trainer):
    trainer._is_lesson_mode = True
    trainer._is_lesson_complete = False


def test_no_input_is_scored_while_the_coach_speaks(trainer):
    in_lesson(trainer)
    apply(trainer, c_major())
    trainer.pause_for_speech()
    assert trainer.isPausedForSpeech

    press(trainer, C4, E4, G4)
    assert trainer.rec.successes == []


def test_keys_pressed_during_speech_must_be_struck_again(trainer):
    """
    Note-ons that arrive while the coach is speaking are dropped outright, not
    held for later, so a chord already down when speech ends does not score.
    """
    in_lesson(trainer)
    apply(trainer, c_major())
    trainer.pause_for_speech()
    press(trainer, C4, E4, G4)
    trainer.resume_lesson()
    assert not trainer.isPausedForSpeech
    assert trainer.rec.successes == []

    release(trainer, C4, E4, G4)
    press(trainer, C4, E4, G4)
    assert trainer.rec.successes == ["C Major"]


def test_new_step_during_speech_with_keys_down_needs_a_full_release(trainer):
    in_lesson(trainer)
    apply(trainer, c_major())
    press(trainer, C4, E4)  # not yet complete

    trainer.pause_for_speech()
    apply(trainer, c_major(root_idx=7, exercise_name="G Major"))
    trainer.resume_lesson()
    assert trainer.targetPitches == [G4, B4, D5]

    press(trainer, G4, B4, D5)  # C and E still down
    release(trainer, C4, E4)
    assert trainer.rec.successes == []  # lock holds until every key is up

    release(trainer, G4, B4, D5)
    press(trainer, G4, B4, D5)
    assert trainer.rec.successes == ["G Major"]


def test_inactive_trainer_ignores_notes(trainer):
    assert trainer._state == LessonState.IDLE
    press(trainer, C4, E4, G4)
    assert trainer.rec.successes == []
    assert not trainer.mistakeActive
