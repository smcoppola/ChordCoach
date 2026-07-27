import os
import json
import pytest
from logic.utils.step_schema import (
    CURRENT_SCHEMA_VERSION,
    migrate_record,
    compute_barlines,
    groups_from_steps,
)

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))


def test_migrate_v1_record():
    v1_path = os.path.join(FIXTURES_DIR, "v1_song.json")
    with open(v1_path, "r") as f:
        v1_data = json.load(f)

    v2_data = migrate_record(v1_data)

    assert v2_data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert v2_data["time_signatures"] == [{"offset": 0.0, "numerator": 4, "denominator": 4}]
    assert v2_data["tempo_map"] == [{"offset": 0.0, "bpm": 120.0}]
    assert v2_data["pedal_events"] == []
    assert v2_data["dynamics"] == []
    assert v2_data["source_type"] == "midi"

    # Step-level checks
    step0 = v2_data["steps"][0]
    assert step0["durations"] == [1.0, 1.0]
    assert step0["duration"] == 1.0
    assert step0["tuplets"] == [None, None]
    assert step0["articulations"] == [[], []]
    assert step0["velocities"] == [None, None]


def test_migrate_idempotent():
    v1_path = os.path.join(FIXTURES_DIR, "v1_song.json")
    with open(v1_path, "r") as f:
        v1_data = json.load(f)

    first_pass = migrate_record(v1_data)
    second_pass = migrate_record(first_pass)

    assert first_pass == second_pass


def test_compute_barlines_single_meter():
    time_sigs = [{"offset": 0.0, "numerator": 4, "denominator": 4}]
    barlines = compute_barlines(time_sigs, end_beat=16.0)
    assert barlines == [4.0, 8.0, 12.0, 16.0]

    # 3/4 meter
    time_sigs_34 = [{"offset": 0.0, "numerator": 3, "denominator": 4}]
    barlines_34 = compute_barlines(time_sigs_34, end_beat=9.0)
    assert barlines_34 == [3.0, 6.0, 9.0]

    # 6/8 meter (measure length = 6 * (4/8) = 3 beats)
    time_sigs_68 = [{"offset": 0.0, "numerator": 6, "denominator": 8}]
    barlines_68 = compute_barlines(time_sigs_68, end_beat=9.0)
    assert barlines_68 == [3.0, 6.0, 9.0]


def test_compute_barlines_meter_change():
    time_sigs = [
        {"offset": 0.0, "numerator": 4, "denominator": 4},
        {"offset": 8.0, "numerator": 3, "denominator": 4},
    ]
    barlines = compute_barlines(time_sigs, end_beat=14.0)
    assert barlines == [4.0, 8.0, 11.0, 14.0]


def test_groups_from_steps():
    steps = [
        {
            "offset": 0.0,
            "duration": 1.5,
            "durations": [1.5, 1.0],
            "pitches": [60, 48],
            "hands": ["right", "left"],
        }
    ]
    groups = groups_from_steps(steps)
    assert len(groups) == 1
    assert groups[0]["offset"] == 0.0
    assert groups[0]["duration"] == 1.5
    assert groups[0]["notes"] == [(60, "right"), (48, "left")]
