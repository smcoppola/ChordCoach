"""
Per-note editing of imported songs: beat, duration and hand.

The editor round-trips a song through a flat note list, so the invariant that
matters most is that everything it does *not* show — spelling, finger, velocity,
articulations, rests — survives the trip untouched. These tests pin that, plus
the grid snapping and the derived state (quantized_groups, barlines) that
difficulty levels and the renderer read afterwards.
"""

import json

import pytest

from logic.services.music21_service import Music21Service
from logic.utils.step_schema import groups_from_steps

GRID = 0.25


def _record(song_id="user::demo-1"):
    """A two-step song with a chord, a rest, and full per-note metadata."""
    return {
        "schema_version": 2,
        "id": song_id,
        "title": "Demo",
        "artist": "Tester",
        "level": "Grade 2",
        "key": "C Major",
        "key_sharps": 0,
        "bpm": 100.0,
        "time_signatures": [{"offset": 0.0, "numerator": 4, "denominator": 4}],
        "tempo_map": [{"offset": 0.0, "bpm": 100.0}],
        "pedal_events": [],
        "dynamics": [],
        "source_type": "midi",
        "source_file": "demo.mid",
        "track_hands_reliable": True,
        "pristine_groups": [
            {"offset": 0.0, "duration": 1.0, "notes": [[60, "right"], [64, "right"]]},
            {"offset": 1.0, "duration": 2.0, "notes": [[48, "left"]]},
        ],
        "hand_algo": 2,
        "hand_mode": "auto",
        "barlines": [4.0, 8.0],
        "steps": [
            {
                "offset": 0.0,
                "pitches": [60, 64],
                "spellings": [["C", 0], ["E", 0]],
                "hands": ["right", "right"],
                "fingers": [1, 3],
                "durations": [1.0, 1.0],
                "duration": 1.0,
                "ties": [None, "start"],
                "beams": ["start", None],
                "tuplets": [None, None],
                "articulations": [["staccato"], []],
                "velocities": [80, 72],
                "rests": [{"duration": 1.0, "hand": "left"}],
            },
            {
                "offset": 1.0,
                "pitches": [48],
                "spellings": [["C", 0]],
                "hands": ["left"],
                "fingers": [5],
                "durations": [2.0],
                "duration": 2.0,
                "ties": [None],
                "beams": [None],
                "tuplets": [None],
                "articulations": [[]],
                "velocities": [64],
                "rests": [],
            },
        ],
        "quantized_groups": [
            {"offset": 0.0, "duration": 1.0, "notes": [[60, "right"], [64, "right"]]},
            {"offset": 1.0, "duration": 2.0, "notes": [[48, "left"]]},
        ],
        "imported_at": "2026-08-01 12:00:00",
    }


@pytest.fixture
def service(tmp_user_songs_dir):
    return Music21Service()


@pytest.fixture
def song(service, tmp_user_songs_dir):
    """Writes the demo record to the isolated songs dir and returns its id."""
    rec = _record()
    service._save_user_song_record(rec)
    return rec["id"]


def _stored(service, song_id):
    with open(service._user_song_path(song_id)) as f:
        return json.load(f)


def _find(rows, pitch, beat=None):
    for r in rows:
        if r["pitch"] == pitch and (beat is None or r["beat"] == beat):
            return r
    raise AssertionError(f"no row for pitch {pitch} at beat {beat}")


# --- Reading ---------------------------------------------------------------

def test_notes_are_flattened_one_row_per_note(service, song):
    rows = service.get_user_song_notes(song)

    assert [r["pitch"] for r in rows] == [60, 64, 48]
    assert [r["beat"] for r in rows] == [0.0, 0.0, 1.0]
    assert [r["hand"] for r in rows] == ["right", "right", "left"]
    assert _find(rows, 48)["duration"] == 2.0


def test_rows_carry_display_name_and_measure(service, song):
    rows = service.get_user_song_notes(song)

    assert _find(rows, 60)["name"] == "C4"
    assert _find(rows, 48)["name"] == "C3"
    # barlines are [4.0, 8.0]; everything here is in the first measure
    assert all(r["measure"] == 1 for r in rows)


def test_measure_number_follows_barlines(service, song):
    rows = service.get_user_song_notes(song)
    row = _find(rows, 48)
    row["beat"] = 5.0
    assert service.save_user_song_notes(song, rows) == ""

    moved = _find(service.get_user_song_notes(song), 48)
    assert moved["measure"] == 2


def test_missing_song_reads_as_empty(service):
    assert service.get_user_song_notes("user::nope-0") == []


# --- The round trip must not lose anything ---------------------------------

def test_unedited_round_trip_is_lossless(service, song):
    before = _stored(service, song)["steps"]
    rows = service.get_user_song_notes(song)

    assert service.save_user_song_notes(song, rows) == ""

    after = _stored(service, song)["steps"]
    assert after == before


def test_untouched_attributes_survive_an_edit(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 64)["duration"] = 0.5

    assert service.save_user_song_notes(song, rows) == ""

    step = _stored(service, song)["steps"][0]
    i = step["pitches"].index(64)
    assert step["spellings"][i] == ["E", 0]
    assert step["fingers"][i] == 3
    assert step["velocities"][i] == 72
    assert step["articulations"][i] == []


