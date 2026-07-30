"""
===============================================================================
File: test_playback_compile.py
Description: Pure Python unit tests for PlaybackService event compiler, tempo map 
             lookup, hand filtering, loop wrapping, and metronome accent logic.
             Runs headless without requiring PySide6 / Qt.
===============================================================================
"""
import math
import time
import pytest
from logic.services.playback_service import compile_events, bpm_at, beat_to_measure_info


def test_event_compilation_and_sorting():
    """Verify event list is chronologically sorted, NOTE_OFF beats use note durations, and velocity defaults to 80."""
    steps = [
        {
            "offset": 0.0,
            "pitches": [60, 64],
            "durations": [4.0, 1.0],  # Whole note on C4, quarter note on E4
            "hands": ["left", "right"],
            "velocities": [None, 95]
        },
        {
            "offset": 1.0,
            "pitches": [67],
            "durations": [1.0],
            "hands": ["right"],
            "velocities": [85]
        }
    ]
    pedal_events = [
        {"offset": 0.0, "value": 127},
        {"offset": 3.0, "value": 0}
    ]

    events = compile_events(steps, pedal_events)

    # All events must be chronologically sorted by beat offset
    offsets = [e[0] for e in events]
    assert offsets == sorted(offsets), f"Events not sorted: {offsets}"

    # Verify event types and contents
    # At beat 0.0: Pedal Down (CC64=127), Note On 60 (vel 80), Note On 64 (vel 95)
    beat_0_events = [e for e in events if e[0] == 0.0]
    assert len(beat_0_events) == 3

    # Check Note On 60 default velocity 80
    note_60_on = [e for e in beat_0_events if len(e) >= 3 and e[1] == 0x90 and e[2] == 60][0]
    assert note_60_on[3] == 80  # Default velocity when None
    assert note_60_on[4] == "left"

    # Check Note On 64 velocity 95
    note_64_on = [e for e in beat_0_events if len(e) >= 3 and e[1] == 0x90 and e[2] == 64][0]
    assert note_64_on[3] == 95
    assert note_64_on[4] == "right"

    # At beat 1.0: Note Off 64 (duration 1.0), Note On 67
    beat_1_events = [e for e in events if e[0] == 1.0]
    note_64_off = [e for e in beat_1_events if len(e) >= 3 and e[1] == 0x80 and e[2] == 64][0]
    assert note_64_off[4] == "right"

    # At beat 4.0: Note Off 60 (duration 4.0)
    beat_4_events = [e for e in events if e[0] == 4.0]
    note_60_off = [e for e in beat_4_events if len(e) >= 3 and e[1] == 0x80 and e[2] == 60][0]
    assert note_60_off[4] == "left"


def test_tempo_map_lookup():
    """Verify piecewise-constant bpm_at lookup across tempo changes."""
    tempo_map = [
        {"offset": 0.0, "bpm": 120.0},
        {"offset": 4.0, "bpm": 90.0},
        {"offset": 8.0, "bpm": 140.0}
    ]

    assert bpm_at(tempo_map, 0.0) == 120.0
    assert bpm_at(tempo_map, 2.5) == 120.0
    assert bpm_at(tempo_map, 4.0) == 90.0
    assert bpm_at(tempo_map, 6.0) == 90.0
    assert bpm_at(tempo_map, 8.0) == 140.0
    assert bpm_at(tempo_map, 12.0) == 140.0

    # Empty or single entry fallback
    assert bpm_at([], 5.0) == 100.0
    assert bpm_at([{"offset": 0.0, "bpm": 80.0}], 5.0) == 80.0


def test_hand_filtering_at_compile_and_dispatch():
    """Verify filtered-out hands drop both Note On and Note Off events."""
    steps = [
        {
            "offset": 0.0,
            "pitches": [48, 72],
            "durations": [2.0, 1.0],
            "hands": ["left", "right"],
            "velocities": [80, 80]
        }
    ]
    events = compile_events(steps, [])

    # Filter for right hand only
    rh_events = [e for e in events if e[4] in ("right", "both")]
    rh_pitches = [e[2] for e in rh_events if e[1] in (0x90, 0x80)]
    assert set(rh_pitches) == {72}
    assert 48 not in rh_pitches

    # Filter for left hand only
    lh_events = [e for e in events if e[4] in ("left", "both")]
    lh_pitches = [e[2] for e in lh_events if e[1] in (0x90, 0x80)]
    assert set(lh_pitches) == {48}
    assert 72 not in lh_pitches


