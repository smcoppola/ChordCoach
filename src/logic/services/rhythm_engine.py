"""
===============================================================================
File: rhythm_engine.py
Description: Reusable beat-clock / hit-window scoring engine for ChordCoach
             Companion.

             The mechanics here (10 ms PreciseTimer, wall-clock beat advance,
             count-in metronome ticks, per-note "pending"/"hit"/"miss" states,
             a hit window measured in BEATS rather than milliseconds) were
             moved verbatim out of EvaluationService, which had been driving
             the onboarding skill evaluation with them since launch.
             EvaluationService now delegates to this class, and song practice
             in "rhythm" pacing mode uses the same engine.
===============================================================================
"""
import time
from typing import Any, Dict, List

from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt  # type: ignore


class RhythmEngine(QObject):
    """
    Drives a beat clock over an arbitrary note list and scores each note as
    "hit" or "miss" against a timing window.

    One entry per pitch: chords are several entries sharing a ``start_beat``
    and each scores independently, so a partially played chord scores partially.
    """

    # Playhead position in beats. Throttled to `beat_signal_interval` seconds
    # (30 Hz by default, matching the Phase 2 renderer convention). Pass 0.0 to
    # emit on every timer tick — EvaluationService does this to preserve the
    # 100 Hz scroll cadence onboarding shipped with.
    beatChanged = Signal(float)
    # (note index, "pending" | "hit" | "miss")
    noteStateChanged = Signal(int, str)
    # (count-in beat number starting at 1, is_accent)
    metronomeTick = Signal(int, bool)
    # (accuracy 0..1, hits, misses) — accumulated across loop passes
    finished = Signal(float, int, int)

    # Hit window in BEATS, not milliseconds: practising slower automatically
    # grants proportionally more wall-clock leeway.
    HIT_WINDOW_BEATS = 0.35

    # Beats of silence after the final note before a run is considered over.
    TAIL_BEATS = 2.0

    def __init__(self, parent=None, beat_signal_interval: float = 0.033):
        super().__init__(parent)

        # Note data
        self._notes: List[Dict[str, Any]] = []
        self._note_states: List[str] = []
        self._active_held_keys: set[int] = set()

        # Clock state
        self._tempo_bpm: float = 100.0
        self._tempo_scale: float = 1.0
        self._count_in_beats: int = 4
        self._current_beat: float = 0.0
        self._end_beat: float = 0.0
        self._is_running: bool = False
        self._paused: bool = False

        # Metronome state (count-in only, as in the original evaluation flow)
        self._next_metronome_beat: int = 0

        # Index of the earliest note whose hit window the playhead has not passed
        self._miss_cursor: int = 0

        # Loop state
        self._loop_start: float = -1.0
        self._loop_end: float = -1.0
        self._loop_passes: int = 0

        # Stats accumulated from completed loop passes
        self._acc_hits: int = 0
        self._acc_total: int = 0

        # Live accuracy over resolved (non-pending) notes
        self._accuracy: float = 0.0

        # Timing
        self._beat_timer = QTimer(self)
        self._beat_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick_interval_ms = 10  # 100 fps update rate for smooth movement
        self._beat_timer.setInterval(self._tick_interval_ms)
        self._beat_timer.timeout.connect(self._advance_beat)
        self._last_tick_time = 0.0

        self._beat_signal_interval = float(beat_signal_interval)
        self._last_beat_signal_time = 0.0

    # ── Read-only state ─────────────────────────────────────────────
    # Plain Python properties: the engine is an internal collaborator of
    # EvaluationService and ChordTrainerService, never bound from QML directly.

    @property
    def currentBeat(self) -> float:
        return self._current_beat

    @property
    def noteStates(self) -> List[str]:
        return self._note_states

    @property
    def notes(self) -> List[Dict[str, Any]]:
        return self._notes

    @property
    def accuracy(self) -> float:
        """Live accuracy over resolved notes only (pending notes excluded)."""
        return self._accuracy

    @property
    def isRunning(self) -> bool:
        return self._is_running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def loopPasses(self) -> int:
        return self._loop_passes

    @property
    def hasLoop(self) -> bool:
        return self._loop_end > self._loop_start >= 0.0

    @property
    def tempoBpm(self) -> float:
        return self._tempo_bpm

    def set_tempo(self, bpm: float):
        """Changes the clock rate mid-run (e.g. the user moved the tempo slider)."""
        if bpm and bpm > 0:
            self._tempo_bpm = float(bpm)

    def set_tempo_scale(self, scale: float):
        self._tempo_scale = max(0.05, float(scale))

    # ── Loading & Transport ─────────────────────────────────────────

    def load(self, notes: List[Dict[str, Any]], tempo_bpm: float, count_in_beats: int = 4):
        """
        Loads an arbitrary note list. Each entry needs ``pitch``, ``start_beat``
        and ``duration_beats``; ``hand`` is optional and carried through untouched.
        """
        self.stop()

        # Sorted by onset so the miss sweep can walk a cursor instead of
        # rescanning every note on every 10 ms tick. The sort is stable, and
        # both callers already hand over onset-ordered lists, so note indices
        # (which `noteStateChanged` reports) are unaffected in practice.
        self._notes = sorted(notes or [], key=lambda n: float(n.get("start_beat", 0.0)))
        self._note_states = ["pending"] * len(self._notes)
        self._active_held_keys.clear()
        self._tempo_bpm = float(tempo_bpm) if tempo_bpm else 100.0
        self._count_in_beats = max(0, int(count_in_beats))

        self._reset_run_state()

        # A run ends TAIL_BEATS after the last note finishes sounding.
        if self._notes:
            self._end_beat = max(
                float(n.get("start_beat", 0.0)) + float(n.get("duration_beats", 0.0))
                for n in self._notes
            ) + self.TAIL_BEATS
        else:
            self._end_beat = self.TAIL_BEATS

    def _reset_run_state(self):
        """Resets clock, metronome and stats. Called on load, start and restart."""
        self._current_beat = -float(self._count_in_beats)
        self._next_metronome_beat = -self._count_in_beats
        self._miss_cursor = 0
        self._acc_hits = 0
        self._acc_total = 0
        self._loop_passes = 0
        self._accuracy = 0.0
        self._last_beat_signal_time = 0.0

    def set_loop(self, start_beat: float, end_beat: float):
        """
        Constrains the run to [start_beat, end_beat). On each wrap the states of
        notes inside the loop reset to "pending" so every pass scores on its own,
        while hits/misses accumulate across passes.
        """
        self._loop_start = float(start_beat)
        self._loop_end = float(end_beat)

    def clear_loop(self):
        self._loop_start = -1.0
        self._loop_end = -1.0

    @Slot()
    def start(self, paused: bool = False):
        """Starts a run from the count-in."""
        self._note_states = ["pending"] * len(self._notes)
        self._active_held_keys.clear()
        self._reset_run_state()

        self._is_running = True
        self._paused = bool(paused)

        self.beatChanged.emit(self._current_beat)

        if not paused:
            self._last_tick_time = time.perf_counter()
            self._beat_timer.start()

    @Slot()
    def stop(self):
        """Aborts the run without emitting `finished`."""
        self._beat_timer.stop()
        self._is_running = False
        self._paused = False

    @Slot()
    def pause(self):
        if self._is_running and self._beat_timer.isActive():
            self._beat_timer.stop()
            self._paused = True

    @Slot()
    def resume(self):
        if self._is_running and self._paused:
            self._last_tick_time = time.perf_counter()
            self._beat_timer.start()
            self._paused = False

    @Slot()
    def toggle_pause(self):
        if not self._is_running:
            return
        if self._beat_timer.isActive():
            self.pause()
        else:
            self.resume()

    @Slot()
    def finish_now(self):
        """
        Ends the run early and reports results. Used to close out a loop-only
        practice run, which would otherwise never reach the end of the piece.
        """
        if self._is_running:
            self._finish()

    # ── Beat Clock ──────────────────────────────────────────────────

    def _advance_beat(self):
        """Called every 10 ms. Advances currentBeat from real elapsed time."""
        now = time.perf_counter()
        elapsed_sec = now - self._last_tick_time
        self._last_tick_time = now

        beats_per_sec = (self._tempo_bpm * self._tempo_scale) / 60.0
        self._current_beat += elapsed_sec * beats_per_sec

        self._emit_beat(now)

        # Metronome ticks during the count-in (beats -count_in .. -1)
        if self._next_metronome_beat <= -1:
            if self._current_beat >= self._next_metronome_beat:
                tick_num = self._next_metronome_beat + self._count_in_beats + 1
                self.metronomeTick.emit(tick_num, tick_num == 1)
                self._next_metronome_beat += 1

        # Loop wrap takes priority over miss detection and end-of-run: the
        # playhead never actually travels past loop_end.
        if self.hasLoop and self._current_beat >= self._loop_end:
            self._wrap_loop()
            return

        self._check_missed_notes()

        if not self.hasLoop and self._current_beat > self._end_beat:
            self._finish()

    def _emit_beat(self, now: float):
        if self._beat_signal_interval <= 0.0:
            self.beatChanged.emit(self._current_beat)
        elif (now - self._last_beat_signal_time) >= self._beat_signal_interval:
            self._last_beat_signal_time = now
            self.beatChanged.emit(self._current_beat)

    def _wrap_loop(self):
        """Banks this pass's stats and resets in-loop note states to pending."""
        in_loop = [
            i for i, n in enumerate(self._notes)
            if self._loop_start <= float(n.get("start_beat", 0.0)) < self._loop_end
        ]

        # Anything inside the loop that is still pending has been passed over.
        for i in in_loop:
            if self._note_states[i] == "pending":
                self._note_states[i] = "miss"

        self._acc_hits += sum(1 for i in in_loop if self._note_states[i] == "hit")
        self._acc_total += len(in_loop)
        self._loop_passes += 1

        for i in in_loop:
            self._note_states[i] = "pending"
            self.noteStateChanged.emit(i, "pending")

        self._current_beat = self._loop_start
        self._next_metronome_beat = 0  # No count-in on a wrap
        # Rewind the miss cursor to the top of the loop; the notes it already
        # walked past are pending again.
        self._miss_cursor = 0
        while (self._miss_cursor < len(self._notes)
               and float(self._notes[self._miss_cursor].get("start_beat", 0.0)) < self._loop_start):
            self._miss_cursor += 1
        self._update_accuracy()
        self.beatChanged.emit(self._current_beat)

    # ── Scoring ─────────────────────────────────────────────────────

    def handle_midi_note(self, pitch: int, is_on: bool):
        """Feeds a MIDI event into the engine. Note-offs only release held state."""
        if not self._is_running:
            return

        if is_on:
            self._active_held_keys.add(pitch)
            self._check_note_hit(pitch)
        else:
            self._active_held_keys.discard(pitch)

    def _check_note_hit(self, pitch: int):
        """
        Scores a played pitch against the first pending note of that pitch inside
        the timing window. First-match (not nearest-match) is deliberate: it is
        the shipped onboarding behaviour, and two same-pitch notes can only both
        be in window if they sit within 0.7 beats of each other.
        """
        for i, note in enumerate(self._notes):
            if self._note_states[i] != "pending":
                continue
            if int(note.get("pitch", -1)) != pitch:
                continue
            if not self._in_scope(i):
                continue

            time_diff = abs(self._current_beat - float(note.get("start_beat", 0.0)))
            if time_diff <= self.HIT_WINDOW_BEATS:
                self._note_states[i] = "hit"
                self._update_accuracy()
                self.noteStateChanged.emit(i, "hit")
                return

    def _in_scope(self, index: int) -> bool:
        """
        True if a note is being scored right now. With an A/B loop set, only the
        notes inside the loop count — the rest of the piece is never played, so
        letting it mark misses would sink a loop-only run's accuracy.
        """
        if not self.hasLoop:
            return True
        start = float(self._notes[index].get("start_beat", 0.0))
        return self._loop_start <= start < self._loop_end

    def _check_missed_notes(self):
        """
        Marks notes missed once the playhead has passed their hit window.

        Runs 100 times a second, so it walks a cursor over the onset-sorted note
        list rather than rescanning the whole piece: once the playhead is past
        note i's window it is past every earlier note's too, and none of them can
        return to "pending" without a loop wrap (which rewinds the cursor).
        """
        # Nothing can be missed before the piece starts.
        if self._current_beat < 0.0:
            return

        changed = []
        limit = self._current_beat - self.HIT_WINDOW_BEATS
        while self._miss_cursor < len(self._notes):
            i = self._miss_cursor
            if float(self._notes[i].get("start_beat", 0.0)) >= limit:
                break
            if self._note_states[i] == "pending" and self._in_scope(i):
                self._note_states[i] = "miss"
                changed.append(i)
            self._miss_cursor += 1

        if changed:
            self._update_accuracy()
            for i in changed:
                self.noteStateChanged.emit(i, "miss")

    def _scored_states(self) -> List[str]:
        return [s for i, s in enumerate(self._note_states) if self._in_scope(i)]

    def _update_accuracy(self):
        """Recalculates live accuracy from resolved states plus banked passes."""
        self._accuracy = self.result()[0]

    def result(self):
        """
        Returns (accuracy, hits, misses) over the whole run, loop passes included.

        Only resolved notes count, so a run cut short mid-pass is not charged for
        notes it never reached. At a natural end every note has resolved, which
        makes this identical to the hits/total the evaluation flow always used.
        """
        resolved = [s for s in self._scored_states() if s != "pending"]
        hits = self._acc_hits + resolved.count("hit")
        total = self._acc_total + len(resolved)
        accuracy = (hits / total) if total > 0 else 0.0
        return (accuracy, hits, total - hits)

    def _finish(self):
        self._beat_timer.stop()
        self._is_running = False
        self._paused = False

        accuracy, hits, misses = self.result()
        self._accuracy = accuracy
        self.finished.emit(accuracy, hits, misses)
