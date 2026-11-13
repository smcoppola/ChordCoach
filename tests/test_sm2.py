"""The SM-2 algorithm and how the app grades reviews. Pure Python."""
import pytest

from logic.utils.sm2 import (
    INITIAL_EASE, MIN_EASE, ReviewState, quality_for_chord, quality_for_song, sm2_update,
)


def run(*grades):
    state = ReviewState()
    for q in grades:
        state = sm2_update(state, q)
    return state


def test_successful_reviews_space_out():
    intervals = []
    state = ReviewState()
    for _ in range(5):
        state = sm2_update(state, 4)
        intervals.append(state.interval_days)
    assert intervals[:2] == [1, 6]
    assert intervals == sorted(intervals) and intervals[-1] > 30


def test_grade_4_keeps_the_ease():
    assert run(4, 4, 4).ease == pytest.approx(INITIAL_EASE)


def test_grade_5_grows_faster_than_grade_3():
    assert run(5, 5, 5, 5).interval_days > run(3, 3, 3, 3).interval_days


def test_a_lapse_starts_over_tomorrow():
    state = run(5, 5, 5, 1)
    assert (state.repetitions, state.interval_days) == (0, 1)
    assert state.ease < INITIAL_EASE


def test_ease_has_a_floor():
    assert run(*[0] * 20).ease == pytest.approx(MIN_EASE)


def test_out_of_range_grades_are_clamped():
    assert sm2_update(ReviewState(), 9) == sm2_update(ReviewState(), 5)
    assert sm2_update(ReviewState(), -3) == sm2_update(ReviewState(), 0)


@pytest.mark.parametrize("success,latency,wrong,expected", [
    (False, 500, 0, 1),
    (True, 5000, 0, 3),   # slow: the trainer's struggle threshold
    (True, 800, 3, 3),    # several wrong notes on the way
    (True, 2000, 1, 4),
    (True, 900, 0, 5),
])
def test_quality_for_chord(success, latency, wrong, expected):
    assert quality_for_chord(success, latency, wrong) == expected


@pytest.mark.parametrize("mode,wrong,accuracy,expected", [
    ("self_paced", 0, 0, 5), ("self_paced", 2, 0, 4), ("self_paced", 5, 0, 3), ("self_paced", 9, 0, 2),
    ("rhythm", 0, 0.95, 5), ("rhythm", 0, 0.8, 4), ("rhythm", 0, 0.6, 3), ("rhythm", 0, 0.3, 2),
])
def test_quality_for_song(mode, wrong, accuracy, expected):
    assert quality_for_song(mode, wrong, accuracy) == expected
