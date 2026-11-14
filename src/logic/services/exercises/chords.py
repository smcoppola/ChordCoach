"""Chord-shaped exercises: hands together, sustain pedal, ear training, theory cards."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List

from PySide6.QtCore import QTimer  # type: ignore

from logic.services.exercises.base import Exercise  # type: ignore


class HandsTogether(Exercise):
    """Right-hand chord over its root in the left hand."""
    type = "hands_together"

    def setup(self, chord_data):
        """Sets up a hands together exercise: right hand chord + left hand bass note."""
        root_idx = int(chord_data.get("root_idx", 0))
        chord_type_name = str(chord_data.get("chord_type_name", "Major"))
        intervals = self._t.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))

        self._t._current_hand = "both"
        self._t._setup_target(root_idx, chord_type_name, intervals, octave, suppress_signal=True)

        # Override formula and type for hands together UI differences
        self._t._target_chord_type = "Hands Together"
        self._t._target_formula_text = "Bass + Chord"

        # Inject bass note for UI rendering
        lh_octave = max(2, min(3, octave - 1))
        lh_base_pitch = (lh_octave + 1) * 12 + root_idx
        self._t._target_pitches.insert(0, lh_base_pitch)
        self._t._target_hands.insert(0, "left")
        
        # Add LH finger (usually thumb/1 but calculation will handle it)
        lh_fingers = self._t._calculate_fingerings([lh_base_pitch], "left")
        if lh_fingers:
            self._t._target_fingers.insert(0, lh_fingers[0])
            self._t.targetFingersChanged.emit()

        self._t.targetChordChanged.emit(self._t._target_chord_name)


class SustainPedal(Exercise):
    """A chord that only counts with the pedal: pressed with it (direct) or after it (legato)."""
    type = "sustain_pedal"
    needs_pedal = True

    def setup(self, chord_data):
        """Sets up a sustain pedal exercise."""
        root_idx = int(chord_data.get("root_idx", 0))
        chord_type_name = str(chord_data.get("chord_type_name", "Major"))
        if chord_type_name in ("N/A", "None", "Single", ""):
            intervals = chord_data.get("intervals", [0])
            chord_type_name = ""
        else:
            intervals = self._t.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))

        self.pedal_type = str(chord_data.get("pedal_type", "direct"))
        self.pedal_satisfied = False

        self._t._setup_target(root_idx, chord_type_name, intervals, octave, suppress_signal=True)
        self._t._target_chord_type = "Sustain Pedal"
        # We don't need UI text for pedal type since standard notation will be used,
        # but keep it in formula text for debugging or fallback if desired.
        self._t._target_formula_text = f"Pedal: {self.pedal_type.capitalize()}"

        # Override the target name if it was blanked out by the fallback to single note
        if not chord_type_name:
            root_name = self._t.ROOT_NOTES[root_idx]
            self._t._target_chord_name = f"{root_name} Note ({self.pedal_type.capitalize()} Pedal)"

        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged for Sustain ({self._t._target_chord_name})")
        self._t.targetChordChanged.emit(self._t._target_chord_name)

    def on_pedal(self, is_down: bool):
        t = self._t
        if self.pedal_satisfied:
            return
        if self.pedal_type == "direct":
            # Pedal should be pressed around the same time as the chord
            if is_down and t._is_holding:
                pedal_timing = t._pedal_down_time - t._hold_start_time
                if pedal_timing <= 400: # generous 400ms window
                    self.pedal_satisfied = True
                    t._check_input()
                else:
                    t.speakInstruction.emit("Try to press the pedal *exactly* when you strike the keys for a 'direct' pedal technique.")
        elif self.pedal_type == "legato":
            # Pedal should be pressed after the chord starts
            if is_down and t._is_holding:
                self.pedal_satisfied = True
                t._check_input()


class Listen(Exercise):
    """Ear training: the app plays a chord, the student says major or minor on screen."""
    type = "listen"
    reviewable = False
    keyboard_answers = False

    def setup(self, chord_data):
        """Sets up an ear training exercise: plays a chord, user identifies it."""
        root_idx = int(chord_data.get("root_idx", 0))

        target_quality = str(chord_data.get("target_quality", "")).strip()
        chord_type_name = str(chord_data.get("chord_type_name", "")).strip()

        # Reconcile missing parameters if the AI was sloppy
        if target_quality and not chord_type_name:
            chord_type_name = target_quality
        elif chord_type_name and not target_quality:
            target_quality = chord_type_name
        elif not target_quality and not chord_type_name:
            chord_type_name = "Major"
            target_quality = "Major"

        # Ensure proper casing since dictionary CHORD_TYPES expects Title Case (e.g. 'minor' -> 'Minor')
        if chord_type_name:
            chord_type_name = chord_type_name[0].upper() + chord_type_name[1:]
        if target_quality:
            target_quality = target_quality[0].upper() + target_quality[1:]

        intervals = self._t.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))

        # Standard chord setup but marked as listen
        self._t._setup_target(root_idx, chord_type_name, intervals, octave, preview_chord=True)
        self._t._target_chord_name = "Listen to the chord"
        self._t._target_chord_type = "Listen" # UI uses this to show quiz instead of notation
        self._t._target_formula_text = target_quality # Hidden till answered

        self._t.targetChordChanged.emit(self._t._target_chord_name)

        print(f"ChordTrainer: Listen target: {root_idx} {chord_type_name}, quality={target_quality}")

    def after_success(self):
        # Answered on screen, not with keys: pause briefly, then move on.
        QTimer.singleShot(700, self._t._next_chord)


class TheoryConcept(Exercise):
    """A card with an idea and Continue; nothing to play."""
    type = "theory_concept"
    reviewable = False

    def setup(self, chord_data):
        """A theory card: title and explanation on screen, Continue to move on. Nothing to play."""
        name = str(chord_data.get("exercise_name", ""))
        self._t._target_chord_name = name
        self._t._target_chord_type = "Concept"
        self._t._target_formula_text = ""
        self._t._target_intervals = set()
        self._t._target_pitches = []
        self._t._target_hands = []
        self._t._target_fingers = []
        self._t._scrolling_notes = []
        self._t.scrollingNotesChanged.emit()
        self._t.targetFingersChanged.emit()
        self._t._set_concept_card({"title": name, "body": str(chord_data.get("concept_body", ""))})
        self._t.targetChordChanged.emit(self._t._target_chord_name)


class SongApplication(Exercise):
    """A piece, self-paced or in rhythm. The piece itself lives in SongSession."""
    type = "song_application"
    reviewable = False

    def setup(self, chord_data):
        self._t._song.setup(chord_data)

    def handle_raw_note(self, pitch: int, is_on: bool) -> bool:
        # In rhythm mode the RhythmEngine owns scoring outright, so the engine
        # path and the self-paced path can never both run for one note-on.
        # The trainer's held keys are deliberately left alone: they are the
        # self-paced path's state, and leaving them empty keeps mistakeActive
        # (and its whole-sheet dim) inert.
        song = self._t._song
        if song.pacing_mode != "rhythm":
            return False
        song.engine.handle_midi_note(pitch, is_on)
        return True

    def on_note_on(self, pitch: int):
        # Songs leave the target intervals empty, so mistakes are counted
        # here. Previous-step pitches are tolerated for legato playing.
        t = self._t
        if pitch not in t._target_pitches and pitch not in t._prev_target_pitches:
            t._song.wrong_notes += 1

    def mistake_active(self) -> bool:
        t = self._t
        allowed = set(t._target_pitches) | set(t._prev_target_pitches)
        return any(p not in allowed for p in t._active_pitches)

    def on_keys_released(self):
        self._t._song.advance_step()

    def after_success(self):
        t = self._t
        song = t._song
        song.index += 1
        if song.index < len(song.steps):
            print("ChordTrainer: Advancing song immediately (Legato-Friendly)")
            song.advance_step()
            return
        # Last note played — advance beat past song end so all notes render gray
        t._set_stepped_scroll_beat(song.end_beat + 0.5)
        song.completed = True
        t.songCompletedChanged.emit()
        # Only a lesson has an AI turn worth blocking for, and only
        # _apply_exercise clears this window. In free play nothing ever
        # would, so the block outlived the song and deafened the next
        # one. Mirrors the same guard on the rhythm path.
        if t._is_lesson_mode:
            t._ignore_midi_until = time.time() + 99.0
        print(f"ChordTrainer: Song complete — '{song.title}'")
        QTimer.singleShot(1500, song.on_finished)
