"""
The local lesson sequencer: music helpers, pacing rules, and coverage of every
milestone in the shipped curriculum. Pure Python — no Qt.
"""
import json
from pathlib import Path

import pytest

from logic.services.lesson_sequencer import (
    SONG_UNITS, LessonSequencer, build_pool, exercise_key, numeral_for,
    parse_chord, parse_key, resolve_numeral, simplify,
)

TRACKS = json.loads(
    (Path(__file__).resolve().parent.parent / "src" / "resources" / "curriculum_tracks.json")
    .read_text(encoding="utf-8")
)
ALL_MILESTONES = [(track, m) for track, ms in TRACKS.items() for m in ms]


def block_for(track, meta, step_count=10):
    """A plan block shaped like CurriculumService.plan_session's."""
    return {
        "track": track,
        "milestone_id": meta["id"],
        "milestone_title": meta["title"],
        "milestone_description": meta["description"],
        "exercise_types": meta["exercise_types"],
        "target_keys": meta["target_keys"],
        "target_chords": meta["target_chords"],
        "step_count": step_count,
    }


def sequencer_for(*milestone_ids, seed=1, step_count=10, library=None, **kw):
    blocks, hints = [], {}
    for track, meta in ALL_MILESTONES:
        if meta["id"] in milestone_ids:
            blocks.append(block_for(track, meta, step_count))
            hints[meta["id"]] = meta
    blocks.sort(key=lambda b: milestone_ids.index(b["milestone_id"]))
    return LessonSequencer({"blocks": blocks}, hints=hints, library=library, seed=seed, **kw)


def run(seq, results=None, limit=500):
    """Drains a sequencer. `results(ex)` gives the result to report for each exercise."""
    out, result = [], None
    for _ in range(limit):
        ex = seq.next_exercise(result)
        if ex is None:
            return out
        out.append(ex)
        result = results(ex) if results else {"struggled": False}
    raise AssertionError("sequencer did not finish")


# ── Music helpers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("C Major", (0, "Major")), ("A Minor", (9, "Minor")), ("G Dominant 7th", (7, "Dominant 7th")),
    ("Eb Major 7th", (3, "Major 7th")), ("F#", (6, "Major")),
])
def test_parse_chord(name, expected):
    assert parse_chord(name) == expected


def test_parse_key():
    assert parse_key("C") == (0, "major")
    assert parse_key("Am") == (9, "minor")
    assert parse_key("F#m") == (6, "minor")


@pytest.mark.parametrize("numeral,key,mode,expected", [
    ("I", 0, "major", (0, "Major")), ("V", 0, "major", (7, "Major")),
    ("vi", 0, "major", (9, "Minor")), ("IV", 7, "major", (0, "Major")),
    ("vii°", 0, "major", (11, "Diminished")),
    ("5", 0, "major", (7, "Major")), ("6", 7, "major", (4, "Minor")),
    ("i", 9, "minor", (9, "Minor")), ("VI", 9, "minor", (5, "Major")),
    ("III", 9, "minor", (0, "Major")), ("VII", 9, "minor", (7, "Major")),
])
def test_resolve_numeral(numeral, key, mode, expected):
    assert resolve_numeral(numeral, key, mode) == expected


def test_numeral_for():
    assert numeral_for(7, "Major", 0) == "V"
    assert numeral_for(9, "Minor", 0) == "vi"
    assert numeral_for(5, "Major", 9, "minor") == "VI"
    assert numeral_for(1, "Major", 0) == ""


# ── Every milestone in the curriculum ───────────────────────────────────────

@pytest.mark.parametrize("track,meta", ALL_MILESTONES, ids=[m["id"] for _, m in ALL_MILESTONES])
def test_every_milestone_yields_exercises(track, meta):
    seq = LessonSequencer({"blocks": [block_for(track, meta)]}, hints={meta["id"]: meta}, seed=3)
    exercises = run(seq)
    assert exercises, f"{meta['id']} produced nothing"
    playable = [e for e in exercises if e["exercise_type"] != "theory_concept"]
    assert playable, f"{meta['id']} produced only cards"
    for ex in exercises:
        assert ex["track"] == track and ex["milestone_id"] == meta["id"]
        assert ex["exercise_name"]


def test_concept_milestones_open_with_a_card():
    exercises = run(sequencer_for("major_formula"))
    assert exercises[0]["exercise_type"] == "theory_concept"
    assert "4 half steps" in exercises[0]["concept_body"]
    assert {e["chord_type_name"] for e in exercises[1:]} == {"Major"}
    # The card does not use up the block's exercises.
    assert len(exercises) == 1 + 10


def test_progression_hints_resolve_to_chords():
    drills, _ = build_pool({"exercise_types": ["progression"], "target_keys": ["C"],
                            "progressions": [{"numerals": ["I", "V", "vi", "IV"]}]})
    steps = drills[0]["progression_steps"]
    assert [(s["root_idx"], s["chord_type_name"]) for s in steps] == \
        [(0, "Major"), (7, "Major"), (9, "Minor"), (5, "Major")]
    assert drills[0]["exercise_name"] == "I–V–vi–IV in C"


