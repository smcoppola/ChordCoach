"""
The per-type exercise handlers (logic/services/exercises). Chord, pentascale,
progression and song behaviour is pinned end to end in
test_trainer_characterization; this covers the registry, the flags that
replaced the trainer's type checks, and steady pulse, which nothing else runs.
"""
from unittest.mock import MagicMock

import pytest

from logic.services.chord_trainer import ChordTrainerService
from logic.services.exercises import HANDLERS, make_exercises


@pytest.fixture
def trainer(qapp):
    db = MagicMock()
    db.get_app_setting.side_effect = lambda k, d="": d
    t = ChordTrainerService(db, None, None, MagicMock())
    yield t
    t.stop_session()


def test_every_type_has_one_handler():
    types = [h.type for h in HANDLERS]
    assert len(types) == len(set(types))
    assert set(types) == {"chord", "hands_together", "sustain_pedal", "listen", "theory_concept",
                          "song_application", "pentascale", "progression", "steady_pulse"}


def test_every_type_the_sequencer_emits_has_a_handler(trainer):
    from logic.services.lesson_sequencer import build_pool
    emitted = set()
    for types in (["chord"], ["hands_together"], ["sustain_pedal"], ["listen"], ["pentascale"],
                  ["progression"], ["song_application"]):
        drills, songs = build_pool({"exercise_types": types, "target_chords": ["C Major", "A Minor"],
                                    "suggested_pieces": ["x"]})
        emitted |= {e["exercise_type"] for e in drills + songs}
    emitted.add("theory_concept")
    assert emitted <= set(make_exercises(trainer))


def test_unknown_types_fall_back_to_a_plain_chord(trainer):
    trainer._exercise_type = "key_explorer"
    assert trainer._exercise.type == "chord"


@pytest.mark.parametrize("kind,reviewable,keyboard,pedal,sorted_", [
    ("chord", True, True, False, True),
    ("hands_together", True, True, False, True),
    ("sustain_pedal", True, True, True, True),
    ("progression", True, True, False, True),
    ("listen", False, False, False, True),
    ("pentascale", False, True, False, False),
    ("steady_pulse", False, True, False, True),
    ("song_application", False, True, False, True),
    ("theory_concept", False, True, False, True),
])
def test_handler_flags(trainer, kind, reviewable, keyboard, pedal, sorted_):
    h = trainer._exercises[kind]
    assert (h.reviewable, h.keyboard_answers, h.needs_pedal, h.sorted_targets) == \
        (reviewable, keyboard, pedal, sorted_)


@pytest.mark.parametrize("wrong,label", [(0, "Excellent Timing!"), (2, "Good Pace"), (3, "Keep Practicing")])
def test_pentascale_success_labels(trainer, wrong, label):
    trainer._wrong_notes_count = wrong
    assert trainer._exercises["pentascale"].success_label() == label


# ── Steady pulse ────────────────────────────────────────────────────────────

class FakeMetronome:
    def __init__(self):
        self.started, self.deferred, self.stopped = [], [], 0
        self.currentBeatPosition = 0.0
        self.is_in_lead_in = False
        self.has_deferred = False
        self.offset = 0.0
        self.bpm = 0

    def start(self, bpm, lead_in_beats=4):
        self.started.append(bpm)

    def defer_start(self, bpm, lead_in_beats=4):
        self.deferred.append(bpm)

    def stop(self):
        self.stopped += 1

    def get_timing_offset_ms(self, index):
        return self.offset


def test_steady_pulse_scores_hits_on_the_beat_and_ends_after_the_last(trainer):
    metronome = FakeMetronome()
    trainer.metronome = metronome
    successes = []
    trainer.chordSuccess.connect(lambda name, ms: successes.append(name))

    trainer.present_exercise({"exercise_type": "steady_pulse", "exercise_name": "C on the beat",
                              "root_idx": 0, "chord_type": "Major", "bpm": 90, "pulse_count": 4})
    pulse = trainer._exercises["steady_pulse"]
    assert trainer.exerciseType == "steady_pulse"
    assert metronome.started == [90]
    assert pulse.beats == 4 and len(trainer.scrollingNotes) == 4

    for p in (60, 64, 67):
        trainer.handle_midi_note(p, True)
    assert successes == ["C Major"]
    assert pulse.hits == [0.0]

    trainer._on_metronome_tick(5)  # past the last beat
    assert metronome.stopped >= 1
    assert successes[-1] == "C Major" and len(successes) == 2  # the closing completion


def test_steady_pulse_ignores_hits_outside_the_window(trainer):
    metronome = FakeMetronome()
    metronome.offset = 450.0
    trainer.metronome = metronome
    trainer.present_exercise({"exercise_type": "steady_pulse", "exercise_name": "C on the beat",
                              "root_idx": 0, "chord_type": "Major", "bpm": 90})
    for p in (60, 64, 67):
        trainer.handle_midi_note(p, True)
    assert trainer._exercises["steady_pulse"].hits == []
