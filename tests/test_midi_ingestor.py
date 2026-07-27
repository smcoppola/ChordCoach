import os
import pytest
from logic.services.midi_ingestor import parse_and_quantize

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))


def test_two_track_midi_ingest():
    midi_path = os.path.join(FIXTURES_DIR, "two_track.mid")
    res = parse_and_quantize(midi_path)

    assert "title" in res
    assert res["single_track"] is False
    assert len(res["time_signatures"]) >= 1
    assert res["time_signatures"][0]["numerator"] == 3
    assert res["time_signatures"][0]["denominator"] == 4

    assert len(res["tempo_map"]) >= 1
    assert len(res["pedal_events"]) >= 1
    # Check CC64 pedal events captured
    assert any(p["down"] is True for p in res["pedal_events"])

    # Check note groups have velocities
    groups = res["groups"]
    assert len(groups) > 0
    assert "velocities" in groups[0]
    assert all(v is not None for v in groups[0]["velocities"])

    # Hand tagging check: 2-track input hand tagging maintains lower mean pitch = left
    all_notes = []
    for g in groups:
        for p, h in g["notes"]:
            all_notes.append((p, h))
    rh_pitches = [p for p, h in all_notes if h == "right"]
    lh_pitches = [p for p, h in all_notes if h == "left"]
    assert min(rh_pitches) > max(lh_pitches)


def test_single_track_midi_ingest():
    midi_path = os.path.join(FIXTURES_DIR, "single_track.mid")
    res = parse_and_quantize(midi_path)

    assert res["single_track"] is True
    assert len(res["groups"]) > 0
