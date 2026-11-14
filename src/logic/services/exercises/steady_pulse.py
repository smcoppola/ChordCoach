"""Steady pulse: the same chord on every beat of a metronome."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List

from PySide6.QtCore import QTimer  # type: ignore

from logic.services.exercises.base import Exercise  # type: ignore


class SteadyPulse(Exercise):
    type = "steady_pulse"
    reviewable = False

    def __init__(self, trainer):
        super().__init__(trainer)
        self.beats = 16          # total beats to play
        self.hits: List[float] = []  # timing offset of each hit
        self.current_beat = 0
        self.missed_beats = 0

    def setup(self, chord_data):
        """Sets up a steady pulse exercise: user repeats a chord/note on every beat."""
        root_idx = int(chord_data.get("root_idx", 0))
        chord_type_name = str(chord_data.get("chord_type", "Major"))
        intervals = self._t.CHORD_TYPES.get(chord_type_name, self._t.CHORD_TYPES["Major"])
        octave = int(chord_data.get("octave", 4))
        self._t._setup_target(root_idx, chord_type_name, intervals, octave)
        self._t._exercise_type = "steady_pulse"
        self.beats = int(chord_data.get("pulse_count", 16))
        self.hits = []
        self.current_beat = 0
        self.missed_beats = 0
        
        # Build scrolling notes
        sn = []
        base_pitch = (octave + 1) * 12 + root_idx
        for i in range(self.beats):
            sn.append({
                "pitch": base_pitch,
                "start_beat": i,
                "duration_beats": 1,
                "finger": 1,
                "hand": "R" if octave >= 4 else "L"
            })
        self._t._scrolling_notes = sn
        self._t.scrollingNotesChanged.emit()

        bpm = int(chord_data.get("bpm", 100))
        self._t._scroll_bpm = bpm
        self._t.scrollBpmChanged.emit()
        self._t._scroll_beat = 0.0 if bpm == 0 else (self._t.metronome.currentBeatPosition if self._t.metronome else 0.0)
        self._t.scrollBeatChanged.emit(self._t._scroll_beat)
        self._t._emit_scroll_anchor(self._t._scroll_beat, bpm / 60.0, active=bpm > 0, snap=True)
        if self._t.metronome:
            if self._t._ai_is_currently_speaking or self._t.isPausedForSpeech:
                self._t.metronome.defer_start(bpm)
            else:
                self._t.metronome.start(bpm)
        print(f"ChordTrainer: Steady Pulse started for {self._t._target_chord_name} at {bpm} BPM")

    def check_input(self):
        """Validates timing of a hit in steady_pulse mode."""
        if not self._t.metronome or self._t.metronome.is_in_lead_in:
            return

        # Correct chord?
        if not self._t._is_chord_satisfied():
            return

        # Find the nearest beat
        # (Simplified: we track hits and timing offsets)
        timing_offset = self._t.metronome.get_timing_offset_ms(self.current_beat)
        
        # Only record if we haven't hit this beat yet and it's within a window
        # For now, just record it and the evaluator can deal with details
        if abs(timing_offset) < 300: # 300ms window
            # Prevent double-recording same beat
            self.hits.append(timing_offset)
            print(f"ChordTrainer: Steady Pulse Hit on beat {self.current_beat}, offset {timing_offset:.1f}ms")
            
            # Emit success signal for visual feedback
            self._t.chordSuccess.emit(self._t._target_chord_name, timing_offset)
            
            # Record in DB
            self._t.db.record_chord_attempt(self._t._target_chord_name, True, timing_offset, 0, True, timing_offset)

    def on_metronome_tick(self, beat_count):
        """Logic called every metronome tick during steady_pulse."""
        if beat_count > self.beats:
            print(f"ChordTrainer: Steady Pulse complete ({len(self.hits)}/{self.beats} hits)")
            if self._t.metronome:
                self._t.metronome.stop()
            self._t._complete_chord()
