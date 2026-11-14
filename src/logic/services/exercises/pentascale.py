"""Five-finger scales, one note at a time."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List

from PySide6.QtCore import QTimer  # type: ignore

from logic.services.exercises.base import Exercise  # type: ignore


class Pentascale(Exercise):
    type = "pentascale"
    reviewable = False
    sorted_targets = False

    def __init__(self, trainer):
        super().__init__(trainer)
        self.sequence: List[int] = []  # exact MIDI pitches of the five notes
        self.index = 0
        self.fingers: List[int] = []
        self.scale_name = ""

    def setup(self, chord_data):
        """Sets up a pentascale exercise: 5 sequential single-note targets."""
        root_idx = int(chord_data.get("root_idx", 0)) # type: ignore
        scale_type = str(chord_data.get("scale_type", "Major")) # type: ignore
        direction = str(chord_data.get("direction", "ascending")) # type: ignore
        octave = int(chord_data.get("octave", 4)) # type: ignore

        pattern = self._t.PENTASCALE_PATTERNS.get(scale_type, self._t.PENTASCALE_PATTERNS["Major"])
        # Clamp octave based on current hand assignment
        if self._t._current_hand == "right":
            octave = max(4, min(5, octave))
        elif self._t._current_hand == "left":
            octave = max(2, min(3, octave))
        base_pitch = (octave + 1) * 12 + root_idx

        # Generate the 5-note sequence as exact MIDI pitches
        sequence = [base_pitch + interval for interval in pattern]
        if direction == "descending":
            sequence = list(reversed(sequence))

        # Set target to the first note in the sequence
        self.scale_name = f"{self._t.ROOT_NOTES[root_idx % 12]} {scale_type}"
        self._t._target_chord_name = self.scale_name
        self._t._target_chord_type = "Pentascale"
        self._t._target_pitches = [sequence[0]]
        self._t._target_hands = [self._t._current_hand]
        
        # Calculate full fingering sequence for the 5-note pentascale
        full_fingers = self._t._calculate_fingerings(sequence if direction == "ascending" else list(reversed(sequence)), self._t._current_hand)
        if direction == "descending":
            full_fingers = list(reversed(full_fingers))
        self.fingers = full_fingers
        self._t._target_fingers = full_fingers  # Show all 5 fingers at start
        self._t.targetFingersChanged.emit()
        self._t._hold_progress = 0.0
        self._t._is_holding = False
        self._t._waiting_for_release = False
        self._t._hold_tick_timer.stop()
        self._t._prompt_time = time.time()
        self._t._wrong_notes_count = 0
        self._t._first_note_time = 0.0
        self._t._is_simultaneous = False

        # Handle metronome via service
        bpm = int(chord_data.get("bpm", 0))
        if bpm > 0 and self._t.metronome:
            if self._t._ai_is_currently_speaking or self._t.isPausedForSpeech:
                self._t.metronome.defer_start(bpm)
            else:
                self._t.metronome.start(bpm)
        elif self._t.metronome:
            self._t.metronome.stop()
            print("ChordTrainer: Free-play pentascale mode (no metronome)")

        # Set target to the first note in the sequence
        self._t._target_chord_name = self.scale_name
        self._t._target_chord_type = "Pentascale"

        # Display the note names in the correct ascending/descending order
        note_names = [self._t.ROOT_NOTES[(root_idx + i) % 12] for i in pattern]
        if direction == "descending":
            note_names = list(reversed(note_names))

        self._t._target_formula_text = f"{direction.capitalize()}: {' → '.join(note_names)}"
        self._t._target_pitches = sequence  # Show full sequence for QML visualization
        self._t._target_hands = [self._t._current_hand] * len(sequence)
        # For validation: match the exact MIDI pitch (not octave-agnostic)
        current_pitch = sequence[0]
        self._t._target_intervals = {current_pitch % 12}

        self.sequence = sequence
        self.index = 0
        
        # Build scrolling notes
        sn = []
        for i, p in enumerate(sequence):
            sn.append({
                "pitch": p,
                "start_beat": i,
                "duration_beats": 1,
                "finger": self.fingers[i],
                "hand": "R" if self._t._current_hand == "right" else "L"
            })
        self._t._scrolling_notes = sn
        self._t.scrollingNotesChanged.emit()
        self._t._scroll_bpm = bpm
        self._t.scrollBpmChanged.emit()
        self._t._scroll_beat = 0.0 if bpm == 0 else (self._t.metronome.currentBeatPosition if self._t.metronome else 0.0)
        self._t.scrollBeatChanged.emit(self._t._scroll_beat)
        self._t._emit_scroll_anchor(self._t._scroll_beat, bpm / 60.0, active=bpm > 0, snap=True)
        
        self._t.lessonStateChanged.emit()
        self._t.targetChordChanged.emit(self._t._target_chord_name)
        self._t.pentascaleNotesChanged.emit()
        self._t.currentNoteIndexChanged.emit()
        print(f"ChordTrainer: Pentascale target: {self.scale_name} ({direction}), notes: {sequence}")

    def check_input(self):
        """Validates single-note input for pentascale exercises."""
        # Wait until the lead-in is complete if we are running a metronome
        if self._t.isPausedForSpeech or (self._t.metronome and self._t.metronome.has_deferred):
            return

        if self._t.metronome and self._t.metronome.is_in_lead_in:
            # Strictly ignore input during lead-in
            return

        if not self.sequence or self.index >= len(self.sequence):
            return

        target_pitch = self.sequence[self.index]

        # Check if the target note is among the currently held keys (legato-friendly)
        # This allows the player to hold the previous note while pressing the next
        if target_pitch in self._t._active_pitches:
            # Correct note! Advance to the next note in the sequence
            print(f"ChordTrainer: Pentascale note {self.index + 1}/5 correct: {self._t.ROOT_NOTES[target_pitch % 12]}")

            # Calculate timing feedback if metronome is active
            feedback_text = ""
            timing_offset = 0.0
            if self._t.metronome and self._t.metronome.isRunning:
                timing_offset = self._t.metronome.get_timing_offset_ms(self.index)
                
                if timing_offset < -150:
                    feedback_text = "Fast"
                elif timing_offset > 150:
                    feedback_text = "Slow"
                else:
                    feedback_text = "Perfect!"

                print(f"ChordTrainer: Timing for note {self.index}: diff={timing_offset:.0f}ms -> {feedback_text}")

            self._t.pentascaleNoteHit.emit(self.index, feedback_text)

            # Record success for this individual note
            note_name = f"{self._t.ROOT_NOTES[target_pitch % 12]} (Pentascale)"
            latency_ms = (time.time() - self._t._prompt_time) * 1000.0
            self._t.db.record_chord_attempt(note_name, True, latency_ms, 0, False, timing_offset)

            self.index += 1
            self._t.currentNoteIndexChanged.emit()
            if self._t._scroll_bpm == 0:
                self._t._set_stepped_scroll_beat(float(self.index))

            if self.index >= len(self.sequence):
                # All 5 notes played correctly — complete the step
                # Delay slightly so the final dot has time to turn green in the UI
                if self._t.metronome:
                    self._t.metronome.stop()
                QTimer.singleShot(600, self._t._complete_chord)
            else:
                # Update target intervals to next note (no release wait — allows legato)
                next_pitch = self.sequence[self.index]
                self._t._target_intervals = {next_pitch % 12}
                
                hand_tag = "left" if self._t._current_hand == "left" else "right"
                self._t._target_pitches = [next_pitch]
                self._t._target_fingers = [self.fingers[self.index]]
                self._t._current_hand = hand_tag # Standard hand from exercise
                self._t._target_hands = [hand_tag]
                self._t.targetFingersChanged.emit()
                self._t.targetChordChanged.emit("")
                self._t._prompt_time = time.time()  # Reset timing for next note
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._t._target_chord_name})")
        self._t.targetChordChanged.emit(self._t._target_chord_name)

    def on_note_on(self, pitch: int):
        # Only the exact current note counts as right.
        if self.sequence and self.index < len(self.sequence):
            if pitch != self.sequence[self.index]:
                self._t._wrong_notes_count += 1

    def mistake_active(self) -> bool:
        # Only the current note is right, but holding the previous one is legato.
        if not self.sequence or self.index >= len(self.sequence):
            return False
        target = self.sequence[self.index]
        previous = self.sequence[self.index - 1] if self.index > 0 else -1
        return any(p != target and p != previous for p in self._t._active_pitches)

    def on_keys_released(self):
        # Mid-sequence there is nothing to do; the next note is already the target.
        if self.index >= len(self.sequence):
            QTimer.singleShot(700, self._t._next_chord)

    def stat_key(self) -> str:
        return self.scale_name

    def success_label(self) -> str:
        # A qualitative summary rather than raw latency.
        wrong = self._t._wrong_notes_count
        if wrong == 0:
            return "Excellent Timing!"
        if wrong <= 2:
            return "Good Pace"
        return "Keep Practicing"