def test_metronome_accent_pattern():
    """Verify 1-based measure beat calculation and downbeat detection for 3/4, 4/4, and 6/8."""
    # 4/4 Time signature starting at beat 0
    ts_4_4 = [{"offset": 0.0, "numerator": 4, "denominator": 4}]
    # Beat 0 -> measure 0, beat 1, downbeat True
    m_idx, b_num, is_down = beat_to_measure_info(ts_4_4, 0.0)
    assert (m_idx, b_num, is_down) == (0, 1, True)

    # Beat 1 -> measure 0, beat 2, downbeat False
    m_idx, b_num, is_down = beat_to_measure_info(ts_4_4, 1.0)
    assert (m_idx, b_num, is_down) == (0, 2, False)

    # Beat 4 -> measure 1, beat 1, downbeat True
    m_idx, b_num, is_down = beat_to_measure_info(ts_4_4, 4.0)
    assert (m_idx, b_num, is_down) == (1, 1, True)

    # 3/4 Time signature (3 beats per bar)
    ts_3_4 = [{"offset": 0.0, "numerator": 3, "denominator": 4}]
    m_idx, b_num, is_down = beat_to_measure_info(ts_3_4, 3.0)
    assert (m_idx, b_num, is_down) == (1, 1, True)
    m_idx, b_num, is_down = beat_to_measure_info(ts_3_4, 5.0)
    assert (m_idx, b_num, is_down) == (1, 3, False)

    # 6/8 Time signature (6 eighth notes per bar, each eighth note is 0.5 beat)
    ts_6_8 = [{"offset": 0.0, "numerator": 6, "denominator": 8}]
    # Measure length = 6 * (4/8) = 3.0 beats
    m_idx, b_num, is_down = beat_to_measure_info(ts_6_8, 0.0)
    assert (m_idx, b_num, is_down) == (0, 1, True)
    m_idx, b_num, is_down = beat_to_measure_info(ts_6_8, 3.0)
    assert (m_idx, b_num, is_down) == (1, 1, True)


class FakeHardware:
    """Minimal stand-in for MidiHardwareService, recording what the sequencer sends."""

    def __init__(self):
        self.sent = []
        self.metronome_beats = []

    def _safe_bulk_send(self, messages):
        self.sent.extend(messages)

    def play_metronome_tick(self, beat_num):
        self.metronome_beats.append(beat_num)


def _make_service(steps=None, tempo_map=None, time_signatures=None):
    """Builds a PlaybackService wired to FakeHardware. QObject works headlessly."""
    from logic.services.playback_service import PlaybackService
    hw = FakeHardware()
    svc = PlaybackService(hw)
    if steps is not None:
        svc.load(steps, tempo_map or [{"offset": 0.0, "bpm": 120.0}],
                 time_signatures or [{"offset": 0.0, "numerator": 4, "denominator": 4}], [])
    return svc, hw


def _tick_with_elapsed(svc, seconds):
    """Drives one _on_tick as though `seconds` of wall-clock had passed."""
    svc._last_tick_time = time.perf_counter() - seconds
    svc._on_tick()


def test_hand_filter_change_flushes_excluded_hand():
    """Switching hands mid-playback must send note-offs for the newly excluded hand."""
    svc, hw = _make_service()
    svc._sounding_notes = {(60, "left"), (72, "right")}

    svc.handFilter = "right"

    assert [0x80, 60, 0] in hw.sent, "left-hand note should have been flushed"
    assert not any(m[1] == 72 for m in hw.sent), "right-hand note must keep sounding"
    assert svc._sounding_notes == {(72, "right")}


def test_metronome_rearms_after_loop_wrap():
    """Regression: metronome went permanently silent after the first A/B loop wrap."""
    steps = [{"offset": float(i), "pitches": [60], "durations": [1.0],
              "hands": ["right"], "velocities": [80]} for i in range(12)]
    svc, hw = _make_service(steps)

    svc._loop_start_beat = 4.0
    svc._loop_end_beat = 8.0
    svc.metronomeEnabled = True
    svc._playback_beat = 7.9
    svc._last_metronome_beat = 7  # as if ticks had advanced to beat 7
    svc._is_playing = True

    _tick_with_elapsed(svc, 0.5)  # enough to cross loop end

    assert svc._playback_beat == 4.0, "should have wrapped to loop start"
    assert svc._last_metronome_beat < 4, "metronome must be re-armed below loop start"

    # Ticks must actually resume inside the loop.
    hw.metronome_beats.clear()
    for _ in range(6):
        _tick_with_elapsed(svc, 0.3)
    assert hw.metronome_beats, "metronome should tick again after wrapping"


def test_metronome_rearms_after_backward_seek():
    """A backward seek must also re-arm the metronome."""
    svc, _ = _make_service()
    svc._last_metronome_beat = 40
    svc.seek(8.0)
    assert svc._last_metronome_beat < 8


def test_playback_stops_at_end_of_piece():
    """Regression: transport ran forever with isPlaying stuck true past the last event."""
    steps = [{"offset": 0.0, "pitches": [60], "durations": [1.0],
              "hands": ["right"], "velocities": [80]}]
    svc, _ = _make_service(steps)

    finished = []
    svc.playbackFinished.connect(lambda: finished.append(True))

    svc._is_playing = True
    for _ in range(10):
        _tick_with_elapsed(svc, 0.5)
        if not svc.isPlaying:
            break

    assert not svc.isPlaying, "playback should stop once the piece ends"
    assert finished == [True], "playbackFinished should fire exactly once"


def test_base_bpm_derived_from_tempo_map():
    """baseBpm must reflect the piece's starting tempo for the UI readout."""
    steps = [{"offset": 0.0, "pitches": [60], "durations": [1.0],
              "hands": ["right"], "velocities": [80]}]
    svc, _ = _make_service(steps, tempo_map=[{"offset": 0.0, "bpm": 76.0},
                                             {"offset": 8.0, "bpm": 120.0}])
    assert svc.baseBpm == 76.0
