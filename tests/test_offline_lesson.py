"""
Sequenced lessons through the real ChordTrainerService, CurriculumService and
SQLite database — with no coach connected, and with a stand-in coach that is
told when to speak.

The point of local sequencing is that a lesson is the same lesson whether or
not the coach is reachable, so most of these run with nobody listening.
"""
import json
import time
from pathlib import Path

import pytest
from PySide6.QtTest import QTest

from logic.services.chord_trainer import ChordTrainerService
from logic.services.curriculum_service import CurriculumService
from logic.services.database_manager import DatabaseManager

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "resources"


class StubMusic21:
    """Songs load from memory; any piece listed in `broken` fails to load."""

    def __init__(self, broken=()):
        self.broken = set(broken)
        self.loaded = []

    def load_song_as_steps(self, piece_name):
        self.loaded.append(piece_name)
        if piece_name in self.broken:
            return {"steps": [], "title": "Error"}
        steps = []
        for i, pitches in enumerate([[60, 64], [62], [64, 67]]):
            n = len(pitches)
            steps.append({"offset": float(i), "duration": 1.0, "pitches": pitches,
                          "hands": ["right"] * n, "fingers": [1] * n})
        return {"steps": steps, "title": f"Piece {piece_name}", "composer": "Test",
                "key": "C major", "key_sharps": 0, "tempo_map": [], "time_signatures": [],
                "barlines": [], "pedal_events": []}

    def get_user_song_summaries(self):
        return []

    def get_recent_corpus_ids(self, limit=5):
        return []

    def get_user_song_pref(self, song_id, key, default=""):
        return default

    def set_user_song_pref(self, song_id, key, value):
        pass


