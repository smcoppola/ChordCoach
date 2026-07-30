import json
from pathlib import Path
from typing import List, Dict, Any
from PySide6.QtCore import QObject, Signal, Slot, Property # type: ignore
from logic.services.database_manager import DatabaseManager # type: ignore
from logic.services.rhythm_engine import RhythmEngine # type: ignore


class EvaluationService(QObject):
    """
    Manages the onboarding skill evaluation using scrolling sheet music.
    Plays through pre-generated melody sequences at increasing difficulty,
    scoring the user's accuracy to determine their skill level.

    The beat clock, hit window and per-note scoring live in RhythmEngine
    (extracted in Phase 4 and shared with song rhythm practice). This class
    keeps what is specific to onboarding: the sequences.json ladder, the
    level-advance thresholds, and the QML contract below.
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
        self._tempo_bpm = 100
        self._accuracy = 0.0
        self._assessed_level = 0
        self._paused = False

        # Current sequence data
        self._sequence_notes: List[Dict[str, Any]] = []

        # Timing / scoring engine. beat_signal_interval=0.0 keeps the 100 Hz
        # beatChanged cadence the onboarding scroll was tuned against; the
        # engine's 30 Hz default is for the song renderer.
        self._engine = RhythmEngine(self, beat_signal_interval=0.0)
        self._engine.beatChanged.connect(self._on_engine_beat)
        self._engine.noteStateChanged.connect(self._on_engine_note_state)
        self._engine.metronomeTick.connect(self._on_engine_metronome_tick)
        self._engine.finished.connect(self._on_engine_finished)

        # Count-in length, in beats, before the first note arrives
        self._count_in_beats = 4

        # Adaptive thresholds
        self._advance_threshold = 0.70
        self._fail_threshold = 0.60

        # Load sequences
        seq_path = project_root / "src" / "resources" / "sequences.json"
        if seq_path.exists():
            with open(seq_path, "r", encoding="utf-8") as f:
                self._sequences = json.load(f)
            # Add fingerings on-the-fly for all sequences
            for seq in self._sequences:
                self._calculate_fingering(seq.get("notes", []))
            print(f"EvaluationService: Loaded {len(self._sequences)} sequences with pedagogical fingering")
        else:
            print(f"EvaluationService: WARNING - {seq_path} not found!")

    # ── Properties for QML ──────────────────────────────────────────

    @Property(bool, notify=sequenceChanged)
    def isRunning(self) -> bool:
        return self._is_running

    @Property(float, notify=beatChanged)
    def currentBeat(self) -> float:
        return self._engine.currentBeat

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
        return self._engine.noteStates

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
        self._engine.stop()
        self._is_running = False
        self._paused = False
        self._sequence_notes = []
        self._engine.load([], self._tempo_bpm, count_in_beats=self._count_in_beats)
        self.sequenceChanged.emit()
        self.pausedChanged.emit()

    @Slot()
    def togglePause(self):
        """Toggle the pause state of the evaluation."""
        if not self._is_running:
            return

        self._engine.toggle_pause()
        self._paused = self._engine.paused
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
            self._engine.resume()
            self._paused = self._engine.paused
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

        # Hand the sequence to the engine: it resets note states and rewinds the
        # clock to -count_in_beats so the notes arrive after the count-in.
        self._engine.load(self._sequence_notes, self._tempo_bpm,
                          count_in_beats=self._count_in_beats)

        self._accuracy = 0.0

        self.levelChanged.emit()
        self.sequenceChanged.emit()
        self.beatChanged.emit()
        self.noteStateChanged.emit()

        print(f"EvaluationService: Starting level {level} — '{seq.get('title', '')}' at {self._tempo_bpm} BPM")
        print(f"EvaluationService: Beat timer starting at beat {self._engine.currentBeat}")

        self._engine.start(paused=paused)
        if paused:
            print(f"EvaluationService: Starting level {level} in PAUSED mode")

    def _finish_evaluation(self):
        """End the evaluation and report results."""
        self._engine.stop()
        self._is_running = False

        # The assessed level is the last level they passed
        print(f"EvaluationService: Evaluation complete. Assessed level: {self._assessed_level}")

        self.sequenceChanged.emit()
        self.evaluationFinished.emit()

    def _calculate_fingering(self, notes: List[Dict[str, Any]]):
        """Augment notes with pedagogical fingerings for simple evaluation melodies."""
        for n in notes:
            if "finger" in n: continue
            # Map Hand 'R'/'L' to boolean
            is_right = n.get("hand", "R").upper() == "R"
            pitch = n.get("pitch", 60)
            
            # Diatonic C-Position mapping (semitone offset: finger)
            base = 60 if is_right else 48
            offset = pitch - base
            if is_right:
                # RH: C(0)=1, D(2)=2, E(4)=3, F(5)=4, G(7)=5
                mapping = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4, 7: 5}
                f = mapping.get(offset, 1 if offset < 0 else 5)
            else:
                # LH: C(0)=1, B(-1)=2, A(-3)=3, G(-5)=4, F(-7)=5
                mapping = {0: 1, -1: 2, -2: 2, -3: 3, -4: 3, -5: 4, -6: 4, -7: 5}
                f = mapping.get(offset, 1 if offset > 0 else 5)
                
            n["finger"] = int(f)

    # ── Rhythm Engine Adapter ───────────────────────────────────────
    # The beat clock, count-in metronome, hit window and per-note scoring
    # were moved into RhythmEngine. These handlers translate the engine's
    # parameterised signals into this service's parameterless QML signals.

    def _on_engine_beat(self, _beat: float):
        self.beatChanged.emit()

    def _on_engine_note_state(self, _index: int, _state: str):
        self._accuracy = self._engine.accuracy
        self.noteStateChanged.emit()

    def _on_engine_metronome_tick(self, beat_num: int, _accent: bool):
        print(f"EvaluationService: Emitting metronomeTick {beat_num} (beat {self._engine.currentBeat:.2f})")
        self.metronomeTick.emit(beat_num)

    def _on_engine_finished(self, accuracy: float, hits: int, misses: int):
        self._end_level(accuracy, hits, hits + misses)

    def _end_level(self, accuracy: float, hits: int, total: int):
        """Evaluate accuracy for this level and decide what to do next."""
        self._engine.stop()

        self._accuracy = accuracy

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

        self._engine.handle_midi_note(pitch, is_on)