def test_minor_progression_hint():
    exercises = run(sequencer_for("minor_progressions", step_count=1))
    steps = exercises[0]["progression_steps"]
    assert [(s["root_idx"], s["chord_type_name"]) for s in steps] == \
        [(9, "Minor"), (5, "Major"), (0, "Major"), (7, "Major")]


def test_inversion_hint_varies_voicings():
    drills, _ = build_pool({"exercise_types": ["chord"], "target_chords": ["C Major"],
                            "inversions": [0, 1, 2]})
    assert [d["inversion"] for d in drills] == [0, 1, 2]
    assert drills[1]["exercise_name"] == "C Major — 1st inversion"


def test_left_hand_bass_notes():
    drills, _ = build_pool({"exercise_types": ["chord"], "target_keys": ["C", "F"],
                            "hand": "left", "single_notes": True})
    assert {(d["root_idx"], d["chord_type_name"], d["hand"], d["octave"]) for d in drills} == \
        {(0, "Single", "left", 3), (5, "Single", "left", 3)}


def test_listen_drills_only_ask_major_or_minor():
    drills, _ = build_pool({"exercise_types": ["listen"],
                            "target_chords": ["C Major", "G Dominant 7th", "A Minor"]})
    assert {d["target_quality"] for d in drills} == {"Major", "Minor"}


# ── Pacing ──────────────────────────────────────────────────────────────────

def test_same_seed_same_lesson():
    a = run(sequencer_for("rh_major_triads", "major_minor_recognition", seed=7))
    b = run(sequencer_for("rh_major_triads", "major_minor_recognition", seed=7))
    assert a == b


def test_blocks_run_in_order_with_their_counts():
    exercises = run(sequencer_for("rh_major_triads", "major_minor_recognition", step_count=6))
    assert [e["milestone_id"] for e in exercises] == \
        ["rh_major_triads"] * 6 + ["major_minor_recognition"] * 6


def test_dev_mode_shortens_blocks():
    exercises = run(sequencer_for("rh_major_triads", "major_minor_recognition", dev_mode=True))
    assert len(exercises) == 6


def test_no_exercise_twice_in_a_row_without_a_struggle():
    for seed in range(20):
        exercises = run(sequencer_for("rh_major_triads", "inversions_intro", "rh_pentascale_c",
                                      seed=seed, step_count=20))
        for prev, cur in zip(exercises, exercises[1:]):
            assert exercise_key(prev) != exercise_key(cur), f"seed {seed}: repeated {cur['exercise_name']}"


def test_struggle_repeats_once_then_simplifies_then_moves_on():
    seq = sequencer_for("inversions_intro", seed=2, step_count=30)
    first = seq.next_exercise()
    while first["inversion"] == 0:  # find an inverted voicing to simplify
        first = seq.next_exercise({"struggled": False})

    repeat = seq.next_exercise({"struggled": True})
    assert repeat == first

    simpler = seq.next_exercise({"struggled": True})
    assert simpler["inversion"] == 0
    assert simpler["root_idx"] == first["root_idx"]
    assert " — " not in simpler["exercise_name"]

    after = seq.next_exercise({"struggled": True})
    assert exercise_key(after) != exercise_key(simpler)
    assert seq.struggled == [first["exercise_name"]] * 2 + [simpler["exercise_name"]]


def test_simplify():
    assert simplify({"exercise_type": "pentascale", "exercise_name": "C Major Pentascale (descending)",
                     "direction": "descending", "bpm": 80})["direction"] == "ascending"
    ht = simplify({"exercise_type": "hands_together", "exercise_name": "C Major with bass",
                   "hand": "both", "hold_ms": 0})
    assert (ht["exercise_type"], ht["hand"], ht["exercise_name"]) == ("chord", "right", "C Major")


def test_songs_close_their_block():
    library = [{"id": "user::mine", "title": "My Song"}]
    exercises = run(sequencer_for("first_song", step_count=8, library=library))
    types = [e["exercise_type"] for e in exercises]
    assert types == ["progression"] * (8 - SONG_UNITS) + ["song_application"]
    assert exercises[-1]["piece_name"] == "essenFolksong/erk5.abc::7"


def test_a_song_that_will_not_load_is_skipped_and_refunded():
    library = [{"id": "user::mine", "title": "My Song"}]
    seq = sequencer_for("song_breakdown_intro", step_count=SONG_UNITS, library=library)
    first = seq.next_exercise()
    second = seq.next_exercise({"failed": True})
    assert second["exercise_type"] == "song_application"
    assert second["piece_name"] != first["piece_name"]
    assert seq.next_exercise({"struggled": False}) is None


def test_library_songs_follow_suggested_pieces():
    library = [{"id": "user::mine", "title": "My Song"}]
    exercises = run(sequencer_for("dream_song_prep", step_count=SONG_UNITS * 4, library=library))
    assert [e["piece_name"] for e in exercises][-1] == "user::mine"
    assert exercises[-1]["exercise_name"] == "My Song"


def test_fixed_list():
    items = [{"exercise_type": "chord", "exercise_name": f"x{i}", "root_idx": i} for i in range(3)]
    seq = LessonSequencer.from_exercises(items)
    assert [e["exercise_name"] for e in run(seq)] == ["x0", "x1", "x2"]


def test_empty_plan_ends_at_once():
    assert LessonSequencer({"blocks": []}).next_exercise() is None
