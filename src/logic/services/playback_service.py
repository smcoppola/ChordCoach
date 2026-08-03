"""
===============================================================================
File: playback_service.py
Description: Piece Playback Sequencer service for ChordCoach Companion.
             Compiles flat event timelines, drives wall-clock precise timers,
             manages A/B section looping, per-hand filtering, meter-correct 
             metronome ticks, and MIDI loopback suppression.
===============================================================================
"""
import math
import time
from typing import List, Dict, Any, Tuple, Set, Optional
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt  # type: ignore


# ── Pure Module-Level Functions (No Qt dependencies for headless testing) ────

def compile_events(steps: List[Dict[str, Any]], pedal_events: List[Dict[str, Any]]) -> List[Tuple]:
    """
    Compiles song steps and pedal events into a flat, chronologically sorted event list.

    Returns:
        List[Tuple]: Sorted event tuples:
          - Note On:  (beat, 0x90, pitch, velocity, hand)
          - Note Off: (beat, 0x80, pitch, 0, hand)
          - CC Pedal: (beat, 0xB0, 64, value, "both")
    """
    events = []

    # Compile note events from steps
    for step in steps or []:
        step_off = float(step.get("offset", 0.0))
        pitches = step.get("pitches", [])
        durations = step.get("durations", [])
        velocities = step.get("velocities", [])
        hands = step.get("hands", [])

        n_notes = len(pitches)
        step_dur = float(step.get("duration", 0.25))

        for i in range(n_notes):
            p = int(pitches[i])
            d = float(durations[i]) if i < len(durations) and durations[i] is not None else step_dur
            v_raw = velocities[i] if i < len(velocities) else None
            v = int(v_raw) if v_raw is not None else 80
            h = hands[i] if i < len(hands) else "right"

            # Note On
            events.append((step_off, 0x90, p, v, h))
            # Note Off
            events.append((step_off + d, 0x80, p, 0, h))

    # Compile sustain pedal events
    for p_event in pedal_events or []:
        p_off = float(p_event.get("offset", 0.0))
        p_val = int(p_event.get("value", 0))
        events.append((p_off, 0xB0, 64, p_val, "both"))

    # Sort events chronologically by beat offset. Tie-break: NOTE_OFF (0x80) before NOTE_ON (0x90)
    events.sort(key=lambda e: (e[0], 0 if e[1] == 0x80 else 1))
    return events


def bpm_at(tempo_map: List[Dict[str, Any]], beat: float) -> float:
    """
    Looks up the effective BPM at a given beat from a piecewise-constant tempo_map.
    """
    if not tempo_map:
        return 100.0

    sorted_map = sorted(tempo_map, key=lambda t: float(t.get("offset", 0.0)))
    effective_bpm = float(sorted_map[0].get("bpm", 100.0))

    for entry in sorted_map:
        if beat >= float(entry.get("offset", 0.0)):
            effective_bpm = float(entry.get("bpm", 100.0))
        else:
            break

    return effective_bpm


def beat_to_measure_info(time_signatures: List[Dict[str, Any]], beat: float) -> Tuple[int, int, bool]:
    """
    Calculates measure index, 1-based beat in measure, and downbeat flag for a beat position.

    Returns:
        Tuple[int, int, bool]: (measure_index, beat_in_measure_1_based, is_downbeat)
    """
    if not time_signatures:
        time_signatures = [{"offset": 0.0, "numerator": 4, "denominator": 4}]

    sorted_sigs = sorted(time_signatures, key=lambda ts: float(ts.get("offset", 0.0)))
    active_ts = sorted_sigs[0]
    for ts in sorted_sigs:
        if beat >= float(ts.get("offset", 0.0)):
            active_ts = ts
        else:
            break

    ts_offset = float(active_ts.get("offset", 0.0))
    num = int(active_ts.get("numerator", 4))
    den = int(active_ts.get("denominator", 4))

    beat_unit = 4.0 / den  # Beat unit length in quarter notes (e.g. 1.0 for 4/4, 0.5 for 6/8)
    measure_len = num * beat_unit

    rel_beat = max(0.0, beat - ts_offset)
    measure_idx = int(math.floor(rel_beat / measure_len)) if measure_len > 0 else 0
    beat_in_measure_idx = int(math.floor((rel_beat - measure_idx * measure_len) / beat_unit)) if beat_unit > 0 else 0

    beat_num = beat_in_measure_idx + 1
    is_downbeat = (beat_num == 1)

    return (measure_idx, beat_num, is_downbeat)


