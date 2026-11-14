"""
The base exercise: one chord, played and held.

Every exercise type is a subclass that overrides only where it behaves
differently. The trainer owns what all of them share — the current target,
held keys, hold timing, scroll position, signals — and each handler works
through it as `self._t`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    from logic.services.chord_trainer import ChordTrainerService


class Exercise:
    type = "chord"
    # Graded into the SM-2 review schedule.
    reviewable = True
    # False when the answer is given on screen and keys are not checked.
    keyboard_answers = True
    # Completion also needs the sustain pedal.
    needs_pedal = False
    # targetPitches is shown sorted (sequential drills keep their order).
    sorted_targets = True

    def __init__(self, trainer: "ChordTrainerService"):
        self._t = trainer

    def setup(self, chord_data):
        """Puts this exercise's target in front of the student."""
        t = self._t
        root_idx = chord_data.get("root_idx", 0)
        chord_type_name = chord_data.get("chord_type_name", "Major")
        if chord_type_name in ("N/A", "None", "Single", ""):
            intervals = chord_data.get("intervals", [0])
            chord_type_name = ""
        else:
            intervals = chord_data.get("intervals", t.CHORD_TYPES.get("Major", [0, 4, 7]))
        octave = chord_data.get("octave", 4)
        preview = chord_data.get("preview_chord", False)
        t._setup_target(root_idx, chord_type_name, intervals, octave, preview_chord=preview)

    def handle_raw_note(self, pitch: int, is_on: bool) -> bool:
        """Takes a note before any other processing. True if it was consumed."""
        return False

    def on_note_on(self, pitch: int):
        """Counts a note outside the chord against the attempt."""
        t = self._t
        if t._target_intervals and (pitch % 12) not in t._target_intervals:
            t._wrong_notes_count += 1

    def check_input(self):
        self._t._check_chord()

    def mistake_active(self) -> bool:
        """Any held key outside the chord, in any octave."""
        t = self._t
        return any((p % 12) not in t._target_intervals for p in t._active_pitches)

    def on_keys_released(self):
        """All keys up after a completed step that waits for release."""
        QTimer.singleShot(700, self._t._next_chord)

    def after_success(self):
        """Moves on once the target is played. Not waiting for release keeps it fluid."""
        t = self._t
        t._waiting_for_release = False
        QTimer.singleShot(300, t._next_chord)

    def stat_key(self) -> str:
        return self._t._target_chord_name

    def success_label(self) -> str:
        return self._t._target_chord_name

    def on_metronome_tick(self, beat_count: int):
        pass

    def on_pedal(self, is_down: bool):
        pass


class Chord(Exercise):
    type = "chord"
