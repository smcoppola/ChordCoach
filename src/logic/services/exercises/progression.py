"""Chord progressions: several chords in order, each a step of its own."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List

from PySide6.QtCore import QTimer  # type: ignore

from logic.services.exercises.base import Exercise  # type: ignore


class Progression(Exercise):
    type = "progression"

    def __init__(self, trainer):
        super().__init__(trainer)
        self.steps: List[Dict] = []
        self.index = 0
        self.numerals: List[str] = []

    def setup(self, chord_data):
        """Sets up a chord progression exercise: multiple chords played in sequence."""
        prog_steps = chord_data.get("progression_steps", []) # type: ignore
        print(f"[PROG DEBUG] _setup_progression_target called. prog_steps count={len(prog_steps)}")
        if not prog_steps:
            # Fallback: treat as a regular chord step
            print(f"[PROG DEBUG] No progression_steps! Falling back to chord. chord_data keys={list(chord_data.keys())}")
            self._t._exercise_type = "chord"
            root_idx = chord_data.get("root_idx", 0)
            chord_type_name = chord_data.get("chord_type_name", "Major")
            intervals = chord_data.get("intervals", self._t.CHORD_TYPES.get(chord_type_name, {0, 4, 7}))
            self._t._setup_target(root_idx, chord_type_name, intervals, 4)
            return

        # Store the full progression
        self.steps = []
        self.numerals = []
        for step in prog_steps:
            c_type = str(step.get("chord_type_name", "Major")) # type: ignore
            intervals = self._t.CHORD_TYPES.get(c_type, {0, 4, 7})
            self.steps.append({
                "root_idx": int(step.get("root_idx", 0)), # type: ignore
                "chord_type_name": c_type,
                "intervals": intervals,
                "numeral": str(step.get("numeral", "")), # type: ignore
                "octave": int(step.get("octave", 4)), # type: ignore
            })
            self.numerals.append(str(step.get("numeral", ""))) # type: ignore

        self.index = 0
        self._t._required_hold_ms = 0
        self._t.lessonStateChanged.emit()

        # Build scrolling notes for the progression
        sn = []
        for i, step in enumerate(self.steps):
            root_idx = step["root_idx"]
            intervals = step["intervals"]
            octave = step["octave"]
            
            c_hand = self._t._current_hand
            if c_hand == "right":
                oct_clamped = max(4, min(5, octave))
            elif c_hand == "left":
                oct_clamped = max(2, min(3, octave))
            else:
                oct_clamped = octave
                
            base_pitch = (oct_clamped + 1) * 12 + root_idx
            pitches = sorted([(base_pitch + inv) for inv in intervals])
            fingers = self._t._calculate_fingerings(pitches, "right" if c_hand != "left" else "left")
            if not fingers or len(fingers) != len(pitches):
                fingers = [j + 1 for j in range(len(pitches))]
            
            for j, p in enumerate(pitches):
                sn.append({
                    "pitch": p,
                    "hand": "R" if c_hand in ("right", "both") else "L",
                    "finger": fingers[j],
                    "start_beat": float(i),
                    "duration_beats": 1.0
                })

        self._t._scrolling_notes = sn
        self._t.scrollingNotesChanged.emit()
        self._t._set_stepped_scroll_beat(0.0)
        
        # User-driven pacing (no metronome by default for progressions)
        self._t._scroll_bpm = 0
        self._t.scrollBpmChanged.emit()
        
        print(f"[PROG DEBUG] Built {len(self.steps)} progression steps, {len(sn)} scrolling notes")

        # Set up the first chord in the progression
        self.advance_chord()

    def advance_chord(self):
        """Sets up the current chord within a progression sequence."""
        print(f"[PROG DEBUG] _advance_progression_chord called. index={self.index}/{len(self.steps) if self.steps else 0}")
        if self.index >= len(self.steps):
            # Progression complete
            print(f"[PROG DEBUG] Progression complete (index >= len). Skipping.")
            return

        step = self.steps[self.index]
        root_idx = step["root_idx"]
        chord_type_name = step["chord_type_name"]
        intervals = step["intervals"]
        octave = step["octave"]
        numeral = step["numeral"]

        root_name = self._t.ROOT_NOTES[root_idx]
        self._t._target_chord_name = f"{root_name} {chord_type_name} ({numeral})" if numeral else f"{root_name} {chord_type_name}"
        self._t._review_chord = f"{root_name} {chord_type_name}"
        self._t._target_chord_type = chord_type_name

        # Clamp octave based on current hand assignment
        if self._t._current_hand == "right":
            octave = max(4, min(5, octave))
        elif self._t._current_hand == "left":
            octave = max(2, min(3, octave))
        base_pitch = (octave + 1) * 12 + root_idx
        self._t._target_pitches = sorted([(base_pitch + interval) for interval in intervals])

        hand_tag = "left" if self._t._current_hand == "left" else "right"
        self._t._target_hands = [hand_tag] * len(self._t._target_pitches)

        self._t._target_intervals = {(root_idx + interval) % 12 for interval in intervals}

        # Calculate formula text
        if len(intervals) <= 1:
            self._t._target_formula_text = ""
        else:
            sorted_intervals = sorted(list(intervals))
            steps = []
            for i in range(1, len(sorted_intervals)):
                diff = sorted_intervals[i] - sorted_intervals[i-1]
                steps.append(str(diff))
            self._t._target_formula_text = "Root + " + " + ".join(steps)

        # Reset per-chord state
        self._t._hold_progress = 0.0
        self._t._is_holding = False
        self._t._waiting_for_release = False
        self._t._required_hold_ms = 0
        self._t._hold_tick_timer.stop()
        self._t._prompt_time = self._t._now()
        self._t._wrong_notes_count = 0
        self._t._first_note_time = 0.0
        self._t._is_simultaneous = False

        print(f"[PROG DEBUG] _advance_progression_chord set target: name={self._t._target_chord_name} pitches={self._t._target_pitches} intervals={self._t._target_intervals}")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._t._target_chord_name})")
        self._t.targetChordChanged.emit(self._t._target_chord_name)
        print(f"ChordTrainer: Progression chord {self.index + 1}/{len(self.steps)}: {self._t._target_chord_name}")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting inputReady")
        self._t.inputReady.emit()

    def after_success(self):
        t = self._t
        self.index += 1
        if t._scroll_bpm == 0:
            t._set_stepped_scroll_beat(float(self.index))
        if self.index < len(self.steps):
            print("ChordTrainer: Advancing to next progression chord immediately...")
            self.advance_chord()
            return
        super().after_success()  # the whole progression is done
