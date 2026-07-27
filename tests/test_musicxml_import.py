import os
import pytest
from logic.services.music21_service import Music21Service

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))


def test_do_import_musicxml():
    xml_path = os.path.join(FIXTURES_DIR, "waltz_34.musicxml")
    service = Music21Service()

    song_id, entry = service._do_import_musicxml(xml_path)
    assert song_id.startswith(service.USER_SONG_PREFIX)
    assert entry["title"] is not None

    record = service._load_user_song_steps(song_id)
    assert record["schema_version"] == 2
    assert record["source_type"] == "musicxml"
    assert record["time_signatures"] == [{"offset": 0.0, "numerator": 3, "denominator": 4}]

    steps = record["steps"]
    assert len(steps) > 0

    # Step 0 checks
    s0 = steps[0]
    assert s0["durations"][0] == 1.5
    # Native fingering preserved
    assert s0["fingers"][0] == 3

    # Dynamic extracted
    assert any(d["mark"] == "p" for d in record.get("dynamics", []))

    # Tuplet check
    tuplet_step = None
    for s in steps:
        for t in s.get("tuplets", []):
            if t is not None:
                tuplet_step = t
                break
    assert tuplet_step is not None
    assert tuplet_step["actual"] == 3
    assert tuplet_step["normal"] == 2
