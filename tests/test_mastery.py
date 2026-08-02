"""
Phase 4 mastery-recording tests.

Covers the two mastery formulas, that `record_song_play` is called exactly once
per completion with the song id, and the pacing/hand-filter plumbing around it.
The DB is a stub throughout — nothing here touches live user data.
"""
import pytest

from logic.services.chord_trainer import ChordTrainerService


# ── Test doubles ────────────────────────────────────────────────────────────

class SpyDB:
    """Records record_song_play calls; stubs the rest of the trainer's DB use."""

    def __init__(self):
        self.song_plays = []
        self.settings = {}
        self.chord_attempts = []

    def record_song_play(self, filepath, title, mastery_gained):
        self.song_plays.append({
            "filepath": filepath,
            "title": title,
            "mastery_gained": mastery_gained,
        })

    def record_chord_attempt(self, *args, **kwargs):
        self.chord_attempts.append((args, kwargs))

    def get_app_setting(self, key, default=""):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = str(value)


class SpyMusic21:
    """Minimal Music21Service stand-in with an in-memory per-song pref store."""

    def __init__(self, song_data=None):
        self.prefs = {}
        self.song_data = song_data or {}

    def get_user_song_pref(self, song_id, key, default=""):
        return self.prefs.get((song_id, key), default)

    def set_user_song_pref(self, song_id, key, value):
        self.prefs[(song_id, key)] = value

    def load_song_as_steps(self, piece_name):
        return self.song_data


class SpyPlayback:
    def __init__(self):
        self.isPlaying = False
        self.handFilter = "both"
        self.tempoScale = 1.0
        self.loopStartBeat = -1.0
        self.loopEndBeat = -1.0
        self.loaded = None

    def load(self, steps, tempo_map=None, time_signatures=None, pedal_events=None):
        self.loaded = {"steps": steps, "tempo_map": tempo_map}

    def setLoop(self, start_beat, end_beat):
        self.loopStartBeat = start_beat
        self.loopEndBeat = end_beat

    def was_just_sent(self, pitch, window_ms=80.0):
        return False


def sample_song():
    """Four quarter-note steps in 4/4: RH melody over an LH bass, two measures."""
    steps = []
    for i in range(4):
        steps.append({
            "offset": float(i),
            "duration": 1.0,
            "pitches": [60 + i, 48 + i],
            "hands": ["right", "left"],
            "fingers": [1, 5],
            "durations": [1.0, 1.0],
            "spellings": [None, None],
            "ties": [None, None],
            "beams": [None, None],
        })
    return {
        "steps": steps,
        "title": "Test Piece",
        "composer": "Nobody",
        "key": "C major",
        "key_sharps": 0,
        "tempo_map": [{"offset": 0.0, "bpm": 90.0}],
        "time_signatures": [{"offset": 0.0, "numerator": 2, "denominator": 4}],
        "barlines": [2.0],
        "pedal_events": [],
        "dynamics": [],
    }


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def trainer():
    db = SpyDB()
    music21 = SpyMusic21(sample_song())
    svc = ChordTrainerService(db, curriculum_service=None,
                              settings_manager=None, music21_service=music21)
    svc.set_playback_service(SpyPlayback())
    svc.db_spy = db
    svc.music21_spy = music21
    yield svc
    svc._rhythm_engine.stop()


# ── Defaults ────────────────────────────────────────────────────────────────

def test_never_played_song_starts_self_paced(trainer):
    trainer.start_song("user::never-played-1")

    assert trainer.pacingMode == "self_paced"
    assert trainer.practiceHands == "both"
    # The protected path is live and the renderer gets no state array.
    assert list(trainer.songNoteStates) == []
    assert trainer.scrollBpm == 0
    assert trainer._target_pitches  # _advance_song_chord ran


def test_a_second_never_played_song_still_defaults_to_self_paced(trainer):
    trainer.start_song("user::song-a")
    trainer.set_pacing_mode("rhythm")
    assert trainer.pacingMode == "rhythm"

    trainer.start_song("user::song-b")
    assert trainer.pacingMode == "self_paced"


# ── Persistence ─────────────────────────────────────────────────────────────

