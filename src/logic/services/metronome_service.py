"""
MetronomeService — Standalone metronome engine for ChordCoach Companion.

Provides a precise QTimer-based metronome with configurable BPM,
lead-in beats, deferred start (for speech synchronization), and
timing offset calculation for rhythm accuracy feedback.
"""
import time
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt  # type: ignore


class MetronomeService(QObject):
    tick = Signal(int)              # Emits current beat_count on each tick
    leadInComplete = Signal()       # Emitted when lead-in beats finish (beat_count reaches 0)
    bpmChanged = Signal(int)
    runningChanged = Signal(bool)
    beatPositionChanged = Signal(float) # Emits continuous float beat position for smooth scrolling

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bpm: int = 0
        self._beat_count: int = 0
        self._is_running: bool = False
        self._lead_in_beats: int = 4
        self._start_time: float = 0.0  # Wall-clock time when beat 0 will occur
        self._current_beat_position: float = 0.0
        self._last_tick_time: float = 0.0

        # Deferred start state (wait for AI speech to finish)
        self._deferred_bpm: int = 0
        self._deferred_interval_ms: int = 0
        self._has_deferred: bool = False

        # Precise timer for accurate beat tracking
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)

        # High-frequency timer for smooth UI animations
        self._beat_clock_timer = QTimer(self)
        self._beat_clock_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._beat_clock_timer.setInterval(10)
        self._beat_clock_timer.timeout.connect(self._update_beat_position)

    # ── Properties ────────────────────────────────────────────────────

    @Property(int, notify=bpmChanged)
    def bpm(self) -> int:
        return self._bpm

    @Property(int, notify=tick)
    def beatCount(self) -> int:
        return self._beat_count

    @Property(bool, notify=runningChanged)
    def isRunning(self) -> bool:
        return self._is_running

    @Property(float, notify=beatPositionChanged)
    def currentBeatPosition(self) -> float:
        return self._current_beat_position

    # ── Public API ────────────────────────────────────────────────────

    @Slot(int)
    @Slot(int, int)
    def start(self, bpm: int, lead_in_beats: int = 4):
        """Start the metronome immediately at the given BPM with a lead-in."""
        if bpm <= 0:
            self.stop()
            return

        self._bpm = bpm
        self._lead_in_beats = lead_in_beats
        self._beat_count = -lead_in_beats  # e.g., -4, -3, -2, -1, then 0 = first real beat
        interval_ms = int(60000 / bpm)

        self._start_time = time.time() + (interval_ms / 1000.0 * lead_in_beats)

        self._current_beat_position = -float(lead_in_beats)
        self._last_tick_time = time.perf_counter()

        self._timer.start(interval_ms)
        self._beat_clock_timer.start()
        self._is_running = True
        self._has_deferred = False

        self.bpmChanged.emit(bpm)
        self.runningChanged.emit(True)
        self.beatPositionChanged.emit(self._current_beat_position)
        print(f"MetronomeService: Started at {bpm} BPM ({lead_in_beats}-beat lead-in)")

    @Slot()
    def stop(self):
        """Stop the metronome."""
        if not self._is_running and not self._has_deferred:
            return

        self._timer.stop()
        self._beat_clock_timer.stop()
        was_running = self._is_running
        self._is_running = False
        self._has_deferred = False
        self._deferred_bpm = 0
        self._bpm = 0
        self._beat_count = 0
        self._current_beat_position = 0.0
        self._start_time = 0.0

        if was_running:
            self.runningChanged.emit(False)
            print("MetronomeService: Stopped")

    @Slot(int)
    @Slot(int, int)
    def defer_start(self, bpm: int, lead_in_beats: int = 4):
        """Queue a metronome start for later (e.g., after AI speech finishes).

        Call flush_deferred() when ready to actually start.
        """
        if bpm <= 0:
            return

        self._deferred_bpm = bpm
        self._deferred_interval_ms = int(60000 / bpm)
        self._has_deferred = True
        self._lead_in_beats = lead_in_beats
        print(f"MetronomeService: Deferred start queued at {bpm} BPM")

    @Slot()
    def flush_deferred(self):
        """Start the metronome if a deferred start was queued. Returns True if started."""
        if not self._has_deferred:
            return False

        bpm = self._deferred_bpm
        self._has_deferred = False
        self._deferred_bpm = 0
        self._deferred_interval_ms = 0

        self.start(bpm, self._lead_in_beats)
        print(f"MetronomeService: Flushed deferred start at {bpm} BPM")
        return True

    @property
    def has_deferred(self) -> bool:
        """Check if a deferred start is pending."""
        return self._has_deferred

    @property
    def is_in_lead_in(self) -> bool:
        """Check if the metronome is running but still in the lead-in phase."""
        return self._is_running and self._beat_count < 0

    def get_timing_offset_ms(self, note_index: int) -> float:
        """Calculate how many milliseconds off-beat a note was hit.

        Args:
            note_index: The zero-based index of the note in the sequence
                        (e.g., 0 for first pentascale note, 1 for second, etc.)

        Returns:
            Signed offset in ms. Negative = early, positive = late.
            Returns 0.0 if the metronome hasn't started or BPM is 0.
        """
        if self._bpm <= 0 or self._start_time <= 0:
            return 0.0

        interval_sec = 60.0 / self._bpm
        expected_time = self._start_time + (note_index * interval_sec)
        actual_time = time.time()
        return (actual_time - expected_time) * 1000.0

    # ── Internal ──────────────────────────────────────────────────────

    def _on_tick(self):
        """Called by QTimer on each beat."""
        self._beat_count += 1
        self.tick.emit(self._beat_count)

        # Notify when lead-in finishes (transition from -1 → 0)
        if self._beat_count == 0:
            self.leadInComplete.emit()

    def _update_beat_position(self):
        """Called by high-frequency timer to compute fractional beat position smoothly."""
        now = time.perf_counter()
        elapsed_sec = now - self._last_tick_time
        self._last_tick_time = now

        beats_per_sec = self._bpm / 60.0
        beat_delta = elapsed_sec * beats_per_sec
        self._current_beat_position += beat_delta
        self.beatPositionChanged.emit(self._current_beat_position)
