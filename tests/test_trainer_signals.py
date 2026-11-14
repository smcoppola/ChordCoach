"""
Which notify signal each trainer property rides on, and that the hot paths —
every key event, every hold-progress tick — no longer make QML re-read every
lesson property.
"""
from unittest.mock import MagicMock

import pytest
from PySide6.QtTest import QTest

from logic.services.chord_trainer import ChordTrainerService


@pytest.fixture
def trainer(qapp):
    db = MagicMock()
    db.get_app_setting.side_effect = lambda k, d="": d
    t = ChordTrainerService(db, None, None, MagicMock())
    t.counts = {}
    for name in ("lessonStateChanged", "mistakeChanged", "holdProgressChanged", "exerciseChanged",
                 "lessonProgressChanged", "struggledItemsChanged"):
        t.counts[name] = 0
        getattr(t, name).connect(lambda *a, n=name: t.counts.__setitem__(n, t.counts[n] + 1))
    yield t
    t.stop_session()


def notify_of(cls, prop):
    mo = cls.staticMetaObject
    p = mo.property(mo.indexOfProperty(prop))
    return bytes(p.notifySignal().name()).decode()


@pytest.mark.parametrize("prop,signal", [
    ("mistakeActive", "mistakeChanged"), ("holdProgress", "holdProgressChanged"),
    ("exerciseName", "exerciseChanged"), ("exerciseType", "exerciseChanged"),
    ("currentHand", "exerciseChanged"), ("requiredHoldMs", "exerciseChanged"),
    ("progressionNumerals", "exerciseChanged"), ("lessonProgress", "lessonProgressChanged"),
    ("lessonTotal", "lessonProgressChanged"), ("lessonBlocks", "lessonProgressChanged"),
    ("struggledItems", "struggledItemsChanged"), ("isPausedForSpeech", "lessonStateChanged"),
    ("isLoading", "lessonStateChanged"), ("isLessonComplete", "lessonStateChanged"),
])
def test_property_notifiers(prop, signal):
    assert notify_of(ChordTrainerService, prop) == signal


def test_a_lesson_state_change_still_refreshes_everything(trainer):
    trainer.lessonStateChanged.emit()
    assert all(n == 1 for n in trainer.counts.values()), trainer.counts


def test_a_key_press_only_refreshes_mistake_display(trainer):
    trainer.present_exercise({"exercise_type": "chord", "exercise_name": "C Major",
                              "root_idx": 0, "chord_type_name": "Major"})
    for k in trainer.counts:
        trainer.counts[k] = 0
    trainer.handle_midi_note(61, True)  # a wrong note
    assert trainer.counts["lessonStateChanged"] == 0
    assert trainer.counts["mistakeChanged"] == 1
    assert trainer.mistakeActive


def test_a_hold_ticks_progress_without_a_full_refresh(trainer):
    trainer.present_exercise({"exercise_type": "chord", "exercise_name": "C Major",
                              "root_idx": 0, "chord_type_name": "Major", "hold_ms": 300})
    for p in (60, 64, 67):
        trainer.handle_midi_note(p, True)
    for k in trainer.counts:
        trainer.counts[k] = 0
    QTest.qWait(150)
    assert trainer.counts["holdProgressChanged"] >= 2
    assert trainer.counts["lessonStateChanged"] == 0
    assert 0.0 < trainer.holdProgress < 1.0
