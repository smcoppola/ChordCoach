import os
import pytest
from logic.services.music21_service import Music21Service

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))


def test_simplify_groups_meter_preservation(tmp_user_songs_dir):
    service = Music21Service()
    groups = [
        {"offset": 0.0, "duration": 1.0, "notes": [(60, "right"), (64, "right"), (67, "right"), (72, "right")]},
        {"offset": 1.0, "duration": 1.0, "notes": [(48, "left")]},
        {"offset": 2.0, "duration": 1.0, "notes": [(60, "right"), (64, "right")]},
    ]

    # Level 1 cap for RH notes is 2, LH is 1
    simplified = service._simplify_groups(groups, level=1)
    assert len(simplified[0]["notes"]) == 2

    # Score rebuild carries 3/4 meter
    time_sigs = [{"offset": 0.0, "numerator": 3, "denominator": 4}]
    score, key_name, key_sharps = service._build_score_from_groups(
        simplified, time_signatures=time_sigs
    )
    steps, barlines, extra_meta = service._extract_steps_from_score(score)

    assert extra_meta["time_signatures"] == time_sigs


def _sparse_block_chord_steps(service):
    """
    A two-handed block chord on every fourth beat and silence in between —
    the shape thinning notes out produces, and the one the rest padding
    distorts most. _build_score_from_groups fills each gap with a rest per
    hand, so the score comes back with a pitchless step between every chord.
    """
    chord = [(60, "right"), (64, "right"), (67, "right"),
             (36, "left"), (43, "left"), (48, "left")]
    groups = [{"offset": float(i * 4), "duration": 2.0, "notes": chord}
              for i in range(4)]

    score, _kn, _ks = service._build_score_from_groups(
        groups, time_signatures=[{"offset": 0.0, "numerator": 4, "denominator": 4}]
    )
    steps, _barlines, _meta = service._extract_steps_from_score(score)
    return steps


def test_gap_filling_rests_produce_pitchless_steps(tmp_user_songs_dir):
    """
    Pins the shape that stalled self-paced play. This is production output, not
    a synthetic edge case: every consumer of `steps` has to tolerate it, and
    ChordTrainerService drops them before they can become input targets.
    """
    service = Music21Service()
    steps = _sparse_block_chord_steps(service)

    silent = [s for s in steps if not s["pitches"]]
    assert silent, "the rest padding this fixture depends on is gone"
    assert all(s["rests"] for s in silent)


def test_difficulty_ignores_pitchless_steps(tmp_user_songs_dir):
    """
    Rests are engraving, not work for the hands. Counting them dragged
    avg_chord_size and the polyphony ratios down while splitting real onset
    gaps into shorter ones, so a grade partly measured how a piece was notated
    rather than how hard it is to play. This fixture — six-note block chords in
    both hands — swung two grades, 5 instead of 7.
    """
    service = Music21Service()
    steps = _sparse_block_chord_steps(service)
    played_only = [s for s in steps if s["pitches"]]
    assert len(played_only) < len(steps)

    assert service._score_difficulty(steps) == service._score_difficulty(played_only)
    # Pinned so a regression shows up as a grade, not just an equality.
    assert service._score_difficulty(steps) == 7
