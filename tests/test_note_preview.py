"""
Preview playback for the song editor: hearing a note, or a bar, while editing.

Two halves. `preview_schedule` is pure, so its timing rules — the clamping of a
note tied in from the previous bar, the clipping at the bar edge, the tempo
fallbacks — are pinned exactly. The service half pins the property that actually
matters at the keyboard: every note that goes down comes back up, including when
the preview is abandoned part-way through, because a stuck note outlives the
popup that caused it.
"""

import pytest

from hardware.midi_hardware_service import (
    PREVIEW_FALLBACK_BPM,
    PREVIEW_MAX_BPM,
    PREVIEW_MIN_BPM,
    MidiHardwareService,
    preview_schedule,
)

# At 100bpm a quarter note is 600ms.
BPM = 100.0
BEAT_MS = 600.0


def _note(pitch, beat, duration):
    return {"pitch": pitch, "beat": beat, "duration": duration}


# --- The schedule ----------------------------------------------------------

def test_no_notes_schedules_nothing():
    assert preview_schedule([], 0.0, 4.0, BPM) == []
    assert preview_schedule(None, 0.0, 4.0, BPM) == []


def test_a_single_note_starts_now_and_lasts_its_length():
    [event] = preview_schedule([_note(60, 0.0, 1.0)], 0.0, 1.0, BPM)

    assert event["pitch"] == 60
    assert event["on_ms"] == 0.0
    assert event["off_ms"] == BEAT_MS


def test_onsets_are_relative_to_the_window_not_the_song():
    [event] = preview_schedule([_note(60, 9.0, 1.0)], 8.0, 12.0, BPM)

    assert event["on_ms"] == BEAT_MS
    assert event["off_ms"] == 2 * BEAT_MS


def test_a_note_tied_in_from_the_previous_bar_sounds_with_the_bar():
    """Starts before the window and is still ringing — clamp, do not drop."""
    [event] = preview_schedule([_note(60, 2.0, 4.0)], 4.0, 8.0, BPM)

    assert event["on_ms"] == 0.0
    assert event["off_ms"] == 2 * BEAT_MS


def test_a_note_running_past_the_bar_stops_at_its_edge():
    [event] = preview_schedule([_note(60, 3.0, 8.0)], 0.0, 4.0, BPM)

    assert event["off_ms"] == 4 * BEAT_MS


def test_a_note_finishing_before_the_window_is_dropped():
    assert preview_schedule([_note(60, 0.0, 1.0)], 4.0, 8.0, BPM) == []


def test_a_note_starting_after_the_window_is_dropped():
    assert preview_schedule([_note(60, 20.0, 1.0)], 0.0, 4.0, BPM) == []


def test_a_zero_length_note_is_dropped_rather_than_stuck_on():
    assert preview_schedule([_note(60, 0.0, 0.0)], 0.0, 4.0, BPM) == []


def test_an_empty_window_schedules_nothing():
    assert preview_schedule([_note(60, 0.0, 1.0)], 4.0, 4.0, BPM) == []
    assert preview_schedule([_note(60, 0.0, 1.0)], 8.0, 4.0, BPM) == []


def test_a_chord_sounds_together_in_pitch_order():
    events = preview_schedule([_note(64, 0.0, 1.0), _note(60, 0.0, 1.0)], 0.0, 4.0, BPM)

    assert [e["pitch"] for e in events] == [60, 64]
    assert {e["on_ms"] for e in events} == {0.0}


def test_events_come_back_in_playing_order():
    events = preview_schedule(
        [_note(67, 2.0, 1.0), _note(60, 0.0, 1.0), _note(64, 1.0, 1.0)], 0.0, 4.0, BPM
    )

    assert [e["pitch"] for e in events] == [60, 64, 67]


def test_tempo_scales_the_whole_schedule():
    [slow] = preview_schedule([_note(60, 0.0, 1.0)], 0.0, 4.0, 60.0)
    [fast] = preview_schedule([_note(60, 0.0, 1.0)], 0.0, 4.0, 120.0)

    assert slow["off_ms"] == 1000.0
    assert fast["off_ms"] == 500.0


@pytest.mark.parametrize("bad", [0, -120.0, None, "", "fast", float("nan")])
def test_an_unusable_tempo_falls_back_rather_than_dividing_by_zero(bad):
    [event] = preview_schedule([_note(60, 0.0, 1.0)], 0.0, 4.0, bad)

    assert event["off_ms"] == pytest.approx(60000.0 / PREVIEW_FALLBACK_BPM)


def test_an_absurd_tempo_is_clamped_into_range():
    [crawling] = preview_schedule([_note(60, 0.0, 1.0)], 0.0, 4.0, 0.5)
    [racing] = preview_schedule([_note(60, 0.0, 1.0)], 0.0, 4.0, 100000.0)

    assert crawling["off_ms"] == pytest.approx(60000.0 / PREVIEW_MIN_BPM)
    assert racing["off_ms"] == pytest.approx(60000.0 / PREVIEW_MAX_BPM)


