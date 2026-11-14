"""
One handler per exercise type. ChordTrainerService keeps one of each and
dispatches to the one matching its current exercise type, in place of the
`if self._exercise_type == ...` chains it used to carry.
"""
from logic.services.exercises.base import Chord, Exercise  # type: ignore
from logic.services.exercises.chords import (  # type: ignore
    HandsTogether, Listen, SongApplication, SustainPedal, TheoryConcept,
)
from logic.services.exercises.pentascale import Pentascale  # type: ignore
from logic.services.exercises.progression import Progression  # type: ignore
from logic.services.exercises.steady_pulse import SteadyPulse  # type: ignore

HANDLERS = (Chord, HandsTogether, SustainPedal, Listen, TheoryConcept,
            SongApplication, Pentascale, Progression, SteadyPulse)


def make_exercises(trainer) -> dict:
    """{exercise type: handler} for one trainer."""
    return {cls.type: cls(trainer) for cls in HANDLERS}


__all__ = ["Exercise", "make_exercises", "HANDLERS"]