# ── PlaybackService Class ─────────────────────────────────────────────────────

class PlaybackService(QObject):
    """
    High-level QObject service driving piece playback, timer updates, A/B looping,
    and MIDI output hardware integration.
    """

    isPlayingChanged = Signal(bool)
    playbackBeatChanged = Signal(float)
    scrollAnchorChanged = Signal()
    tempoScaleChanged = Signal(float)
    loopStartBeatChanged = Signal(float)
    loopEndBeatChanged = Signal(float)
    handFilterChanged = Signal(str)
    metronomeEnabledChanged = Signal(bool)
    baseBpmChanged = Signal(float)
    playbackFinished = Signal()

    def __init__(self, hw_service=None, parent=None):
        super().__init__(parent)
        self._hw_service = hw_service

        # Piece Data
        self._steps: List[Dict[str, Any]] = []
        self._tempo_map: List[Dict[str, Any]] = []
        self._time_signatures: List[Dict[str, Any]] = []
        self._pedal_events: List[Dict[str, Any]] = []
        self._events: List[Tuple] = []

        # Playback State
        self._is_playing = False
        self._playback_beat = 0.0
        self._tempo_scale = 1.0
        self._loop_start_beat = -1.0
        self._loop_end_beat = -1.0
        self._hand_filter = "both"  # "both" | "right" | "left"
        self._metronome_enabled = False

        # Internal Execution Tracking
        self._cursor = 0
        self._sounding_notes: Set[Tuple[int, str]] = set()  # Set of (pitch, hand)
        self._sent_buffer: List[Tuple[int, float]] = []  # Ring buffer: (pitch, monotonic_ms)
        self._last_tick_time = 0.0
        self._last_beat_signal_time = 0.0
        self._last_metronome_beat = -1
        self._base_bpm = 100.0
        self._end_beat = 0.0

        # Scroll anchor. The notation does not consume playbackBeat: sampling a
        # moving position on a timer and pushing it into the UI is what made
        # scrolling judder. Instead the view is told where the playhead is and
        # how fast it is moving, and extrapolates on the display's frame clock.
        # See ScrollClock.qml.
        self._scroll_anchor: Dict[str, Any] = {
            "beat": 0.0, "bps": 0.0, "snap": True, "active": False, "seq": 0,
        }
        self._last_anchor_time = 0.0
        self._last_anchor_bps = 0.0

        # Precise Timer
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(10)  # 10 ms resolution
        self._timer.timeout.connect(self._on_tick)

    # ── QML Properties ────────────────────────────────────────────────────────

    @Property(bool, notify=isPlayingChanged)
    def isPlaying(self) -> bool:
        return self._is_playing

    @Property(float, notify=playbackBeatChanged)
    def playbackBeat(self) -> float:
        return self._playback_beat

    @Property("QVariantMap", notify=scrollAnchorChanged)
    def scrollAnchor(self) -> Dict[str, Any]:
        """
        Where the playhead is and how fast it is moving, for ScrollClock.qml.

        `snap` marks a genuine discontinuity (start, seek, loop wrap) that the
        view must land on rather than slide into. Anchors without it are drift
        corrections and are absorbed smoothly.
        """
        return self._scroll_anchor

    def _beats_per_second(self) -> float:
        """Current playhead speed in beats/sec, honouring the tempo map and scale."""
        if not self._is_playing:
            return 0.0
        return bpm_at(self._tempo_map, self._playback_beat) / 60.0 * self._tempo_scale

    def _emit_scroll_anchor(self, snap: bool = False, now: Optional[float] = None):
        """Publishes a new scroll anchor. Cheap enough to call on any state change."""
        bps = self._beats_per_second()
        self._scroll_anchor = {
            "beat": float(self._playback_beat),
            "bps": float(bps),
            "snap": bool(snap),
            "active": bool(self._is_playing),
            "seq": int(self._scroll_anchor["seq"]) + 1,
        }
        self._last_anchor_time = now if now is not None else time.perf_counter()
        self._last_anchor_bps = bps
        self.scrollAnchorChanged.emit()

    @Property(float, notify=tempoScaleChanged)
    def tempoScale(self) -> float:
        return self._tempo_scale

    @tempoScale.setter
    def tempoScale(self, val: float):
        clamped = max(0.25, min(1.5, float(val)))
        if abs(self._tempo_scale - clamped) > 1e-4:
            self._tempo_scale = clamped
            self.tempoScaleChanged.emit(self._tempo_scale)
            # Speed changed, so the view's extrapolation is now wrong. Not a
            # snap: the position is still correct, only the rate has changed.
            self._emit_scroll_anchor()

    @Property(float, notify=loopStartBeatChanged)
    def loopStartBeat(self) -> float:
        return self._loop_start_beat

    @Property(float, notify=loopEndBeatChanged)
    def loopEndBeat(self) -> float:
        return self._loop_end_beat

    @Property(str, notify=handFilterChanged)
    def handFilter(self) -> str:
        return self._hand_filter

    @handFilter.setter
    def handFilter(self, val: str):
        if val in ("both", "right", "left") and val != self._hand_filter:
            # Flush sounding notes of newly excluded hand(s) to avoid hanging notes
            self._flush_sounding_notes(excluded_hand_only=(val != "both", val))
            self._hand_filter = val
            self.handFilterChanged.emit(self._hand_filter)

    @Property(float, notify=baseBpmChanged)
    def baseBpm(self) -> float:
        """The piece's unscaled starting tempo, for UI tempo readouts."""
        return self._base_bpm

    @Property(bool, notify=metronomeEnabledChanged)
    def metronomeEnabled(self) -> bool:
        return self._metronome_enabled

    @metronomeEnabled.setter
    def metronomeEnabled(self, val: bool):
        val = bool(val)
        if self._metronome_enabled != val:
            self._metronome_enabled = val
            self.metronomeEnabledChanged.emit(self._metronome_enabled)

    # ── Public Load & Control Slots ───────────────────────────────────────────

    def load(self, steps: List[Dict[str, Any]], tempo_map: Optional[List[Dict[str, Any]]] = None,
             time_signatures: Optional[List[Dict[str, Any]]] = None,
             pedal_events: Optional[List[Dict[str, Any]]] = None):
        """Loads a piece definition and pre-compiles the flat event list."""
        self.stop()
        self._steps = steps or []
        self._tempo_map = tempo_map or []
        self._time_signatures = time_signatures or []
        self._pedal_events = pedal_events or []

        self._events = compile_events(self._steps, self._pedal_events)
        self._playback_beat = 0.0
        self._cursor = 0
        self._last_metronome_beat = -1

        # Last event beat marks the end of the piece (used to stop the transport).
        self._end_beat = float(self._events[-1][0]) if self._events else 0.0

        new_base = bpm_at(self._tempo_map, 0.0)
        if new_base != self._base_bpm:
            self._base_bpm = new_base
            self.baseBpmChanged.emit(self._base_bpm)

        self.playbackBeatChanged.emit(0.0)

    @Slot()
    def play(self):
        """Starts or resumes playback."""
        if not self._events or self._is_playing:
            return
        self._is_playing = True
        self._last_tick_time = time.perf_counter()
        self._timer.start()
        self.isPlayingChanged.emit(True)
        self._emit_scroll_anchor(snap=True, now=self._last_tick_time)

    @Slot()
    def pause(self):
        """Pauses playback and silences sounding notes."""
        if not self._is_playing:
            return
        self._timer.stop()
        self._is_playing = False
        self._flush_sounding_notes()
        self.isPlayingChanged.emit(False)
        # bps drops to 0, which parks the view exactly where the audio stopped.
        self._emit_scroll_anchor(snap=True)

    @Slot()
    def stop(self):
        """Stops playback, silences notes, and resets position."""
        if self._is_playing:
            self._timer.stop()
            self._is_playing = False
            self.isPlayingChanged.emit(False)

        self._flush_sounding_notes()
        self._playback_beat = 0.0
        self._cursor = 0
        self._last_metronome_beat = -1
        self.playbackBeatChanged.emit(0.0)
        self._emit_scroll_anchor(snap=True)

    @Slot(float)
    def seek(self, beat: float):
        """Seeks playback to a specific beat offset."""
        target_beat = max(0.0, float(beat))
        self._flush_sounding_notes()
        self._playback_beat = target_beat

        # Position cursor at first event >= target_beat
        self._cursor = 0
        while self._cursor < len(self._events) and self._events[self._cursor][0] < target_beat:
            self._cursor += 1

        # Re-arm the metronome so ticks resume after a backward seek.
        self._last_metronome_beat = math.floor(target_beat) - 1

        self.playbackBeatChanged.emit(self._playback_beat)
        self._emit_scroll_anchor(snap=True)

    @Slot()
    def setLoopA(self):
        """Sets loop start to current playback position."""
        self._loop_start_beat = round(self._playback_beat, 2)
        self.loopStartBeatChanged.emit(self._loop_start_beat)

    @Slot()
    def setLoopB(self):
        """Sets loop end to current playback position."""
        self._loop_end_beat = round(self._playback_beat, 2)
        self.loopEndBeatChanged.emit(self._loop_end_beat)

    @Slot(float, float)
    def setLoop(self, start_beat: float, end_beat: float):
        """
        Sets both loop bounds directly, for callers that know the region they
        want (e.g. ChordTrainer's "practice trouble spots" measure targeting)
        rather than marking it from the playhead.
        """
        self._loop_start_beat = round(max(0.0, float(start_beat)), 2)
        self._loop_end_beat = round(float(end_beat), 2)
        self.loopStartBeatChanged.emit(self._loop_start_beat)
        self.loopEndBeatChanged.emit(self._loop_end_beat)

    @Slot()
    def clearLoop(self):
        """Clears current A/B loop bounds."""
        self._loop_start_beat = -1.0
        self._loop_end_beat = -1.0
        self.loopStartBeatChanged.emit(-1.0)
        self.loopEndBeatChanged.emit(-1.0)

    # ── Pitch Suppression Buffer ─────────────────────────────────────────────

    def was_just_sent(self, pitch: int, window_ms: float = 80.0) -> bool:
        """
        Returns True if pitch was transmitted by the sequencer within the last window_ms.
        Used by ChordTrainerService for pitch-selective input suppression.
        """
        now = time.monotonic() * 1000.0
        # Prune entries older than window_ms
        self._sent_buffer = [e for e in self._sent_buffer if (now - e[1]) <= window_ms]
        return any(e[0] == pitch for e in self._sent_buffer)

    # ── Internal Clock & Dispatch ────────────────────────────────────────────

    def _on_tick(self):
        """Called every 10 ms by PreciseTimer during playback."""
        if not self._is_playing:
            return

        now = time.perf_counter()
        elapsed_sec = now - self._last_tick_time
        self._last_tick_time = now

        current_bpm = bpm_at(self._tempo_map, self._playback_beat)
        beat_delta = elapsed_sec * (current_bpm / 60.0) * self._tempo_scale
        next_beat = self._playback_beat + beat_delta

        # Check A/B loop wrapping boundary
        if self._loop_end_beat > self._loop_start_beat >= 0 and next_beat >= self._loop_end_beat:
            self._flush_sounding_notes()
            self._playback_beat = self._loop_start_beat
            self._cursor = 0
            while self._cursor < len(self._events) and self._events[self._cursor][0] < self._loop_start_beat:
                self._cursor += 1
            # Re-arm the metronome; without this it stays silent after the first wrap
            # because int_beat can never again exceed the pre-wrap value inside the loop.
            self._last_metronome_beat = math.floor(self._loop_start_beat) - 1
            self.playbackBeatChanged.emit(self._playback_beat)
            # A wrap is a jump backwards; the view must cut, not rewind.
            self._emit_scroll_anchor(snap=True, now=now)
            return

        # Dispatch events up to next_beat
        msgs_to_send = []
        while self._cursor < len(self._events) and self._events[self._cursor][0] <= next_beat:
            evt = self._events[self._cursor]
            beat_off, status, arg1, arg2, hand = evt

            # Filter evaluation
            if self._hand_filter == "both" or hand in ("both", self._hand_filter):
                msgs_to_send.append([status, arg1, arg2])

                if status == 0x90:  # Note On
                    self._sounding_notes.add((arg1, hand))
                    self._sent_buffer.append((arg1, time.monotonic() * 1000.0))
                elif status == 0x80:  # Note Off
                    self._sounding_notes.discard((arg1, hand))

            self._cursor += 1

        if msgs_to_send and self._hw_service:
            self._hw_service._safe_bulk_send(msgs_to_send)

        # Metronome integer-beat crossing check
        if self._metronome_enabled and self._hw_service:
            int_beat = math.floor(next_beat)
            if int_beat > self._last_metronome_beat and int_beat >= 0:
                self._last_metronome_beat = int_beat
                _, beat_num, _ = beat_to_measure_info(self._time_signatures, float(int_beat))
                self._hw_service.play_metronome_tick(beat_num)

        self._playback_beat = next_beat

        # End of piece: every event dispatched and the playhead has passed the final
        # event. Without this the transport would run forever with isPlaying stuck true.
        is_looping = self._loop_end_beat > self._loop_start_beat >= 0
        if not is_looping and self._cursor >= len(self._events) and next_beat >= self._end_beat:
            self.stop()
            self.playbackFinished.emit()
            return

        # playbackBeatChanged drives progress readouts, not the notation, so it
        # runs at ~10 Hz. It used to run at 30 Hz to animate the scroll, which
        # cost a QML binding pass three times as often for no visible gain.
        if (now - self._last_beat_signal_time) >= 0.1:
            self._last_beat_signal_time = now
            self.playbackBeatChanged.emit(self._playback_beat)

        # Re-anchor the view when its extrapolation would have gone stale:
        # either the tempo map changed the speed, or enough time has passed that
        # frame-clock drift could show. Four times a second is ample — the view
        # is computing its own position in between, not waiting on us.
        bps = self._beats_per_second()
        if abs(bps - self._last_anchor_bps) > 1e-6 or (now - self._last_anchor_time) >= 0.25:
            self._emit_scroll_anchor(now=now)

    def _flush_sounding_notes(self, excluded_hand_only: Tuple[bool, str] = (False, "")):
        """Flushes active sounding notes by transmitting explicit Note Off messages."""
        if not self._sounding_notes:
            return

        is_selective, active_filter = excluded_hand_only
        msgs = []
        to_remove = set()

        for pitch, hand in self._sounding_notes:
            if is_selective:
                # Flush notes that belong to the non-active hand
                if active_filter != "both" and hand != active_filter:
                    msgs.append([0x80, pitch, 0])
                    to_remove.add((pitch, hand))
            else:
                msgs.append([0x80, pitch, 0])
                to_remove.add((pitch, hand))

        if is_selective:
            self._sounding_notes -= to_remove
        else:
            self._sounding_notes.clear()

        if msgs and self._hw_service:
            self._hw_service._safe_bulk_send(msgs)