def test_mode_persists_per_user_song(trainer):
    trainer.start_song("user::persist-me")
    trainer.set_pacing_mode("rhythm")

    assert trainer.music21_spy.prefs[("user::persist-me", "practice_mode")] == "rhythm"

    # Simulate an app restart: a fresh service reading the same store.
    fresh = ChordTrainerService(trainer.db_spy, None, None, trainer.music21_spy)
    fresh.set_playback_service(SpyPlayback())
    fresh.start_song("user::persist-me")
    assert fresh.pacingMode == "rhythm"
    fresh._rhythm_engine.stop()


def test_mode_persists_for_corpus_songs_via_app_settings(trainer):
    trainer.start_song("bach/bwv1.6.mxl")
    trainer.set_pacing_mode("rhythm")

    assert trainer.db_spy.settings["practice_mode::bach/bwv1.6.mxl"] == "rhythm"

    fresh = ChordTrainerService(trainer.db_spy, None, None, trainer.music21_spy)
    fresh.set_playback_service(SpyPlayback())
    fresh.start_song("bach/bwv1.6.mxl")
    assert fresh.pacingMode == "rhythm"
    fresh._rhythm_engine.stop()


def test_practice_hands_persist(trainer):
    trainer.start_song("user::hands")
    trainer.set_practice_hands("right")
    assert trainer.music21_spy.prefs[("user::hands", "practice_hands")] == "right"
    assert trainer.practiceHands == "right"


# ── Hand filtering ──────────────────────────────────────────────────────────

def test_right_hand_practice_drops_left_hand_pitches_from_targets(trainer):
    trainer.start_song("user::hands-rh")
    trainer.set_practice_hands("right")

    # Every remaining target is a RH pitch; the LH bass notes are gone.
    for step in trainer._song_steps:
        assert step["hands"] == ["right"]
        assert step["pitches"][0] >= 60
        assert len(step["fingers"]) == len(step["pitches"])


def test_steps_with_no_notes_for_the_practised_hand_are_skipped(trainer):
    song = sample_song()
    # Make step 2 left-hand only.
    song["steps"][2] = {
        "offset": 2.0, "duration": 1.0,
        "pitches": [50], "hands": ["left"], "fingers": [5], "durations": [1.0],
    }
    trainer.music21_spy.song_data = song

    trainer.start_song("user::skip-lh")
    trainer.set_practice_hands("right")

    offsets = [s["offset"] for s in trainer._song_steps]
    assert 2.0 not in offsets
    assert offsets == [0.0, 1.0, 3.0]


def test_rest_only_steps_never_become_self_paced_targets(trainer):
    """
    Both loaders emit a pitchless step wherever a rest starts with nothing
    sounding under it. Self-paced mode used to stop dead on one: _check_chord
    bails on an empty target, so no key the student could press would advance
    the song.
    """
    song = sample_song()
    song["steps"].insert(2, {
        "offset": 1.5, "duration": 0.5,
        "pitches": [], "hands": [], "fingers": [], "durations": [],
        "rests": [{"duration": 0.5, "hand": "right"}],
    })
    trainer.music21_spy.song_data = song

    trainer.start_song("user::rest-gap")

    assert all(s["pitches"] for s in trainer._song_steps)
    assert 1.5 not in [s["offset"] for s in trainer._song_steps]
    # The rest still draws — only the input gate skips it.
    assert any(n.get("is_rest") for n in trainer.scrollingNotes)


def test_a_rest_step_does_not_stall_playing_the_song_through(trainer):
    song = sample_song()
    song["steps"].insert(2, {
        "offset": 1.5, "duration": 0.5,
        "pitches": [], "hands": [], "fingers": [], "durations": [],
        "rests": [{"duration": 0.5, "hand": "right"}],
    })
    trainer.music21_spy.song_data = song
    trainer.start_song("user::rest-playthrough")

    for i in range(4):
        assert trainer._target_pitches, f"stalled before step {i}"
        for pitch in list(trainer._target_pitches):
            trainer.handle_midi_note(pitch, True)
        for pitch in [60 + i, 48 + i]:
            trainer.handle_midi_note(pitch, False)

    assert trainer.isSongCompleted


