"""Phase 6 — AI library awareness, repertoire bindings and the review queue.

Covers the song-library section of the coach context, `get_user_song_summaries`,
the `suggested_pieces` milestone field and `reviewQueueCount`. Anything that
touches user songs goes through the `tmp_user_songs_dir` fixture, so the live
library is never written to.
"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from logic.services.curriculum_service import CurriculumService
from logic.services.database_manager import DatabaseManager
from logic.services.music21_service import Music21Service


# ── helpers ─────────────────────────────────────────────────────────

def _write_song(user_dir, slug, title="A Song", level="Grade 3"):
    song_id = f"user::{slug}"
    record = {
        "schema_version": 2,
        "id": song_id,
        "title": title,
        "artist": "Someone",
        "level": level,
        "key": "C Major",
        "key_sharps": 0,
        "bpm": 100.0,
        "source_type": "midi",
        "imported_at": "2026-07-30 10:00:00",
        "barlines": [],
        "steps": [{
            "offset": 0.0, "pitches": [60], "duration": 1.0, "durations": [1.0],
            "hands": ["right"], "spellings": ["C4"], "fingers": [1],
            "ties": [None], "beams": [[]], "rests": [],
        }],
        "quantized_groups": [{"offset": 0.0, "duration": 1.0, "notes": [[60, "right"]]}],
    }
    with open(user_dir / f"{slug}.json", "w") as f:
        json.dump(record, f)
    return song_id


class _FakeMusic21:
    """Stands in for Music21Service when only the context strings are of interest."""

    def __init__(self, summaries=None, recent=None):
        self._summaries = summaries or []
        self._recent = recent or []
        self.recent_limit_seen = None

    def get_user_song_summaries(self):
        return list(self._summaries)

    def get_recent_corpus_ids(self, limit=5):
        self.recent_limit_seen = limit
        return list(self._recent)[:limit]


class _FakeDB:
    """Minimal DatabaseManager surface used by CurriculumService."""

    def __init__(self, active=None, review_count=0):
        self._active = active or []
        self.review_count = review_count

    def initialize_curriculum(self, tracks):
        pass

    def get_coach_context(self):
        return "User Practice Context:\n"

    def get_active_milestones(self):
        return list(self._active)

    def get_recent_sessions(self, limit=3):
        return []

    def count_songs_due_for_review(self, decay_hours=48):
        return self.review_count


def _milestone(track, milestone_id):
    return {"track_name": track, "milestone_id": milestone_id,
            "attempts": 0, "successes": 0, "status": "active"}


@pytest.fixture
def tracks_dir(tmp_path):
    """A tiny curriculum: one milestone with suggested_pieces, one without."""
    resources = tmp_path / "resources"
    resources.mkdir()
    tracks = {
        "technique": [{
            "id": "tech_1", "title": "Tech One", "order": 1,
            "exercise_types": ["chord"], "target_keys": ["C"], "target_chords": [],
            "min_attempts_to_advance": 2, "min_accuracy_to_advance": 0.5,
        }],
        "repertoire": [{
            "id": "rep_1", "title": "Rep One", "order": 1,
            "exercise_types": ["song_application"], "target_keys": [], "target_chords": [],
            "min_attempts_to_advance": 2, "min_accuracy_to_advance": 0.5,
            "suggested_pieces": ["essenFolksong/erk5.abc::7", "bach/bwv1.6.mxl"],
        }],
    }
    with open(resources / "curriculum_tracks.json", "w", encoding="utf-8") as f:
        json.dump(tracks, f)
    return resources


@pytest.fixture
def service(tmp_user_songs_dir):
    svc = Music21Service()
    svc._load_user_songs()
    return svc


# ── get_user_song_summaries ─────────────────────────────────────────

def test_summaries_shape_without_database(service, tmp_user_songs_dir):
    _write_song(tmp_user_songs_dir, "shape-1", title="Shapely", level="Grade 2")
    service._load_user_songs()

    summaries = service.get_user_song_summaries()

    assert len(summaries) == 1
    song = summaries[0]
    assert set(song) == {"id", "title", "grade", "mastery", "last_played"}
    assert song["id"] == "user::shape-1"
    assert song["title"] == "Shapely"
    assert song["grade"] == 2
    assert song["mastery"] == 0
    assert song["last_played"] == ""


def test_summaries_join_mastery_from_database(service, tmp_user_songs_dir, tmp_path):
    played = _write_song(tmp_user_songs_dir, "played-1", title="Played")
    _write_song(tmp_user_songs_dir, "unplayed-1", title="Unplayed")
    service._load_user_songs()

    db = DatabaseManager(tmp_path / "mastery.db")
    db.record_song_play(filepath=played, title="Played", mastery_gained=35.0)
    service.set_database(db)

    by_id = {s["id"]: s for s in service.get_user_song_summaries()}

    assert by_id[played]["mastery"] == pytest.approx(35.0)
    assert by_id[played]["last_played"]
    # A song with no rows is simply "never played", not an error
    assert by_id["user::unplayed-1"]["mastery"] == 0
    assert by_id["user::unplayed-1"]["last_played"] == ""


def test_summaries_grade_defaults_to_zero_for_ungraded_level(service, tmp_user_songs_dir):
    _write_song(tmp_user_songs_dir, "ungraded-1", level="Imported")
    service._load_user_songs()

    assert service.get_user_song_summaries()[0]["grade"] == 0


def test_summaries_sort_in_progress_then_unplayed_then_mastered(service,
                                                                tmp_user_songs_dir,
                                                                tmp_path):
    _write_song(tmp_user_songs_dir, "fresh-1", title="Never Played")
    _write_song(tmp_user_songs_dir, "learning-1", title="In Progress")
    _write_song(tmp_user_songs_dir, "known-1", title="Mastered")
    service._load_user_songs()

    db = DatabaseManager(tmp_path / "sort.db")
    db.record_song_play(filepath="user::learning-1", title="In Progress", mastery_gained=40.0)
    db.record_song_play(filepath="user::known-1", title="Mastered", mastery_gained=95.0)
    service.set_database(db)

    order = [s["id"] for s in service.get_user_song_summaries()]

    assert order == ["user::learning-1", "user::fresh-1", "user::known-1"]


def test_summaries_empty_library(service):
    assert service.get_user_song_summaries() == []


def test_recent_corpus_ids_exclude_imported_songs(service):
    service._recent_songs = ["user::mine-1", "bach/bwv1.6.mxl",
                             "user::mine-2", "essenFolksong/erk5.abc::7"]

    assert service.get_recent_corpus_ids() == ["bach/bwv1.6.mxl",
                                               "essenFolksong/erk5.abc::7"]
    assert service.get_recent_corpus_ids(limit=1) == ["bach/bwv1.6.mxl"]


# ── library section of the coach context ────────────────────────────

def test_context_contains_library_section(tracks_dir):
    music21 = _FakeMusic21(
        summaries=[{"id": "user::fur-elise-1721912345", "title": "Für Elise",
                    "grade": 4, "mastery": 35.0, "last_played": "2026-07-20T09:15:00"}],
        recent=["bach/bwv1.6.mxl"],
    )
    svc = CurriculumService(_FakeDB(), tracks_dir, music21)

    context = svc.get_curriculum_context()

    assert "STUDENT'S SONG LIBRARY (assignable via song_application piece_name):" in context
    assert ('- user::fur-elise-1721912345 — "Für Elise" '
            "(Grade 4, mastery 35%, last played 2026-07-20)") in context
    assert "Recently played corpus pieces: bach/bwv1.6.mxl" in context


def test_context_library_section_empty_profile(tracks_dir):
    svc = CurriculumService(_FakeDB(), tracks_dir, _FakeMusic21())

    context = svc.get_curriculum_context()

    assert "STUDENT'S SONG LIBRARY" in context
    assert "(none yet)" in context
    assert "Recently played corpus pieces" not in context


def test_context_survives_a_missing_music21_service(tracks_dir):
    svc = CurriculumService(_FakeDB(), tracks_dir)

    context = svc.get_curriculum_context()

    assert "(none yet)" in context


def test_context_caps_library_lines_and_recent_corpus(tracks_dir):
    summaries = [{"id": f"user::song-{i}", "title": f"Song {i}",
                  "grade": 2, "mastery": 50.0 - i, "last_played": "2026-07-01T00:00:00"}
                 for i in range(40)]
    music21 = _FakeMusic21(summaries=summaries,
                           recent=[f"corpus/piece{i}" for i in range(10)])
    svc = CurriculumService(_FakeDB(), tracks_dir, music21)

    context = svc.get_curriculum_context()

    library_lines = [ln for ln in context.splitlines() if ln.startswith("- user::")]
    assert len(library_lines) == CurriculumService.MAX_LIBRARY_LINES == 20
    # The cap keeps the head of the (already sorted) list
    assert library_lines[0].startswith("- user::song-0 ")
    assert music21.recent_limit_seen == CurriculumService.MAX_RECENT_CORPUS
    assert context.count("corpus/piece") == 5


def test_context_truncates_long_titles(tracks_dir):
    long_title = "A Really Very Extremely Long Piece Title That Rambles On"
    music21 = _FakeMusic21(summaries=[{"id": "user::long-1", "title": long_title,
                                       "grade": 3, "mastery": 10.0, "last_played": ""}])
    svc = CurriculumService(_FakeDB(), tracks_dir, music21)

    line = next(ln for ln in svc.get_curriculum_context().splitlines()
                if ln.startswith("- user::long-1"))

    assert long_title not in line
    title = line.split('"')[1]
    assert len(title) <= CurriculumService.MAX_TITLE_CHARS
    assert title.endswith("…")


def test_context_marks_never_played_songs(tracks_dir):
    music21 = _FakeMusic21(summaries=[{"id": "user::new-1", "title": "New One",
                                       "grade": 1, "mastery": 0.0, "last_played": ""}])
    svc = CurriculumService(_FakeDB(), tracks_dir, music21)

    assert "mastery 0%, never played" in svc.get_curriculum_context()


# ── suggested_pieces on milestones ──────────────────────────────────

def test_milestone_lines_render_with_and_without_suggested_pieces(tracks_dir):
    db = _FakeDB(active=[_milestone("technique", "tech_1"),
                         _milestone("repertoire", "rep_1")])
    svc = CurriculumService(db, tracks_dir, _FakeMusic21())

    lines = svc.get_curriculum_context().splitlines()
    tech_line = next(ln for ln in lines if "Tech One" in ln)
    rep_line = next(ln for ln in lines if "Rep One" in ln)

    assert tech_line == "- [Technique] Tech One (not started)"
    assert rep_line == ("- [Repertoire] Rep One (not started) — suggested pieces: "
                        "essenFolksong/erk5.abc::7, bach/bwv1.6.mxl")


def test_shipped_repertoire_milestones_have_suggested_pieces():
    """The three repertoire milestones ship with real, loadable corpus ids."""
    from pathlib import Path
    resources = Path(__file__).parent.parent / "src" / "resources"
    with open(resources / "curriculum_tracks.json", encoding="utf-8") as f:
        tracks = json.load(f)

    for milestone in tracks["repertoire"]:
        pieces = milestone.get("suggested_pieces")
        assert pieces and 2 <= len(pieces) <= 3, milestone["id"]
        assert all(isinstance(p, str) and p for p in pieces)

    # Every other milestone parses unchanged, without the optional field
    for track, milestones in tracks.items():
        if track == "repertoire":
            continue
        for milestone in milestones:
            assert "suggested_pieces" not in milestone


# ── reviewQueueCount ────────────────────────────────────────────────

def _insert_song(db, filepath, mastery, played_at):
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "INSERT INTO songs (filepath, title, last_played, play_count, mastery_score)"
            " VALUES (?, ?, ?, 1, ?)",
            (filepath, filepath, played_at.isoformat(), mastery),
        )
        conn.commit()


def test_review_count_only_includes_stale_started_songs(tmp_path):
    db = DatabaseManager(tmp_path / "review.db")
    now = datetime.now()
    _insert_song(db, "user::stale-1", 40.0, now - timedelta(hours=72))
    _insert_song(db, "user::fresh-1", 40.0, now - timedelta(hours=2))
    _insert_song(db, "user::never-scored-1", 0.0, now - timedelta(hours=72))

    assert db.count_songs_due_for_review(decay_hours=48) == 1


def test_review_count_collapses_difficulty_variants(tmp_path):
    db = DatabaseManager(tmp_path / "variants.db")
    now = datetime.now()
    # One song, three level variants, all stale — still one song to review
    _insert_song(db, "user::multi-1", 30.0, now - timedelta(hours=72))
    _insert_song(db, "user::multi-1::L2", 20.0, now - timedelta(hours=96))
    _insert_song(db, "user::multi-1::L3", 10.0, now - timedelta(hours=80))

    assert db.count_songs_due_for_review(decay_hours=48) == 1

    # A recent play on any variant takes the whole song out of the queue
    _insert_song(db, "user::multi-1::L4", 10.0, now - timedelta(hours=1))
    assert db.count_songs_due_for_review(decay_hours=48) == 0


def test_review_count_is_read_only(tmp_path):
    db = DatabaseManager(tmp_path / "readonly.db")
    _insert_song(db, "user::stale-1", 40.0, datetime.now() - timedelta(hours=72))

    db.count_songs_due_for_review(decay_hours=48)

    with sqlite3.connect(db.db_path) as conn:
        mastery = conn.execute(
            "SELECT mastery_score FROM songs WHERE filepath = 'user::stale-1'"
        ).fetchone()[0]
    assert mastery == pytest.approx(40.0), "the count must not apply decay"


def test_review_queue_property_reflects_the_database(tmp_path, tracks_dir):
    db = DatabaseManager(tmp_path / "prop.db")
    svc = CurriculumService(db, tracks_dir, _FakeMusic21())

    assert svc.reviewQueueCount == 0

    _insert_song(db, "user::stale-1", 40.0, datetime.now() - timedelta(hours=72))
    assert svc.reviewQueueCount == 1


def test_review_queue_property_survives_a_failing_database(tracks_dir):
    class _BrokenDB(_FakeDB):
        def count_songs_due_for_review(self, decay_hours=48):
            raise sqlite3.OperationalError("no such table: songs")

    svc = CurriculumService(_BrokenDB(), tracks_dir, _FakeMusic21())

    assert svc.reviewQueueCount == 0


# ── task 6: a hallucinated user:: id must not crash the trainer ─────

def test_bad_user_song_id_returns_an_empty_record(service):
    record = service.load_song_as_steps("user::bogus")

    assert record.get("steps") == []


def test_trainer_recovers_from_a_bad_song_application_exercise(service, tmp_user_songs_dir,
                                                               tmp_path):
    from logic.services.chord_trainer import ChordTrainerService, LessonState

    real_id = _write_song(tmp_user_songs_dir, "real-1", title="Real Song")
    service._load_user_songs()
    trainer = ChordTrainerService(DatabaseManager(tmp_path / "trainer.db"), None, None, service)

    statuses = []
    trainer.statusMessageRequested.connect(lambda kind, msg: statuses.append((kind, msg)))

    trainer.receive_exercise({
        "exercise_type": "song_application",
        "exercise_name": "Bogus Piece",
        "track": "repertoire",
        "milestone_id": "rep_1",
        "piece_name": "user::bogus",
    })

    assert trainer._state == LessonState.IDLE
    assert statuses and statuses[-1][0] == "error"

    # ...and the next exercise is still accepted
    trainer.receive_exercise({
        "exercise_type": "song_application",
        "exercise_name": "Real Piece",
        "track": "repertoire",
        "milestone_id": "rep_1",
        "piece_name": real_id,
    })

    assert trainer._state != LessonState.IDLE
    assert trainer._song_title == "Real Song"