def test_a_long_preview_is_truncated():
    events = preview_schedule([_note(60, 0.0, 40.0)], 0.0, 40.0, BPM, max_ms=2000.0)

    assert events[0]["off_ms"] == 2000.0


def test_notes_beginning_past_the_cutoff_are_dropped_entirely():
    events = preview_schedule(
        [_note(60, 0.0, 1.0), _note(72, 30.0, 1.0)], 0.0, 40.0, BPM, max_ms=2000.0
    )

    assert [e["pitch"] for e in events] == [60]


@pytest.mark.parametrize(
    "bad",
    [
        {"beat": 0.0, "duration": 1.0},          # no pitch
        {"pitch": "C4", "beat": 0.0, "duration": 1.0},
        {"pitch": 200, "beat": 0.0, "duration": 1.0},
        {"pitch": -1, "beat": 0.0, "duration": 1.0},
    ],
)
def test_a_malformed_note_is_skipped_not_fatal(bad):
    events = preview_schedule([bad, _note(60, 0.0, 1.0)], 0.0, 4.0, BPM)

    assert [e["pitch"] for e in events] == [60]


# --- The service -----------------------------------------------------------

class _FakeMidiOut:
    """Records what would reach the wire. `_port_open` mirrors the real class."""

    def __init__(self):
        self.messages = []
        self._port_open = True

    def send_message(self, message):
        self.messages.append(list(message))


@pytest.fixture
def service(qapp):
    return MidiHardwareService(None, None, midi_out_enabled=False)


def _drain(qapp, ms):
    """Runs the event loop for `ms`, so QTimer.singleShot callbacks actually fire."""
    from PySide6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(int(ms))
    while not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)


def _notes_of(messages, status):
    return [m[1] for m in messages if m[0] == status]


def test_preview_without_hardware_is_a_silent_no_op(service):
    service.play_preview([_note(60, 0.0, 1.0)], 0.0, 1.0, BPM)
    service.stop_preview()  # must not raise either


def test_a_previewed_note_is_released(service, qapp):
    service._ll_midi_out = _FakeMidiOut()

    service.play_preview([_note(60, 0.0, 0.25)], 0.0, 0.25, BPM)
    _drain(qapp, 500)

    assert _notes_of(service._ll_midi_out.messages, 0x90) == [60]
    assert _notes_of(service._ll_midi_out.messages, 0x80) == [60]


def test_every_note_of_a_bar_is_released(service, qapp):
    service._ll_midi_out = _FakeMidiOut()

    service.play_preview(
        [_note(60, 0.0, 0.25), _note(64, 0.25, 0.25), _note(67, 0.5, 0.25)],
        0.0, 1.0, 240.0,
    )
    _drain(qapp, 800)

    sent = service._ll_midi_out.messages
    assert sorted(_notes_of(sent, 0x90)) == [60, 64, 67]
    assert sorted(_notes_of(sent, 0x80)) == [60, 64, 67]


def test_stopping_mid_preview_releases_what_is_sounding(service, qapp):
    service._ll_midi_out = _FakeMidiOut()

    service.play_preview([_note(60, 0.0, 8.0)], 0.0, 8.0, 30.0)
    _drain(qapp, 150)
    assert _notes_of(service._ll_midi_out.messages, 0x90) == [60]

    service.stop_preview()
    _drain(qapp, 150)

    assert _notes_of(service._ll_midi_out.messages, 0x80) == [60]


def test_stopping_suppresses_the_rest_of_the_schedule(service, qapp):
    service._ll_midi_out = _FakeMidiOut()

    service.play_preview(
        [_note(60, 0.0, 0.5), _note(72, 4.0, 0.5)], 0.0, 8.0, 120.0
    )
    _drain(qapp, 100)
    service.stop_preview()
    _drain(qapp, 2500)

    assert 72 not in _notes_of(service._ll_midi_out.messages, 0x90)


def test_a_new_preview_cancels_the_one_before_it(service, qapp):
    service._ll_midi_out = _FakeMidiOut()

    service.play_preview([_note(60, 0.0, 8.0)], 0.0, 8.0, 30.0)
    _drain(qapp, 150)
    service.play_preview([_note(72, 0.0, 0.25)], 0.0, 0.25, 240.0)
    _drain(qapp, 500)

    sent = service._ll_midi_out.messages
    # The held note was released by the interrupting preview, not left ringing.
    assert 60 in _notes_of(sent, 0x80)
    assert sorted(_notes_of(sent, 0x80)) == [60, 72]


def test_stopping_when_nothing_is_playing_sends_nothing(service, qapp):
    service._ll_midi_out = _FakeMidiOut()

    service.stop_preview()
    _drain(qapp, 100)

    assert service._ll_midi_out.messages == []
