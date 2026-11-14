"""
The two scripted lessons: the Circle of Fifths tutorial and the Dominant
Motion (V→I) drill. Both run without a coach (no narration, nothing waits)
and with one (input waits for the narration).
"""
import time
from unittest.mock import MagicMock

import pytest
from PySide6.QtTest import QTest

from logic.services.chord_trainer import ChordTrainerService

C, D, E, F, G, A, B = 60, 62, 64, 65, 67, 69, 71


def wait_for(predicate, timeout_ms=2000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(20)
    return predicate()


@pytest.fixture
def trainer(qapp):
    db = MagicMock()
    db.get_dominant_motion_play_count.return_value = 1
    db.get_curriculum_state.return_value = []
    db.get_app_setting.side_effect = lambda k, d="": d
    t = ChordTrainerService(db, None, None, MagicMock())
    t.midi_out = []
    t.midiOutRequested.connect(t.midi_out.append)
    t.visuals = []
    t.theoryVisualDirect.connect(t.visuals.append)
    t.prompts = []
    t.speakInstruction.connect(t.prompts.append)
    t.speakBrief.connect(t.prompts.append)
    t.failures = []
    t.chordFailed.connect(lambda: t.failures.append(1))
    yield t
    t.stop_session()


def chord(trainer, *pitches):
    for p in pitches:
        trainer.handle_midi_note(p, True)
    for p in pitches:
        trainer.handle_midi_note(p, False)


# ── Dominant Motion ─────────────────────────────────────────────────────────

def test_dominant_motion_starts_on_g_to_c(trainer):
    trainer.start_single_drill("theory", "dominant_motion")

    assert trainer.isCircleOfFifthsMode and trainer.isActive
    assert trainer.exerciseName == "Resolve G → C"
    assert trainer.targetPitches == [C, E, G]
    assert (trainer.lessonProgress, trainer.lessonTotal) == (1, 6)
    assert trainer.midi_out[-1] == [G, B, 74]  # the V chord is played for the student
    assert trainer.visuals[-1]["highlight_key"] == "G"
    assert trainer.visuals[-1]["arrows"] == [{"from": "G", "to": "C", "color": "#4CAF50"}]


def test_resolving_moves_to_the_next_pair_after_release(trainer):
    trainer.start_single_drill("theory", "dominant_motion")
    chord(trainer, C, E, G)
    assert wait_for(lambda: trainer.exerciseName == "Resolve D → G")
    assert trainer.targetPitches == [G, B, 74]
    assert trainer.lessonProgress == 2


def test_a_wrong_resolution_gets_a_hint_after_release(trainer):
    trainer.start_single_drill("theory", "dominant_motion")
    for p in (D, F, A):
        trainer.handle_midi_note(p, True)
    assert wait_for(lambda: trainer.failures, 500)
    played_before = len(trainer.midi_out)
    for p in (D, F, A):
        trainer.handle_midi_note(p, False)

    assert trainer.midi_out[played_before:] == [[C, E, G]]  # the answer, played as a hint
    assert trainer.visuals[-1]["highlighted_chords"] == ["G", "C"]
    assert trainer.targetPitches == [C, E, G]  # still the same question

    chord(trainer, C, E, G)
    assert wait_for(lambda: trainer.exerciseName == "Resolve D → G")


def test_the_drill_ends_after_six_resolutions(trainer):
    trainer.start_single_drill("theory", "dominant_motion")
    for _ in range(6):
        before = trainer.lessonProgress
        chord(trainer, *trainer.targetPitches)
        assert wait_for(lambda: trainer.isLessonComplete or trainer.lessonProgress != before)
    assert trainer.isLessonComplete
    assert not trainer.isCircleOfFifthsMode


def test_with_a_coach_the_drill_waits_for_the_introduction(trainer):
    trainer.set_coach_available(True)
    trainer.start_single_drill("theory", "dominant_motion")
    assert trainer.isPausedForSpeech
    assert "Dominant Motion" in trainer.prompts[0]
    trainer.pause_for_speech()
    trainer.resume_lesson()
    assert not trainer.isPausedForSpeech
    chord(trainer, C, E, G)
    assert wait_for(lambda: trainer.exerciseName == "Resolve D → G")
    # Between pairs: one short read-aloud line, picked at random, naming the next V.
    from logic.services.circle_tutorial import DominantMotionDrill
    assert any(line.format(v="D") in trainer.prompts[-1]
               for line in DominantMotionDrill.PROMPTS_BETWEEN_PAIRS)


def test_quitting_the_drill_does_not_leak_into_the_next_lesson(trainer):
    trainer.start_single_drill("theory", "dominant_motion")
    trainer.stop_session()

    trainer.start_session()  # free practice
    trainer.present_exercise({"exercise_type": "chord", "exercise_name": "F Major",
                              "root_idx": 5, "chord_type_name": "Major"})
    chord(trainer, F, A, 72)
    assert wait_for(lambda: trainer.targetChord != "F Major", 1000), \
        "free practice should move on to a new chord"
    assert "Resolve" not in trainer.exerciseName


# ── Circle of Fifths ────────────────────────────────────────────────────────

def test_circle_tutorial_offline_steps_through_its_visuals(trainer):
    trainer.start_single_drill("theory", "circle_of_fifths")
    highlights = [trainer.visuals[-1]["highlight_key"]]
    for _ in range(6):
        assert trainer.isWaitingForUserContinue
        trainer.continueCircleTutorial()
        highlights.append(trainer.visuals[-1]["highlight_key"])
    assert highlights == ["", "C", "G", "D", "F", "Am", ""]
    assert trainer.isLessonComplete and not trainer.isCircleOfFifthsMode


def test_circle_tutorial_plays_each_steps_chord(trainer):
    trainer.start_single_drill("theory", "circle_of_fifths")
    trainer.continueCircleTutorial()  # to step 2: C major
    assert wait_for(lambda: [C, E, G] in trainer.midi_out, 1500)


def test_circle_tutorial_with_a_coach_waits_for_each_narration(trainer):
    trainer.set_coach_available(True)
    trainer.start_single_drill("theory", "circle_of_fifths")
    assert not trainer.isWaitingForUserContinue
    assert "Welcome to the Circle of Fifths" in trainer.prompts[-1]
    trainer.pause_for_speech()
    trainer.resume_lesson()
    assert trainer.isWaitingForUserContinue

    trainer.continueCircleTutorial()
    assert not trainer.isWaitingForUserContinue
    assert "C Major is at the very top" in trainer.prompts[-1]


def test_the_circle_prompt_can_be_resent_after_a_reconnect(trainer):
    trainer.start_single_drill("theory", "circle_of_fifths")
    trainer.continueCircleTutorial()
    trainer.continueCircleTutorial()  # step 3: G
    trainer.visuals.clear()
    prompt = trainer.circle_tutorial_prompt()
    assert "G Major is one step clockwise" in prompt
    assert trainer.visuals[-1]["highlight_key"] == "G"
