"""Phase 5 — library management operations (rename / delete / dedupe / mastery).

Everything here runs against the `tmp_user_songs_dir` fixture so the live user
library is never touched.
"""

import json

import pytest

from logic.services.music21_service import Music21Service
from logic.services.database_manager import DatabaseManager


def _write_song(user_dir, song_slug, title="A Song", artist="Someone",
                source_hash="hash-a", source_ext=".mid", **extra):
    """Creates a minimal user-song JSON record plus its archived source copy."""
    song_id = f"user::{song_slug}"
    record = {
        "schema_version": 2,
        "id": song_id,
        "title": title,
        "artist": artist,
        "level": "Grade 3",
        "key": "C Major",
        "key_sharps": 0,
        "bpm": 100.0,
        "source_type": "midi",
        "hand_mode": "auto",
        "imported_at": "2026-07-30 10:00:00",
        "barlines": [],
        "steps": [{"offset": 0.0, "pitches": [60], "duration": 1.0}],
        "quantized_groups": [{"offset": 0.0, "duration": 1.0, "notes": [[60, "right"]]}],
    }
    if source_hash:
        record["source_hash"] = source_hash
        record["source_copy"] = f"sources/{source_hash}{source_ext}"
        sources = user_dir / "sources"
        sources.mkdir(parents=True, exist_ok=True)
        (sources / f"{source_hash}{source_ext}").write_bytes(b"fake source bytes")
    record.update(extra)

    with open(user_dir / f"{song_slug}.json", "w") as f:
        json.dump(record, f)
    return song_id


class _FakeTrainer:
    """Stand-in for ChordTrainerService's active-song state."""

    def __init__(self, song_id="", active=False):
        self._song_id = song_id
        self.isActive = active


@pytest.fixture
def service(tmp_user_songs_dir):
    svc = Music21Service()
    svc._load_user_songs()
    return svc


# ── rename ──────────────────────────────────────────────────────────

def test_rename_rewrites_json_and_preserves_other_fields(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "old-song-1", title="Old Title")
    service._load_user_songs()

    service.rename_user_song(song_id, "New Title", "New Artist")

    with open(tmp_user_songs_dir / "old-song-1.json") as f:
        rec = json.load(f)
    assert rec["title"] == "New Title"
    assert rec["artist"] == "New Artist"
    # Untouched fields survive the rewrite
    assert rec["id"] == song_id
    assert rec["key"] == "C Major"
    assert rec["source_hash"] == "hash-a"
    # Steps survive the rewrite (the save path runs them through the v2 normalizer,
    # which only adds defaults — it never drops or changes the notes themselves)
    assert len(rec["steps"]) == 1
    assert rec["steps"][0]["offset"] == 0.0
    assert rec["steps"][0]["pitches"] == [60]
    assert rec["steps"][0]["duration"] == 1.0

    # In-memory catalog entry follows the record
    entry = next(s for s in service._user_songs if s["id"] == song_id)
    assert entry["title"] == "New Title"
    assert entry["artist"] == "New Artist"


def test_rename_ignores_empty_title(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "keep-me-1", title="Keep Me")
    service._load_user_songs()

    service.rename_user_song(song_id, "   ", "Whoever")

    with open(tmp_user_songs_dir / "keep-me-1.json") as f:
        assert json.load(f)["title"] == "Keep Me"


def test_rename_invalidates_level_cache(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "cached-1")
    service._load_user_songs()
    service._level_cache[song_id] = {"steps": []}
    service._level_cache[song_id + "::L2"] = {"steps": []}

    service.rename_user_song(song_id, "Renamed", "")

    assert service._level_cache == {}


# ── delete ──────────────────────────────────────────────────────────

def test_delete_removes_record_and_last_source_copy(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "lonely-1", source_hash="hash-lonely")
    service._load_user_songs()

    err = service.delete_user_song(song_id)

    assert err == ""
    assert not (tmp_user_songs_dir / "lonely-1.json").exists()
    assert not (tmp_user_songs_dir / "sources" / "hash-lonely.mid").exists()
    assert all(s["id"] != song_id for s in service._user_songs)


def test_delete_keeps_source_copy_shared_with_another_record(service, tmp_user_songs_dir):
    first = _write_song(tmp_user_songs_dir, "twin-a-1", source_hash="hash-shared")
    _write_song(tmp_user_songs_dir, "twin-b-1", source_hash="hash-shared")
    service._load_user_songs()

    assert service.delete_user_song(first) == ""
    assert (tmp_user_songs_dir / "sources" / "hash-shared.mid").exists()

    # ...and goes away once the last reference is deleted
    assert service.delete_user_song("user::twin-b-1") == ""
    assert not (tmp_user_songs_dir / "sources" / "hash-shared.mid").exists()


