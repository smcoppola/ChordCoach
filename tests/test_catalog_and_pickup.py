import os
import pytest
import music21
from music21 import stream, note, meter, clef
from logic.services.music21_service import Music21Service

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))


def test_catalog_methods_restored(tmp_user_songs_dir):
    service = Music21Service()
    assert service._catalog is not None
    assert len(service._flat_catalog) > 0

    # Test get_catalog_level top-level
    top_levels = service.get_catalog_level([])
    assert len(top_levels) > 0

    # Test search_catalog
    res = service.search_catalog("bach")
    assert isinstance(res, list)

    # Test get_recent_songs
    recents = service.get_recent_songs()
    assert isinstance(recents, list)


def test_pickup_measure_barlines(tmp_user_songs_dir):
    service = Music21Service()
    s = stream.Score()
    p = stream.Part()
    p.insert(0, clef.TrebleClef())
    p.insert(0, meter.TimeSignature('4/4'))

    # Measure 0 (pickup measure of 1 beat)
    m0 = stream.Measure(number=0)
    m0.append(note.Note('C4', quarterLength=1.0))

    # Measure 1 (full 4 beats starting at offset 1.0)
    m1 = stream.Measure(number=1)
    m1.append(note.Note('G4', quarterLength=4.0))

    p.append(m0)
    p.append(m1)
    s.append(p)

    steps, barlines, extra_meta = service._extract_steps_from_score(s)
    # The measure boundary after pickup measure starts at offset 1.0
    assert 1.0 in barlines
