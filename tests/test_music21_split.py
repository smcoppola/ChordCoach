"""
Music21Service after the split: it owns a CorpusCatalog and a SongLibrary,
re-emits their signals, and delegates by name so QML sees one object.
(That every name QML uses still exists is test_qml_contract's job.)
"""
import json

import pytest

from logic.services.corpus_catalog import CorpusCatalog
from logic.services.music21_service import Music21Service
from logic.services.song_library import SongLibrary


def _write_song(user_dir, slug, title="A Song"):
    song_id = f"user::{slug}"
    record = {"schema_version": 2, "id": song_id, "title": title, "artist": "Someone",
              "level": "Grade 2", "key": "C Major", "steps": [], "groups": []}
    (user_dir / f"{slug}.json").write_text(json.dumps(record), encoding="utf-8")
    return song_id


@pytest.fixture
def service(qapp, tmp_user_songs_dir):
    _write_song(tmp_user_songs_dir, "mine-1", "Mine")
    return Music21Service()


def test_the_service_owns_one_catalog_and_one_library(service):
    assert isinstance(service.catalog, CorpusCatalog)
    assert isinstance(service.library, SongLibrary)
    assert service.catalog.parent() is service and service.library.parent() is service


@pytest.mark.parametrize("owner,signal,args", [
    ("library", "userSongsChanged", ()), ("library", "importSucceeded", ("user::x",)),
    ("library", "importFailed", ("boom",)), ("library", "importDuplicate", ("user::x", "X")),
    ("library", "songLevelFailed", ("boom",)), ("library", "songRequested", ("user::x",)),
    ("catalog", "corpusProgressChanged", (0.5,)), ("catalog", "corpusStatusChanged", ("hi",)),
    ("catalog", "corpusReady", ()), ("catalog", "corpusError", ()),
])
def test_signals_are_re_emitted_once(service, owner, signal, args):
    seen = []
    getattr(service, signal).connect(lambda *a: seen.append(a))
    getattr(getattr(service, owner), signal).emit(*args)
    assert seen == [args]


def test_the_browser_lists_library_songs_under_my_songs(service):
    assert {"id": "My Songs", "isCategory": True} in service.get_catalog()
    assert [s["id"] for s in service.get_catalog_level(["My Songs"])] == ["user::mine-1"]
    assert [s["id"] for s in service.search_catalog("Mine")][:1] == ["user::mine-1"]


def test_user_songs_load_through_the_service(service):
    assert service.load_song_as_steps("user::mine-1").get("title") == "Mine"
    assert service.get_user_songs()[0]["id"] == "user::mine-1"


def test_the_library_gets_the_analysis_functions_not_the_service(service):
    lib = service.library
    assert lib._extract_steps_from_score == service._extract_steps_from_score
    assert not hasattr(lib, "_chord_trainer") and not hasattr(lib, "catalog")


def test_the_song_in_play_is_protected_at_any_level(service):
    class Trainer:
        isActive = True
        songId = "user::mine-1::L2"
    service.set_chord_trainer(Trainer())
    assert "Stop practising" in service.delete_user_song("user::mine-1")
    Trainer.isActive = False
    assert service.delete_user_song("user::mine-1") == ""