def test_a_song_with_nothing_playable_reports_instead_of_hanging(trainer):
    song = sample_song()
    song["steps"] = [{
        "offset": 0.0, "duration": 1.0,
        "pitches": [], "hands": [], "fingers": [], "durations": [],
        "rests": [{"duration": 1.0, "hand": "right"}],
    }]
    trainer.music21_spy.song_data = song

    messages = []
    trainer.statusMessageRequested.connect(lambda kind, text: messages.append((kind, text)))

    trainer.start_song("user::all-rests")

    assert trainer._song_steps == []
    assert not trainer._target_pitches
    assert messages, "the student was left with no feedback"


def test_playback_keeps_the_unfiltered_steps_for_duet(trainer):
    trainer.start_song("user::duet")
    trainer.set_practice_hands("right")

    # The app still has both hands available to play the accompaniment.
    loaded = trainer._playback_service.loaded["steps"]
    assert any("left" in s.get("hands", []) for s in loaded)


# ── Rhythm mode wiring ──────────────────────────────────────────────────────

def test_rhythm_mode_starts_the_engine_and_populates_note_states(trainer):
    trainer.start_song("user::rhythm-1")
    trainer.set_pacing_mode("rhythm")

    engine = trainer._rhythm_engine
    assert engine.isRunning
    assert engine.currentBeat == -4.0  # 4-beat count-in
    assert engine.tempoBpm == pytest.approx(90.0)  # from tempo_map[0]

    # One engine entry per pitch, mapped into the scrollingNotes array.
    assert len(engine.notes) == 8
    assert len(trainer.songNoteStates) == len(trainer.scrollingNotes)
    assert trainer.songNoteStates.count("pending") == 8


def test_rhythm_tempo_follows_the_playback_tempo_scale(trainer):
    trainer._playback_service.tempoScale = 0.5
    trainer.start_song("user::slow")
    trainer.set_pacing_mode("rhythm")

    assert trainer._rhythm_engine.tempoBpm == pytest.approx(45.0)


def test_rhythm_mode_gate_routes_input_away_from_the_self_paced_path(trainer):
    trainer.start_song("user::gate")
    trainer.set_pacing_mode("rhythm")

    engine = trainer._rhythm_engine
    engine._current_beat = 0.0

    before_index = trainer._song_index
    trainer.handle_midi_note(60, True)

    # Scored by the engine...
    assert engine.noteStates[engine.notes.index(
        next(n for n in engine.notes if n["pitch"] == 60))] == "hit"
    # ...and the self-paced machinery never moved.
    assert trainer._song_index == before_index
    assert trainer._active_pitches == set()
    assert not trainer.mistakeActive


def test_note_states_reach_the_renderer_array_at_the_right_index(trainer):
    trainer.start_song("user::states")
    trainer.set_pacing_mode("rhythm")

    engine = trainer._rhythm_engine
    engine._current_beat = 0.0
    trainer.handle_midi_note(60, True)

    hit_indices = [i for i, s in enumerate(trainer.songNoteStates) if s == "hit"]
    assert len(hit_indices) == 1
    assert trainer.scrollingNotes[hit_indices[0]]["pitch"] == 60


def test_switching_back_to_self_paced_stops_the_engine_and_clears_states(trainer):
    trainer.start_song("user::switch")
    trainer.set_pacing_mode("rhythm")
    assert trainer._rhythm_engine.isRunning

    trainer.set_pacing_mode("self_paced")
    assert not trainer._rhythm_engine.isRunning
    assert list(trainer.songNoteStates) == []
    assert trainer._rhythm_sn_index == []
    assert trainer._target_pitches  # self-paced targets are live again


def test_rhythm_mode_only_scores_the_practised_hand(trainer):
    trainer.start_song("user::rh-only")
    trainer.set_practice_hands("right")
    trainer.set_pacing_mode("rhythm")

    engine = trainer._rhythm_engine
    assert len(engine.notes) == 4
    assert all(n["hand"] == "right" for n in engine.notes)


# ── Mastery formulas ────────────────────────────────────────────────────────