def test_rests_are_preserved(service, song):
    rows = service.get_user_song_notes(song)
    assert service.save_user_song_notes(song, rows) == ""

    assert _stored(service, song)["steps"][0]["rests"] == [{"duration": 1.0, "hand": "left"}]


def test_rests_outlive_the_notes_that_shared_their_offset(service, song):
    """A silence stays where the arrangement put it even if every note moves off it."""
    rows = service.get_user_song_notes(song)
    for r in rows:
        if r["beat"] == 0.0:
            r["beat"] = 3.0

    assert service.save_user_song_notes(song, rows) == ""

    steps = {s["offset"]: s for s in _stored(service, song)["steps"]}
    assert steps[0.0]["pitches"] == []
    assert steps[0.0]["rests"] == [{"duration": 1.0, "hand": "left"}]


# --- Beat ------------------------------------------------------------------

def test_beat_change_moves_a_note_between_steps(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 64)["beat"] = 1.0

    assert service.save_user_song_notes(song, rows) == ""

    steps = {s["offset"]: s for s in _stored(service, song)["steps"]}
    assert steps[0.0]["pitches"] == [60]
    assert steps[1.0]["pitches"] == [48, 64]


def test_beat_change_creates_a_step_at_a_new_offset(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 60)["beat"] = 7.5

    assert service.save_user_song_notes(song, rows) == ""

    steps = {s["offset"]: s for s in _stored(service, song)["steps"]}
    assert 7.5 in steps
    assert steps[7.5]["pitches"] == [60]
    assert steps[7.5]["durations"] == [1.0]


def test_a_step_emptied_of_notes_and_rests_disappears(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 48)["beat"] = 0.0  # step at 1.0 has no rests to hold it open

    assert service.save_user_song_notes(song, rows) == ""

    assert [s["offset"] for s in _stored(service, song)["steps"]] == [0.0]


# --- Duration --------------------------------------------------------------

def test_duration_change_updates_the_note_and_the_step_maximum(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 60)["duration"] = 4.0

    assert service.save_user_song_notes(song, rows) == ""

    step = _stored(service, song)["steps"][0]
    assert step["durations"][step["pitches"].index(60)] == 4.0
    assert step["duration"] == 4.0


def test_step_duration_drops_when_the_longest_note_shortens(service, song):
    rows = service.get_user_song_notes(song)
    for r in rows:
        if r["beat"] == 0.0:
            r["duration"] = 0.5

    assert service.save_user_song_notes(song, rows) == ""

    assert _stored(service, song)["steps"][0]["duration"] == 0.5


# --- Hand ------------------------------------------------------------------

def test_hand_change_updates_the_step_and_flips_hand_mode_to_manual(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 64)["hand"] = "left"

    assert service.save_user_song_notes(song, rows) == ""

    stored = _stored(service, song)
    step = stored["steps"][0]
    assert step["hands"][step["pitches"].index(64)] == "left"
    assert stored["hand_mode"] == "manual"


def test_hand_mode_is_left_alone_when_no_hand_changed(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 60)["duration"] = 2.0

    assert service.save_user_song_notes(song, rows) == ""

    assert _stored(service, song)["hand_mode"] == "auto"


def test_finger_numbers_survive_a_hand_change(service, song):
    """1-5 means thumb-to-pinky in both hands, so the number stays correct."""
    rows = service.get_user_song_notes(song)
    _find(rows, 64)["hand"] = "left"

    assert service.save_user_song_notes(song, rows) == ""

    step = _stored(service, song)["steps"][0]
    assert step["fingers"][step["pitches"].index(64)] == 3


def test_manual_mode_is_not_re_inferred(service):
    """
    The regression that would silently revert every hand edit.

    "auto" restores hands wholesale from pristine_groups whenever the tracks
    were reliable, and that runs on every level regeneration.
    """
    record = _record()
    groups = [{"offset": 0.0, "duration": 1.0, "notes": [(60, "left"), (64, "right")]}]

    service._apply_hand_mode(groups, "manual", record=record)
    assert groups[0]["notes"] == [(60, "left"), (64, "right")]

    service._apply_hand_mode(groups, "auto", record=record)
    assert groups[0]["notes"] == [(60, "right"), (64, "right")]


def test_set_user_song_hand_mode_accepts_manual(service, song):
    service.set_user_song_hand_mode(song, "manual")
    assert _stored(service, song)["hand_mode"] == "manual"


# --- Grid snapping ---------------------------------------------------------

@pytest.mark.parametrize("raw,snapped", [
    (0.3, 0.25), (0.4, 0.5), (1.13, 1.25), (2.0, 2.0), (-3.0, 0.0),
])
def test_beats_snap_to_the_sixteenth_grid(service, song, raw, snapped):
    rows = service.get_user_song_notes(song)
    _find(rows, 48)["beat"] = raw

    assert service.save_user_song_notes(song, rows) == ""

    assert snapped in [s["offset"] for s in _stored(service, song)["steps"]]