def test_delete_sweeps_pre_existing_orphan_sources(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "solo-1", source_hash="hash-solo")
    orphan = tmp_user_songs_dir / "sources" / "hash-nobody.mid"
    orphan.write_bytes(b"orphaned")
    service._load_user_songs()

    service.delete_user_song(song_id)

    assert not orphan.exists()


def test_delete_refused_while_song_is_being_practised(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "in-use-1")
    service._load_user_songs()
    # The trainer reports the ::L3 variant — the base song must still be protected
    service.set_chord_trainer(_FakeTrainer(song_id + "::L3", active=True))

    err = service.delete_user_song(song_id)

    assert err != ""
    assert (tmp_user_songs_dir / "in-use-1.json").exists()
    assert any(s["id"] == song_id for s in service._user_songs)


def test_delete_allowed_when_trainer_is_idle(service, tmp_user_songs_dir):
    song_id = _write_song(tmp_user_songs_dir, "idle-1")
    service._load_user_songs()
    service.set_chord_trainer(_FakeTrainer(song_id, active=False))

    assert service.delete_user_song(song_id) == ""
    assert not (tmp_user_songs_dir / "idle-1.json").exists()


def test_delete_unknown_song_returns_error(service):
    assert service.delete_user_song("user::does-not-exist") != ""


# ── duplicates ──────────────────────────────────────────────────────

def test_find_duplicates_groups_by_source_hash(service, tmp_user_songs_dir):
    _write_song(tmp_user_songs_dir, "dup-a-1", title="Dup A", source_hash="hash-dup")
    _write_song(tmp_user_songs_dir, "dup-b-1", title="Dup B", source_hash="hash-dup")
    _write_song(tmp_user_songs_dir, "unique-1", title="Unique", source_hash="hash-unique")
    _write_song(tmp_user_songs_dir, "hashless-1", title="Hashless", source_hash=None)
    service._load_user_songs()

    groups = service.find_duplicates()

    assert len(groups) == 1
    group = groups[0]
    assert group["source_hash"] == "hash-dup"
    assert group["count"] == 2
    assert sorted(s["title"] for s in group["songs"]) == ["Dup A", "Dup B"]


def test_find_duplicates_empty_library(service):
    assert service.find_duplicates() == []


# ── get_user_songs ──────────────────────────────────────────────────

def test_get_user_songs_shape_without_database(service, tmp_user_songs_dir):
    _write_song(tmp_user_songs_dir, "listed-1", title="Listed", artist="Composer")
    service._load_user_songs()

    songs = service.get_user_songs()

    assert len(songs) == 1
    song = songs[0]
    for field in ("id", "title", "artist", "level", "key", "imported_at",
                  "source_type", "hand_mode", "practice_mode", "mastery", "last_played"):
        assert field in song, f"missing field {field}"
    assert song["title"] == "Listed"
    assert song["key"] == "C Major"
    assert song["source_type"] == "midi"
    assert song["mastery"] == 0
    assert song["last_played"] == ""


def test_get_user_songs_joins_mastery(service, tmp_user_songs_dir, tmp_path):
    song_id = _write_song(tmp_user_songs_dir, "played-1", title="Played")
    service._load_user_songs()
    db = DatabaseManager(tmp_path / "mastery.db")
    db.record_song_play(filepath=song_id, title="Played", mastery_gained=42.0)
    service.set_database(db)

    song = service.get_user_songs()[0]

    assert song["mastery"] == pytest.approx(42.0)
    assert song["last_played"]


# ── get_song_masteries ──────────────────────────────────────────────

def test_get_song_masteries_empty_without_rows(tmp_path):
    db = DatabaseManager(tmp_path / "empty.db")
    assert db.get_song_masteries(["user::nothing-1"]) == {}
    assert db.get_song_masteries([]) == {}


def test_get_song_masteries_aggregates_level_variants(tmp_path):
    db = DatabaseManager(tmp_path / "levels.db")
    db.record_song_play(filepath="user::song-1", title="Song", mastery_gained=10.0)
    db.record_song_play(filepath="user::song-1::L2", title="Song", mastery_gained=30.0)
    db.record_song_play(filepath="user::other-1", title="Other", mastery_gained=5.0)

    res = db.get_song_masteries(["user::song-1"])

    assert set(res) == {"user::song-1"}
    assert res["user::song-1"]["mastery"] == pytest.approx(30.0)
    assert res["user::song-1"]["play_count"] == 2
    assert res["user::song-1"]["last_played"]