@pytest.fixture
def make_trainer(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")  # three exercises per block
    made = []

    def make(music21=None):
        music21 = music21 or StubMusic21()
        db = DatabaseManager(tmp_path / f"lesson{len(made)}.db")
        curriculum = CurriculumService(db, RESOURCES, music21)
        trainer = ChordTrainerService(db, curriculum, None, music21)
        trainer.prompts = []
        trainer.speakInstruction.connect(trainer.prompts.append)
        trainer.speakBrief.connect(trainer.prompts.append)
        trainer.successes = []
        trainer.chordSuccess.connect(lambda name, ms: trainer.successes.append(name))
        made.append(trainer)
        return trainer

    yield make
    for t in made:
        t.stop_session()
        t._song.engine.stop()


def press(trainer, *pitches):
    for p in pitches:
        trainer.handle_midi_note(p, True)


def release(trainer, *pitches):
    for p in pitches:
        trainer.handle_midi_note(p, False)


def play_current(trainer):
    """Plays whatever is on screen correctly."""
    ex_type = trainer.exerciseType
    if ex_type == "theory_concept":
        trainer.continueConcept()
    elif ex_type == "listen":
        trainer.handle_ear_training_answer(trainer.targetFormulaText)
    elif ex_type == "pentascale":
        for p in list(trainer.pentascaleNotes):
            press(trainer, p)
            release(trainer, p)
    elif ex_type == "sustain_pedal":
        pitches = list(trainer.targetPitches)
        press(trainer, *pitches)
        trainer.handle_pedal_event(True)
        release(trainer, *pitches)
        trainer.handle_pedal_event(False)
    elif ex_type == "progression":
        for _ in range(len(trainer.progressionNumerals)):
            pitches = list(trainer.targetPitches)
            press(trainer, *pitches)
            release(trainer, *pitches)
    elif ex_type == "song_application":
        while not trainer.isSongCompleted:
            pitches = list(trainer.targetPitches)
            press(trainer, *pitches)
            release(trainer, *pitches)
    else:
        pitches = list(trainer.targetPitches)
        press(trainer, *pitches)
        release(trainer, *pitches)


def wait_for(predicate, timeout_ms=4000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if predicate():
            return True
        QTest.qWait(20)
    return predicate()


def play_lesson(trainer, limit=60):
    """Plays every exercise until the lesson ends. Returns the exercises played."""
    played = []
    for _ in range(limit):
        if trainer.isLessonComplete:
            return played
        played.append((trainer.exerciseType, trainer.exerciseName))
        before = trainer.lessonProgress
        play_current(trainer)
        assert wait_for(lambda: trainer.isLessonComplete or trainer.lessonProgress != before), \
            f"stuck on {played[-1]}"
    raise AssertionError("lesson did not end")


# ── Offline ─────────────────────────────────────────────────────────────────

def test_a_full_lesson_runs_with_no_coach(make_trainer):
    trainer = make_trainer()
    trainer.start_lesson_plan(10)
    assert trainer.isActive and trainer.isLessonMode
    assert not trainer.isPausedForSpeech, "nothing should wait for a coach that is not there"

    played = play_lesson(trainer)

    assert trainer.isLessonComplete and not trainer.isActive
    assert len(played) >= 3
    assert trainer.prompts == []  # nobody to talk to
    assert len(trainer.db.get_recent_sessions(limit=5)) == 1


MILESTONES = [
    (t, m["id"])
    for t, ms in json.loads((RESOURCES / "curriculum_tracks.json").read_text(encoding="utf-8")).items()
    for m in ms if m["id"] != "circle_of_fifths"  # scripted; see test_circle_tutorial_runs_on_continue_alone
]


@pytest.mark.parametrize("track,milestone", MILESTONES, ids=[m for _, m in MILESTONES])
def test_every_milestone_can_be_drilled_offline(make_trainer, track, milestone):
    trainer = make_trainer()
    trainer.start_single_drill(track, milestone)
    assert trainer.isActive, f"{milestone}: the drill did not start"
    played = play_lesson(trainer)
    assert trainer.isLessonComplete
    assert any(t != "theory_concept" for t, _ in played), f"{milestone}: nothing playable"


def test_curriculum_hints_reach_the_lesson(make_trainer):
    trainer = make_trainer()
    seq_holder = {}
    original = trainer._begin_lesson
    trainer._begin_lesson = lambda seq, ctx="": (seq_holder.setdefault("seq", seq), original(seq, ctx))[1]
    trainer.start_single_drill("technique", "inversions_intro")
    play_lesson(trainer)
    pool = {ex.get("inversion") for ex in seq_holder["seq"].history}
    assert pool & {1, 2}, "inversions_intro never asked for an inversion"


def test_a_concept_card_waits_for_continue(make_trainer):
    trainer = make_trainer()
    trainer.start_single_drill("theory", "major_formula")

    assert trainer.exerciseType == "theory_concept"
    assert trainer.conceptCard["title"] == "Major Formula" or trainer.conceptCard["title"]
    assert "half steps" in trainer.conceptCard["body"]
    assert trainer.targetPitches == []
    QTest.qWait(400)
    assert trainer.exerciseType == "theory_concept"  # does not move on by itself

    trainer.continueConcept()
    assert trainer.conceptCard == {}
    assert trainer.exerciseType == "chord"
    state = {m["milestone_id"]: m for m in trainer.db.get_curriculum_state("theory")}
    assert state["major_formula"]["attempts"] == 1


def test_a_struggled_exercise_comes_round_again(make_trainer):
    trainer = make_trainer()
    trainer.start_single_drill("technique", "rh_major_triads")
    first = (trainer.targetChord, list(trainer.targetPitches))

    wrong = [p + 2 for p in trainer.targetPitches]
    press(trainer, *wrong)
    QTest.qWait(400)  # the wrong-chord grace period
    release(trainer, *wrong)
    play_current(trainer)
    assert wait_for(lambda: trainer.lessonProgress == 2)

    assert (trainer.targetChord, list(trainer.targetPitches)) == first


def test_a_song_that_will_not_load_is_skipped(make_trainer):
    music21 = StubMusic21(broken={"essenFolksong/erk5.abc::6"})
    trainer = make_trainer(music21)
    errors = []
    trainer.statusMessageRequested.connect(lambda kind, msg: errors.append(kind))

    trainer.start_single_drill("repertoire", "song_breakdown_intro")

    assert music21.loaded[:2] == ["essenFolksong/erk5.abc::6", "airdsAirs/book1.abc::4"]
    assert trainer.isActive and trainer.exerciseType == "song_application"
    assert trainer.lessonProgress == 1
    assert errors == ["error"]


def test_review_session_replays_struggled_exercises(make_trainer):
    trainer = make_trainer()
    trainer._struggled_items = [
        {"name": "F Major", "chord_data": {"exercise_type": "chord", "exercise_name": "F Major",
                                           "root_idx": 5, "chord_type_name": "Major",
                                           "track": "technique", "milestone_id": ""}},
    ]
    trainer.start_review_session()
    assert trainer.exerciseName == "Review: F Major"
    assert trainer.targetPitches == [65, 69, 72]
    play_lesson(trainer)
    assert trainer.isLessonComplete


def test_circle_tutorial_runs_on_continue_alone(make_trainer):
    """Steps 1–6 wait for Continue; step 7 closes the lesson once it has been narrated."""
    trainer = make_trainer()
    trainer.start_single_drill("theory", "circle_of_fifths")
    for step in range(1, 7):
        assert trainer.isWaitingForUserContinue, f"no Continue at step {step}"
        trainer.continueCircleTutorial()
    assert trainer.isLessonComplete


# ── With a coach ────────────────────────────────────────────────────────────

def test_the_coach_introduces_then_stays_quiet_between_same_type_reps(make_trainer):
    trainer = make_trainer()
    trainer.set_coach_available(True)
    trainer.start_single_drill("technique", "rh_major_triads")

    assert len(trainer.prompts) == 1 and "first exercise" in trainer.prompts[0]
    assert trainer.isPausedForSpeech  # waiting for the coach
    assert trainer.targetPitches     # but the exercise is already on screen

    press(trainer, *trainer.targetPitches)
    assert trainer.successes == []   # no scoring while the coach talks
    release(trainer, *trainer.targetPitches)

    trainer.pause_for_speech()       # audio starts
    trainer.resume_lesson()          # audio ends
    assert not trainer.isPausedForSpeech

    play_current(trainer)
    assert wait_for(lambda: trainer.lessonProgress == 2)
    assert len(trainer.prompts) == 1  # same kind of drill: silent
    assert not trainer.isPausedForSpeech


def test_a_coach_that_never_speaks_does_not_stall_the_lesson(make_trainer):
    trainer = make_trainer()
    trainer.set_coach_available(True)
    trainer._speech_start_timer.setInterval(100)
    trainer.start_single_drill("technique", "rh_major_triads")
    assert trainer.isPausedForSpeech

    assert wait_for(lambda: not trainer.isPausedForSpeech, timeout_ms=1000)


def test_the_lesson_ends_after_the_coach_has_said_goodbye(make_trainer):
    trainer = make_trainer()
    trainer.start_single_drill("technique", "rh_major_triads")
    trainer.set_coach_available(True)  # connects mid-lesson

    for _ in range(2):
        before = trainer.lessonProgress
        play_current(trainer)
        assert wait_for(lambda: trainer.lessonProgress != before)
    play_current(trainer)
    assert wait_for(lambda: trainer.isPausedForSpeech)

    assert "lesson is over" in trainer.prompts[-1]
    assert not trainer.isLessonComplete  # the summary is still being spoken
    trainer.pause_for_speech()
    trainer.resume_lesson()
    assert trainer.isLessonComplete


def test_a_song_that_ends_the_lesson_is_mentioned_in_the_goodbye(make_trainer):
    trainer = make_trainer()
    trainer.set_coach_available(True)
    trainer.start_single_drill("repertoire", "song_breakdown_intro")  # one piece in dev mode
    trainer.pause_for_speech()
    trainer.resume_lesson()
    assert trainer.exerciseType == "song_application"

    title = trainer.songTitle
    play_current(trainer)
    assert wait_for(lambda: trainer.isPausedForSpeech, timeout_ms=4000)
    assert "lesson is over" in trainer.prompts[-1]
    assert title in trainer.prompts[-1]
