import json
import time
from pathlib import Path
from typing import List, Dict, Any
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt # type: ignore
from logic.services.database_manager import DatabaseManager # type: ignore


class EvaluationService(QObject):
    """
    Manages the onboarding skill evaluation using scrolling sheet music.
    Plays through pre-generated melody sequences at increasing difficulty,
    scoring the user's accuracy to determine their skill level.
    """
    # QML state signals
    sequenceChanged = Signal()
    beatChanged = Signal()
    levelChanged = Signal()
    evaluationFinished = Signal()
    metronomeTick = Signal(int)  # Beat number (1-4) during lead-in
    noteStateChanged = Signal()  # Emitted when a note is hit or missed
    pausedChanged = Signal()

    def __init__(self, db: DatabaseManager, project_root: Path):
        super().__init__()
        self.db = db
        self._sequences: List[Dict[str, Any]] = []
        self._is_running = False
        self._current_level = 0
        self._current_beat = -4.0  # Start 4 beats before notes arrive
        self._tempo_bpm = 100
        self._accuracy = 0.0
        self._assessed_level = 0
        self._paused = False

        # Current sequence data
        self._sequence_notes: List[Dict[str, Any]] = []
        self._note_states: List[str] = []  # "pending", "hit", "miss"
        self._active_held_keys: set[int] = set()

        # Timing
        self._beat_timer = QTimer()
        self._beat_timer.setTimerType(Qt.PreciseTimer)
        self._tick_interval_ms = 10  # 100fps update rate for buttery smooth movement
        self._beat_timer.setInterval(self._tick_interval_ms)
        self._beat_timer.timeout.connect(self._advance_beat)
        self._last_tick_time = 0.0

        # Metronome state
        self._metronome_beats_emitted = 0
        self._next_metronome_beat = -4  # Beats -4, -3, -2, -1

        # Hit detection window (in beats, not ms)
        self._hit_window_beats = 0.35  # ~210ms at 100bpm

        # Adaptive thresholds
        self._advance_threshold = 0.70
        self._fail_threshold = 0.60

        # Load sequences
        seq_path = project_root / "src" / "resources" / "sequences.json"
        if seq_path.exists():
            with open(seq_path, "r", encoding="utf-8") as f:
                self._sequences = json.load(f)
            print(f"EvaluationService: Loaded {len(self._sequences)} sequences")
        else:
            print(f"EvaluationService: WARNING - {seq_path} not found!")

    # ── Properties for QML ──────────────────────────────────────────

    @Property(bool, notify=sequenceChanged)
    def isRunning(self) -> bool:
        return self._is_running

    @Property(float, notify=beatChanged)
    def currentBeat(self) -> float:
        return self._current_beat

    @Property(int, notify=levelChanged)
    def currentLevel(self) -> int:
        return self._current_level

    @Property(int, notify=evaluationFinished)
    def assessedLevel(self) -> int:
        return self._assessed_level

    @Property(float, notify=noteStateChanged)
    def accuracy(self) -> float:
        return self._accuracy

    @Property(int, notify=sequenceChanged)
    def tempo(self) -> int:
        return self._tempo_bpm

    @Property(str, notify=sequenceChanged)
    def sequenceTitle(self) -> str:
        if self._current_level > 0 and self._current_level <= len(self._sequences):
            return self._sequences[self._current_level - 1].get("title", "")
        return ""

    @Property(list, notify=sequenceChanged)
    def sequenceNotes(self) -> list:
        return self._sequence_notes

    @Property(list, notify=noteStateChanged)
    def noteStates(self) -> list:
        return self._note_states

    @Property(bool, notify=pausedChanged)
    def paused(self) -> bool:
        return self._paused

    # ── Public Slots ────────────────────────────────────────────────

    @Slot()
    @Slot(bool)
    def startEvaluation(self, paused: bool = False):
        """Begin the evaluation from level 1."""
        self._current_level = 0
        self._assessed_level = 0
        self._is_running = True
        self._paused = paused
        self.sequenceChanged.emit()
        self.pausedChanged.emit()
        self._start_level(1, paused=paused)

    @Slot()
    def stopEvaluation(self):
        """Abort the evaluation."""
        self._beat_timer.stop()
        self._is_running = False
        self._paused = False
        self._sequence_notes = []
        self._note_states = []
        self.sequenceChanged.emit()
        self.pausedChanged.emit()
        
    @Slot()
    def togglePause(self):
        """Toggle the pause state of the evaluation."""
        if not self._is_running:
            return
            
        if self._beat_timer.isActive():
            self._beat_timer.stop()
            self._paused = True
        else:
            self._last_tick_time = time.perf_counter()
            self._beat_timer.start()
            self._paused = False
        self.pausedChanged.emit()

    @Slot()
    def restartLevel(self):
        """Restart the current evaluation level."""
        if self._current_level > 0:
            self._paused = False
            self.pausedChanged.emit()
            self._start_level(self._current_level)

    @Slot()
    def resume(self):
        """Resume the evaluation if it was paused."""
        if self._is_running and self._paused:
            self._last_tick_time = time.perf_counter()
            self._beat_timer.start()
            self._paused = False
            self.pausedChanged.emit()
            print("EvaluationService: Resuming evaluation.")

    # ── Level Management ────────────────────────────────────────────

    def _start_level(self, level: int, paused: bool = False):
        """Load and start a specific difficulty level."""
        if level < 1 or level > len(self._sequences):
            self._finish_evaluation()
            return

        self._current_level = level
        seq = self._sequences[level - 1]
        self._tempo_bpm = seq.get("tempo_bpm", 100)
        self._sequence_notes = seq.get("notes", [])
        self._note_states = ["pending"] * len(self._sequence_notes)
        self._active_held_keys.clear()

        # Reset beat to 4 beats before the first note
        self._current_beat = -4.0
        self._metronome_beats_emitted = 0
        self._next_metronome_beat = -4

        self._accuracy = 0.0

        self.levelChanged.emit()
        self.sequenceChanged.emit()
        self.beatChanged.emit()
        self.noteStateChanged.emit()

        print(f"EvaluationService: Starting level {level} — '{seq.get('title', '')}' at {self._tempo_bpm} BPM")
        print(f"EvaluationService: Beat timer starting at beat {self._current_beat}")

        if not paused:
            # Start the beat timer
            self._last_tick_time = time.perf_counter()
            self._beat_timer.start()
            print(f"EvaluationService: Beat timer starting at beat {self._current_beat}")
        else:
            print(f"EvaluationService: Starting level {level} in PAUSED mode")

    def _finish_evaluation(self):
        """End the evaluation and report results."""
        self._beat_timer.stop()
        self._is_running = False

        # The assessed level is the last level they passed
        print(f"EvaluationService: Evaluation complete. Assessed level: {self._assessed_level}")

        self.sequenceChanged.emit()
        self.evaluationFinished.emit()

    # ── Beat Timer ──────────────────────────────────────────────────

    def _advance_beat(self):
        """Called ~60x/sec by QTimer. Advances currentBeat based on real elapsed time."""
        now = time.perf_counter()
        elapsed_sec = now - self._last_tick_time
        self._last_tick_time = now

        beats_per_sec = self._tempo_bpm / 60.0
        beat_delta = elapsed_sec * beats_per_sec
        self._current_beat += beat_delta
        self.beatChanged.emit()

        # Emit metronome ticks during the lead-in (beats -4 through -1)
        if self._next_metronome_beat <= -1:
            if self._current_beat >= self._next_metronome_beat:
                tick_num = self._next_metronome_beat + 5  # -4→1, -3→2, -2→3, -1→4
                print(f"EvaluationService: Emitting metronomeTick {tick_num} (beat {self._current_beat:.2f})")
                self.metronomeTick.emit(tick_num)
                self._next_metronome_beat += 1

        # Check for missed notes (passed the hit window)
        self._check_missed_notes()

        # Check if sequence is complete
        last_note = self._sequence_notes[-1] if self._sequence_notes else None
        if last_note:
            seq_end = last_note["start_beat"] + last_note["duration_beats"] + 2  # 2 beats buffer
            if self._current_beat > seq_end:
                self._end_level()

    def _end_level(self):
        """Evaluate accuracy for this level and decide what to do next."""
        self._beat_timer.stop()

        total = len(self._note_states)
        hits = self._note_states.count("hit")
        self._accuracy = hits / total if total > 0 else 0.0

        print(f"EvaluationService: Level {self._current_level} complete — "
              f"{hits}/{total} ({self._accuracy*100:.0f}%)")

        if self._accuracy >= self._advance_threshold:
            # Passed — record and advance
            self._assessed_level = self._current_level
            if self._current_level < len(self._sequences):
                self._start_level(self._current_level + 1)
            else:
                self._finish_evaluation()
        elif self._accuracy >= self._fail_threshold:
            # Borderline — still counts, but stop here
            self._assessed_level = self._current_level
            self._finish_evaluation()
        else:
            # Failed — stop, don't count this level
            self._finish_evaluation()

    # ── MIDI Input Handling ─────────────────────────────────────────

    def handle_midi_note(self, pitch: int, is_on: bool):
        """Called by AppState when MIDI events arrive during evaluation."""
        if not self._is_running:
            return

        if is_on:
            self._active_held_keys.add(pitch)
            self._check_note_hit(pitch)
        else:
            self._active_held_keys.discard(pitch)

    def _check_note_hit(self, pitch: int):
        """Check if a played pitch matches any pending note within the hit window."""
        for i, note in enumerate(self._sequence_notes):
            if self._note_states[i] != "pending":
                continue
            if note["pitch"] != pitch:
                continue

            # Check if within timing window
            time_diff = abs(self._current_beat - note["start_beat"])
            if time_diff <= self._hit_window_beats:
                self._note_states[i] = "hit"
                self.noteStateChanged.emit()
                return

    def _check_missed_notes(self):
        """Mark notes as missed if the playhead has moved past them."""
        changed = False
        for i, note in enumerate(self._sequence_notes):
            if self._note_states[i] != "pending":
                continue
            # If we're past the hit window for this note, it's missed
            if self._current_beat > note["start_beat"] + self._hit_window_beats:
                self._note_states[i] = "miss"
                changed = True
        if changed:
            self.noteStateChanged.emit()
