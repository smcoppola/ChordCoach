"""
Skill decay must happen once a day, never as a side effect of reading.

get_coach_context used to call calculate_skill_decay, which multiplies stale
scores without touching last_played. Every read — several per launch, one per
lesson — therefore shrank the same stale scores again.
"""
import sqlite3
from datetime import date, datetime, timedelta

from logic.services.database_manager import DatabaseManager


def _age_everything(db: DatabaseManager, days: int):
    old = (datetime.now() - timedelta(days=days)).isoformat()
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE songs SET last_played = ?", (old,))
        conn.execute("UPDATE chords SET last_played = ?", (old,))


def _scores(db: DatabaseManager):
    with sqlite3.connect(db.db_path) as conn:
        mastery = conn.execute("SELECT mastery_score FROM songs").fetchone()[0]
        successes = conn.execute("SELECT success_count FROM chords").fetchone()[0]
    return mastery, successes


def _stale_db(tmp_path) -> DatabaseManager:
    db = DatabaseManager(tmp_path / "decay.db")
    db.record_song_play("user::song", "Song", 50.0)
    for _ in range(10):
        db.record_chord_attempt("C Major", True, 500.0)
    _age_everything(db, days=5)
    return db


def test_reading_the_coach_context_does_not_decay(tmp_path):
    db = _stale_db(tmp_path)
    before = _scores(db)

    for _ in range(5):
        context = db.get_coach_context()

    assert _scores(db) == before
    # Stale chords are still reported to the coach.
    assert "Decayed Chords" in context
    assert "C Major" in context


def test_daily_decay_runs_once_per_day(tmp_path):
    db = _stale_db(tmp_path)
    day = date(2026, 11, 13)

    assert db.apply_daily_skill_decay(today=day) is True
    once = _scores(db)
    assert once == (50.0 * 0.90, 9)

    assert db.apply_daily_skill_decay(today=day) is False
    assert _scores(db) == once

    assert db.apply_daily_skill_decay(today=day + timedelta(days=1)) is True
    assert _scores(db) == (50.0 * 0.90 * 0.90, 8)


def test_fresh_items_do_not_decay(tmp_path):
    db = DatabaseManager(tmp_path / "fresh.db")
    db.record_song_play("user::song", "Song", 50.0)
    db.record_chord_attempt("C Major", True, 500.0)

    db.apply_daily_skill_decay(today=date(2026, 11, 13))

    assert _scores(db) == (50.0, 1)
    assert db.get_stale_chords() == []
