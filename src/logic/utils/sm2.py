"""
SM-2 spaced repetition (SuperMemo 2, Woźniak 1990).

Each review is graded 0–5. A grade of 3 or more is a successful recall: the
interval grows (1 day, then 6, then the previous interval times the ease
factor). Below 3 is a lapse: repetitions restart and the item is due again
tomorrow. Every grade nudges the ease factor, which never drops below 1.3.

The app grades from what it already measures — see quality_for_chord and
quality_for_song — rather than asking the student to rate themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

INITIAL_EASE = 2.5
MIN_EASE = 1.3

# Below this a successful chord counts as fast (grade 5).
FAST_CHORD_MS = 1500.0
# The trainer's own definition of a struggle (ChordTrainerService._complete_chord).
STRUGGLE_LATENCY_MS = 4000.0
STRUGGLE_WRONG_NOTES = 2


@dataclass(frozen=True)
class ReviewState:
    ease: float = INITIAL_EASE
    interval_days: int = 0
    repetitions: int = 0


def sm2_update(state: ReviewState, quality: int) -> ReviewState:
    """The state after one review graded `quality` (0–5)."""
    q = max(0, min(5, int(quality)))
    if q >= 3:
        if state.repetitions == 0:
            interval = 1
        elif state.repetitions == 1:
            interval = 6
        else:
            interval = max(1, round(state.interval_days * state.ease))
        repetitions = state.repetitions + 1
    else:
        interval = 1
        repetitions = 0
    ease = state.ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
    return ReviewState(ease=max(MIN_EASE, ease), interval_days=interval, repetitions=repetitions)


def quality_for_chord(success: bool, latency_ms: float = 0.0, wrong_notes: int = 0) -> int:
    """
    1  wrong chord
    3  right, but a struggle (slow or several wrong notes on the way)
    4  right
    5  right, quickly, with no wrong notes
    """
    if not success:
        return 1
    if latency_ms > STRUGGLE_LATENCY_MS or wrong_notes > STRUGGLE_WRONG_NOTES:
        return 3
    if latency_ms < FAST_CHORD_MS and wrong_notes == 0:
        return 5
    return 4


def quality_for_song(mode: str, wrong_notes: int = 0, accuracy: float = 0.0) -> int:
    """
    A completed play-through. Self-paced play is graded on wrong notes; rhythm
    play on timing accuracy (0–1).
    """
    if mode == "rhythm":
        if accuracy >= 0.9:
            return 5
        if accuracy >= 0.75:
            return 4
        if accuracy >= 0.5:
            return 3
        return 2
    if wrong_notes == 0:
        return 5
    if wrong_notes <= 2:
        return 4
    if wrong_notes <= 5:
        return 3
    return 2