@pytest.mark.parametrize("accuracy,expected", [
    (1.0, 10.0),
    (0.8, 6.4),
    (0.5, 2.5),
    (0.0, 0.0),
])
def test_rhythm_mastery_is_accuracy_squared_times_ten(trainer, accuracy, expected):
    trainer.start_song("user::mastery")
    trainer.set_pacing_mode("rhythm")

    trainer._on_rhythm_finished(accuracy, 8, 0)

    assert len(trainer.db_spy.song_plays) == 1
    assert trainer.db_spy.song_plays[0]["mastery_gained"] == pytest.approx(expected)


def test_loop_only_rhythm_run_halves_the_mastery(trainer):
    trainer._playback_service.loopStartBeat = 0.0
    trainer._playback_service.loopEndBeat = 2.0

    trainer.start_song("user::loop")
    trainer.set_pacing_mode("rhythm")
    assert trainer._rhythm_loop_only

    trainer._on_rhythm_finished(1.0, 4, 0)
    assert trainer.db_spy.song_plays[0]["mastery_gained"] == pytest.approx(5.0)


@pytest.mark.parametrize("wrong_notes,expected", [
    (0, 3.0),
    (1, 2.0),
    (2, 1.0),
    (5, 1.0),   # floor of 1
    (50, 1.0),
])
def test_self_paced_mastery_is_three_minus_wrong_notes_floored_at_one(
        trainer, wrong_notes, expected):
    trainer.start_song("user::selfpaced-mastery")
    trainer._song_wrong_notes = wrong_notes

    trainer._on_song_finished()

    assert len(trainer.db_spy.song_plays) == 1
    assert trainer.db_spy.song_plays[0]["mastery_gained"] == pytest.approx(expected)


# ── record_song_play call contract ──────────────────────────────────────────

def test_record_song_play_is_called_once_per_completion_with_the_song_id(trainer):
    trainer.start_song("user::once")
    trainer.set_pacing_mode("rhythm")

    trainer._on_rhythm_finished(0.75, 6, 2)

    assert len(trainer.db_spy.song_plays) == 1
    call = trainer.db_spy.song_plays[0]
    assert call["filepath"] == "user::once"
    assert call["title"] == "Test Piece"


def test_corpus_completion_records_under_the_corpus_id(trainer):
    trainer.start_song("bach/bwv1.6.mxl")
    trainer._song_wrong_notes = 0
    trainer._on_song_finished()

    assert trainer.db_spy.song_plays[0]["filepath"] == "bach/bwv1.6.mxl"


def test_song_result_summary_is_published_for_the_overlay(trainer):
    trainer.start_song("user::overlay")
    trainer.set_pacing_mode("rhythm")

    trainer._on_rhythm_finished(0.5, 4, 4)

    result = trainer.songResult
    assert result["mode"] == "rhythm"
    assert result["hits"] == 4
    assert result["misses"] == 4
    assert result["accuracy"] == pytest.approx(0.5)
    assert result["masteryGained"] == pytest.approx(2.5)
    assert result["title"] == "Test Piece"
    assert trainer.isSongCompleted


def test_completion_with_no_song_id_does_not_write_a_row(trainer):
    trainer._song_id = ""
    trainer._song_title = "Orphan"
    trainer._record_song_completion(5.0, {"mode": "rhythm"})

    assert trainer.db_spy.song_plays == []
    assert trainer.songResult["mode"] == "rhythm"


# ── Trouble spots ───────────────────────────────────────────────────────────

def test_practice_trouble_spots_loops_the_worst_measure(trainer):
    trainer.start_song("user::trouble")
    trainer.set_pacing_mode("rhythm")

    # 2/4 time with a barline at beat 2 -> measure 1 = [0,2), measure 2 = [2,4).
    # Mark both notes of the second measure as missed.
    engine = trainer._rhythm_engine
    for i, note in enumerate(engine.notes):
        if note["start_beat"] >= 2.0:
            trainer._on_rhythm_note_state(i, "miss")

    measure = trainer.practice_trouble_spots()

    assert measure == 2
    assert trainer._playback_service.loopStartBeat == pytest.approx(2.0)
    assert trainer._playback_service.loopEndBeat == pytest.approx(4.0)


def test_practice_trouble_spots_is_a_no_op_with_no_misses(trainer):
    trainer.start_song("user::clean")
    trainer.set_pacing_mode("rhythm")

    assert trainer.practice_trouble_spots() == 0
    assert trainer._playback_service.loopStartBeat == -1.0
