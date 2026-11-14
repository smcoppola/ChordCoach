"""
The SM-2 review schedule end to end: the review_items table, what a lesson
plan takes from it, the Review block that opens a lesson, and what the trainer
records as it is played.
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtTest import QTest

from logic.services.chord_trainer import ChordTrainerService
from logic.services.curriculum_service import CurriculumService
from logic.services.database_manager import DatabaseManager
from logic.services.lesson_sequencer import LessonSequencer, review_exercises

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "resources"
DAY = timedelta(days=1)


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(tmp_path / "reviews.db")


def _row(db, item_type, item_id):
    with sqlite3.connect(db.db_path) as conn:
        return conn.execute(
            "SELECT ease, interval_days, repetitions, due_at, last_quality FROM review_items"
            " WHERE item_type = ? AND item_id = ?", (item_type, item_id)).fetchone()


# ── The table ───────────────────────────────────────────────────────────────

def test_first_review_is_due_the_next_day(db):
    now = datetime(2026, 11, 13, 18, 0)
    assert db.record_review("chord", "C Major", 4, now=now) is True
    _, interval, reps, due, quality = _row(db, "chord", "C Major")
    assert (interval, reps, quality) == (1, 1, 4)
    assert due == (now + DAY).isoformat()


def test_only_the_first_review_of_a_day_counts(db):
    morning = datetime(2026, 11, 13, 9, 0)
    db.record_review("chord", "C Major", 5, now=morning)
    first = _row(db, "chord", "C Major")

    for hour in (10, 11, 12):
        assert db.record_review("chord", "C Major", 1, now=morning.replace(hour=hour)) is False
    assert _row(db, "chord", "C Major") == first

    assert db.record_review("chord", "C Major", 5, now=morning + DAY) is True
    assert _row(db, "chord", "C Major")[1] == 6  # second success: six days


def test_due_reviews_most_overdue_first(db):
    now = datetime(2026, 11, 13, 12, 0)
    db.record_review("chord", "G Major", 4, now=now - 2 * DAY)
    db.record_review("chord", "C Major", 4, now=now - 5 * DAY)
    db.record_review("song", "user::tune", 4, now=now - 3 * DAY)
    db.record_review("chord", "F Major", 4, now=now)  # not due yet

    due = db.get_due_reviews(now=now)
    assert [(d["item_type"], d["item_id"]) for d in due] == \
        [("chord", "C Major"), ("song", "user::tune"), ("chord", "G Major")]
    assert [d["item_id"] for d in db.get_due_reviews(now=now, item_type="chord", limit=1)] == ["C Major"]
    assert db.count_due_reviews(now=now) == 3


def test_resetting_stats_clears_the_schedule(db):
    db.record_review("chord", "C Major", 4)
    db.reset_all_stats()
    assert db.get_due_reviews(now=datetime.now() + 30 * DAY) == []


def test_the_coach_is_told_what_is_due(db):
    db.record_review("chord", "A Minor", 4, now=datetime.now() - 3 * DAY)
    assert "Due for review" in db.get_coach_context()
    assert "chord: A Minor" in db.get_coach_context()


# ── The lesson plan and the Review block ────────────────────────────────────

def test_the_session_plan_carries_due_items(db):
    curriculum = CurriculumService(db, RESOURCES)
    long_ago = datetime.now() - 10 * DAY
    for name in ["C Major", "F Major", "G Major", "A Minor", "D Minor", "E Minor"]:
        db.record_review("chord", name, 4, now=long_ago)
    db.record_review("song", "user::a", 4, now=long_ago)
    db.record_review("song", "user::b", 4, now=long_ago)

    plan = curriculum.plan_session(10)

    kinds = [i["item_type"] for i in plan["review_items"]]
    assert kinds.count("chord") == CurriculumService.MAX_REVIEW_CHORDS
    assert kinds.count("song") == CurriculumService.MAX_REVIEW_SONGS
    assert curriculum.reviewQueueCount == 8


def test_due_items_open_the_lesson():
    plan = {"review_items": [{"item_type": "chord", "item_id": "A Minor"},
                             {"item_type": "song", "item_id": "user::mine"}],
            "blocks": [{"track": "technique", "milestone_id": "x", "milestone_title": "Triads",
                        "exercise_types": ["chord"], "target_chords": ["C Major"], "step_count": 2}]}
    seq = LessonSequencer(plan, library=[{"id": "user::mine", "title": "My Song"}], seed=1)

    first, second = seq.next_exercise(), seq.next_exercise({"struggled": False})
    assert (first["exercise_name"], first["root_idx"], first["chord_type_name"]) == ("Review: A Minor", 9, "Minor")
    assert (second["exercise_type"], second["piece_name"], second["exercise_name"]) == \
        ("song_application", "user::mine", "Review: My Song")
    assert first["track"] == "review" and first["milestone_id"] == ""
    assert seq.block_titles[0] == "Review"
    assert seq.next_exercise({"struggled": False})["milestone_id"] == "x"


def test_unreadable_review_items_are_skipped():
    assert review_exercises([{"item_type": "chord", "item_id": "Listen to the chord"},
                             {"item_type": "key", "item_id": "D"}]) == []


def test_dev_mode_keeps_the_review_short():
    items = [{"item_type": "chord", "item_id": n} for n in ("C Major", "F Major", "G Major")]
    seq = LessonSequencer({"review_items": items, "blocks": []}, dev_mode=True)
    assert len([e for e in iter(lambda: seq.next_exercise({}), None)]) == 2


# ── What the trainer records ────────────────────────────────────────────────

@pytest.fixture
def trainer(qapp, db):
    music21 = MagicMock()
    music21.get_user_song_pref.side_effect = lambda s, k, d="": d
    t = ChordTrainerService(db, None, None, music21)
    yield t
    t.stop_session()
    t._song.engine.stop()


def _play(trainer, exercise):
    trainer.present_exercise(exercise)
    pitches = list(trainer.targetPitches)
    for p in pitches:
        trainer.handle_midi_note(p, True)
    for p in pitches:
        trainer.handle_midi_note(p, False)


def test_a_chord_is_reviewed_under_its_plain_name(trainer, db):
    _play(trainer, {"exercise_type": "chord", "exercise_name": "C Major — 1st inversion",
                    "root_idx": 0, "chord_type_name": "Major", "inversion": 1})
    assert trainer.targetChord == "C Major (1st inv)"
    assert _row(db, "chord", "C Major") is not None


def test_a_wrong_chord_is_a_lapse(trainer, db):
    trainer.present_exercise({"exercise_type": "chord", "exercise_name": "G Major",
                              "root_idx": 7, "chord_type_name": "Major"})
    for p in (62, 65, 69):  # D minor
        trainer.handle_midi_note(p, True)
    QTest.qWait(400)
    assert _row(db, "chord", "G Major")[4] == 1


def test_progression_chords_are_reviewed_one_by_one(trainer, db):
    trainer.present_exercise({"exercise_type": "progression", "exercise_name": "I–V",
                              "progression_steps": [{"root_idx": 0, "chord_type_name": "Major", "numeral": "I"},
                                                    {"root_idx": 7, "chord_type_name": "Major", "numeral": "V"}]})
    for _ in range(2):
        pitches = list(trainer.targetPitches)
        for p in pitches:
            trainer.handle_midi_note(p, True)
        for p in pitches:
            trainer.handle_midi_note(p, False)
    assert _row(db, "chord", "C Major") and _row(db, "chord", "G Major")


def test_ear_training_and_scales_are_not_scheduled(trainer, db):
    trainer.present_exercise({"exercise_type": "listen", "exercise_name": "Major or Minor?",
                              "root_idx": 0, "chord_type_name": "Major", "target_quality": "Major"})
    trainer.handle_ear_training_answer("Major")
    trainer.present_exercise({"exercise_type": "pentascale", "exercise_name": "C Pentascale",
                              "root_idx": 0, "scale_type": "Major"})
    for p in (60, 62, 64, 65, 67):
        trainer.handle_midi_note(p, True)
        trainer.handle_midi_note(p, False)
    QTest.qWait(700)
    assert db.get_due_reviews(now=datetime.now() + 30 * DAY) == []


def test_a_finished_song_reviews_the_song_not_its_difficulty_variant(trainer, db):
    trainer._song.song_id = "user::tune::L2"
    trainer._song.record_completion(2.0, {"mode": "self_paced", "wrongNotes": 1})
    assert _row(db, "song", "user::tune")[4] == 4
    assert _row(db, "song", "user::tune::L2") is None


def test_corpus_tune_indexes_are_kept(trainer):
    assert trainer._song.review_song_id("essenFolksong/erk5.abc::7") == "essenFolksong/erk5.abc::7"


def test_a_loop_only_run_is_not_a_review(trainer, db):
    trainer._song.song_id = "user::tune"
    trainer._song.record_completion(1.0, {"mode": "rhythm", "accuracy": 0.9, "loopOnly": True})
    assert _row(db, "song", "user::tune") is None


def test_quick_review_plays_due_items_then_todays_struggles(trainer, db):
    db.record_review("chord", "D Minor", 4, now=datetime.now() - 3 * DAY)
    db.record_review("chord", "F Major", 4)  # reviewed just now: not due
    trainer._struggled_items = [{"name": "G Major", "chord_data": {
        "exercise_type": "chord", "exercise_name": "G Major", "root_idx": 7,
        "chord_type_name": "Major", "track": "technique", "milestone_id": ""}}]

    trainer.start_review_session()

    assert trainer.isLessonMode and trainer.exerciseName == "Review: D Minor"
    names = []
    while not trainer.isLessonComplete:
        names.append(trainer.exerciseName)
        before = trainer.lessonProgress
        pitches = list(trainer.targetPitches)
        for p in pitches:
            trainer.handle_midi_note(p, True)
        for p in pitches:
            trainer.handle_midi_note(p, False)
        for _ in range(50):
            if trainer.isLessonComplete or trainer.lessonProgress != before:
                break
            QTest.qWait(20)
    assert names == ["Review: D Minor", "Review: G Major"]
    assert db.count_due_reviews() == 0


def test_quick_review_after_a_real_struggle(trainer):
    """Struggled items keep the normalised exercise, `intervals` set and all."""
    trainer.present_exercise({"exercise_type": "chord", "exercise_name": "C Major",
                              "root_idx": 0, "chord_type_name": "Major", "inversion": 1})
    for p in (61, 63, 66):  # three wrong notes on the way: a struggle
        trainer.handle_midi_note(p, True)
        trainer.handle_midi_note(p, False)
    for p in trainer.targetPitches:
        trainer.handle_midi_note(p, True)
    assert isinstance(trainer.struggledItems[0]["chord_data"]["intervals"], set)

    trainer.start_review_session()

    assert trainer.exerciseName == "Review: C Major"
    assert trainer.targetPitches == [64, 67, 72]  # still the 1st inversion


def test_quick_review_with_nothing_to_review_does_not_start(trainer):
    trainer.start_review_session()
    assert not trainer.isActive


def test_a_due_chord_opens_the_next_lesson(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    db = DatabaseManager(tmp_path / "lesson.db")
    db.record_review("chord", "E Minor", 4, now=datetime.now() - 3 * DAY)
    curriculum = CurriculumService(db, RESOURCES)
    trainer = ChordTrainerService(db, curriculum, None, MagicMock())
    try:
        trainer.start_lesson_plan(10)
        assert trainer.exerciseName == "Review: E Minor"
        assert trainer.lessonBlocks[0]["name"] == "Review"

        pitches = list(trainer.targetPitches)
        for p in pitches:
            trainer.handle_midi_note(p, True)
        for p in pitches:
            trainer.handle_midi_note(p, False)

        assert _row(db, "chord", "E Minor")[1] == 6  # second success: six days out
        assert db.count_due_reviews() == 0
    finally:
        trainer.stop_session()