@pytest.mark.parametrize("raw,snapped", [
    (0.3, 0.25), (1.13, 1.25), (0.01, GRID), (0.0, GRID), (-5.0, GRID),
])
def test_durations_snap_and_never_fall_below_one_grid_unit(service, song, raw, snapped):
    rows = service.get_user_song_notes(song)
    _find(rows, 48)["duration"] = raw

    assert service.save_user_song_notes(song, rows) == ""

    step = next(s for s in _stored(service, song)["steps"] if s["offset"] == 1.0)
    assert step["durations"][0] == snapped


def test_malformed_values_fall_back_to_the_floor_instead_of_crashing(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 48)["beat"] = "nonsense"
    _find(rows, 48)["duration"] = None

    assert service.save_user_song_notes(song, rows) == ""

    steps = {s["offset"]: s for s in _stored(service, song)["steps"]}
    assert list(steps) == [0.0]                      # beat fell back to 0.0
    assert steps[0.0]["pitches"] == [48, 60, 64]
    assert steps[0.0]["durations"] == [GRID, 1.0, 1.0]  # duration fell back to one grid unit


# --- Notes that move lose their engraving relationships --------------------

def test_moving_a_note_clears_its_tie_beam_and_tuplet(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 64)["beat"] = 2.0

    assert service.save_user_song_notes(song, rows) == ""

    step = next(s for s in _stored(service, song)["steps"] if s["offset"] == 2.0)
    assert step["ties"] == [None]
    assert step["beams"] == [None]
    assert step["tuplets"] == [None]


def test_an_unmoved_note_keeps_its_tie_and_beam(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 48)["hand"] = "right"  # edit elsewhere in the song

    assert service.save_user_song_notes(song, rows) == ""

    step = _stored(service, song)["steps"][0]
    i = step["pitches"].index(64)
    assert step["ties"][i] == "start"
    assert step["beams"][step["pitches"].index(60)] == "start"


# --- Derived state the rest of the app reads -------------------------------

def test_quantized_groups_are_regenerated_from_the_edited_steps(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 64)["beat"] = 3.0

    assert service.save_user_song_notes(song, rows) == ""

    stored = _stored(service, song)
    expected = groups_from_steps(stored["steps"])
    actual = stored["quantized_groups"]
    assert [g["offset"] for g in actual] == [g["offset"] for g in expected]
    assert [[list(n) for n in g["notes"]] for g in actual] == \
           [[list(n) for n in g["notes"]] for g in expected]


def test_barlines_are_recomputed_for_the_new_end_beat(service, song):
    rows = service.get_user_song_notes(song)
    _find(rows, 48)["beat"] = 12.0

    assert service.save_user_song_notes(song, rows) == ""

    # 4/4, so a barline every 4 beats out past the moved note
    assert _stored(service, song)["barlines"] == [4.0, 8.0, 12.0]


def test_saving_invalidates_the_level_cache(service, song):
    service._level_cache[song] = {"steps": []}
    service._level_cache[song + "::L2"] = {"steps": []}

    assert service.save_user_song_notes(song, service.get_user_song_notes(song)) == ""

    assert song not in service._level_cache
    assert song + "::L2" not in service._level_cache


# --- Refusals --------------------------------------------------------------

def test_a_short_note_list_is_refused_rather_than_dropping_notes(service, song):
    """Editing is modify-only, so a count mismatch means the list is not ours."""
    rows = service.get_user_song_notes(song)
    before = _stored(service, song)["steps"]

    msg = service.save_user_song_notes(song, rows[:1])

    assert "3 notes expected" in msg
    assert _stored(service, song)["steps"] == before


def test_an_empty_note_list_is_refused(service, song):
    before = _stored(service, song)["steps"]

    assert service.save_user_song_notes(song, []) != ""

    assert _stored(service, song)["steps"] == before


def test_duplicate_rows_do_not_duplicate_notes(service, song):
    rows = service.get_user_song_notes(song)

    msg = service.save_user_song_notes(song, rows + rows)

    assert msg == ""
    stored = _stored(service, song)
    assert sum(len(s["pitches"]) for s in stored["steps"]) == 3


def test_editing_the_song_in_play_is_refused(service, song):
    class _Trainer:
        isActive = True
        _song_id = song

    service.set_chord_trainer(_Trainer())
    before = _stored(service, song)["steps"]

    msg = service.save_user_song_notes(song, service.get_user_song_notes(song))

    assert "Stop practising" in msg
    assert _stored(service, song)["steps"] == before


def test_a_different_song_in_play_does_not_block_editing(service, song):
    class _Trainer:
        isActive = True
        _song_id = "user::other-9"

    service.set_chord_trainer(_Trainer())

    assert service.save_user_song_notes(song, service.get_user_song_notes(song)) == ""


def test_difficulty_level_suffix_resolves_to_the_base_song(service, song):
    rows = service.get_user_song_notes(song + "::L2")
    assert len(rows) == 3
    assert service.save_user_song_notes(song + "::L2", rows) == ""
