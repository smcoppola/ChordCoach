"""
Free play must not hold a coach session open.

The coach is never consulted during free play, but the websocket used to stay up
through the whole piece. When it dropped, the retry loop armed and put a
full-screen "RECONNECTING TO YOUR COACH..." overlay on top of the notation —
directly over the music the user was reading.

So free play now releases the session and restores it on the way out. The
release is easy; the part worth testing is the restore, because a coach that
fails to come back leaves every subsequent lesson silently broken.
"""

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from logic.coordinators.app_coordinator import AppCoordinator
from logic.services.chord_trainer import ChordTrainerService


# --- The trainer's own signalling ------------------------------------------

@pytest.fixture
def trainer(qapp):
    """A bare trainer. Every collaborator it takes is optional."""
    return ChordTrainerService(db_manager=MagicMock())


def _record(trainer):
    seen = []
    trainer.coachNeededChanged.connect(seen.append)
    return seen


def test_coach_starts_out_needed(trainer):
    """Everything except free play wants a coach, so that is the default."""
    assert trainer.coachNeeded is True


def test_free_play_releases_the_coach(trainer, monkeypatch):
    monkeypatch.setattr(trainer, "_apply_step", lambda step: None)
    seen = _record(trainer)

    trainer.start_song("some-piece")

    assert trainer.coachNeeded is False
    assert seen == [False]


def test_leaving_free_play_restores_the_coach(trainer, monkeypatch):
    monkeypatch.setattr(trainer, "_apply_step", lambda step: None)
    trainer.start_song("some-piece")
    seen = _record(trainer)

    trainer.stop_session()

    assert trainer.coachNeeded is True
    assert seen == [True]


def test_restore_happens_even_when_already_idle(trainer, monkeypatch):
    """
    stop_session's main body is guarded on the session being active.

    Returning to the dashboard can reach it with the trainer already idle, and
    if the restore sat inside that guard the coach would stay released and every
    later lesson would start with no session.
    """
    monkeypatch.setattr(trainer, "_apply_step", lambda step: None)
    trainer.start_song("some-piece")
    trainer._set_state(trainer._state.__class__.IDLE)
    assert not trainer.isActive

    trainer.stop_session()

    assert trainer.coachNeeded is True


def test_starting_a_lesson_restores_the_coach(trainer, monkeypatch):
    """A lesson is entirely coach-driven, so it must never begin released."""
    monkeypatch.setattr(trainer, "_apply_step", lambda step: None)
    trainer.start_song("some-piece")
    assert trainer.coachNeeded is False

    monkeypatch.setattr(trainer, "_build_lesson_prompt", lambda *a, **k: "go", raising=False)
    try:
        trainer.start_lesson_plan(10)
    except Exception:
        # The prompt-building path pulls in curriculum state this bare trainer
        # does not have. The engagement flip happens first, which is the point.
        pass

    assert trainer.coachNeeded is True


def test_replaying_a_piece_does_not_rerelease(trainer, monkeypatch):
    """
    start_song runs again on every replay.

    Re-emitting would churn the websocket: the coordinator would release an
    already-released session on each restart.
    """
    monkeypatch.setattr(trainer, "_apply_step", lambda step: None)
    trainer.start_song("some-piece")
    seen = _record(trainer)

    trainer.start_song("some-piece")
    trainer.start_song("another-piece")

    assert seen == [], "a repeated free-play start re-announced the same state"


# --- The coordinator's policy ----------------------------------------------

class _StubTrainer(QObject):
    """Just the surface AppCoordinator touches for this behaviour."""
    coachNeededChanged = Signal(bool)
    requestLessonStart = Signal(str)
    reportPerformance = Signal(dict)
    exerciseRequestUnlocked = Signal()
    speakInstruction = Signal(str)
    speakBrief = Signal(str)
    apiConnectivityChanged = Signal(bool)
    isCircleOfFifthsModeChanged = Signal(bool)
    theoryVisualDirect = Signal(dict)
    midiOutRequested = Signal(list)
    metronomeTick = Signal()
    rhythmCountInTick = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self.coachNeeded = True

    # Slots the coordinator connects hardware and AI events to. Not exercised
    # here, but they have to exist for the wiring to succeed.
    def handle_pedal_event(self, *a, **k):
        pass

    def pause_for_speech(self, *a, **k):
        pass

    def resume_lesson(self, *a, **k):
        pass


class _StubGemini(QObject):
    exerciseReceived = Signal(dict)
    theoryVisualReceived = Signal(dict)
    lessonEndReceived = Signal()
    aiStartedSpeaking = Signal()
    aiFinishedSpeaking = Signal()
    connectionStatusChanged = Signal(bool)
    reconnecting = Signal(int, int)
    audioDataReceived = Signal(bytes)

    def __init__(self):
        super().__init__()
        self.connected = True
        self.released = 0
        self.resumed = 0

    def release_service(self):
        self.released += 1

    def resume_service(self):
        self.resumed += 1

    def send_prompt(self, *a, **k):
        pass

    def clear_exercise_pending(self, *a, **k):
        pass

    def send_performance_report(self, *a, **k):
        pass


class _StubEval(QObject):
    metronomeTick = Signal(int)
    evaluationFinished = Signal()

    def __init__(self):
        super().__init__()
        self.isRunning = False


@pytest.fixture
def wired(qapp):
    trainer, gemini = _StubTrainer(), _StubGemini()
    hw = MagicMock()
    coordinator = AppCoordinator(
        gemini_service=gemini,
        eval_engine=_StubEval(),
        chord_trainer=trainer,
        hw_service=hw,
        settings=MagicMock(),
    )
    return coordinator, trainer, gemini, hw


def test_coordinator_releases_on_free_play(wired):
    coordinator, trainer, gemini, _hw = wired

    trainer.coachNeeded = False
    trainer.coachNeededChanged.emit(False)

    assert gemini.released == 1
    assert gemini.resumed == 0


def test_coordinator_restores_on_leaving_free_play(wired):
    coordinator, trainer, gemini, _hw = wired

    trainer.coachNeeded = False
    trainer.coachNeededChanged.emit(False)
    trainer.coachNeeded = True
    trainer.coachNeededChanged.emit(True)

    assert gemini.resumed == 1


def test_entering_free_play_clears_an_overlay_already_up(wired):
    """
    A drop can be mid-retry at the moment free play starts.

    Without this the overlay stays up over the opening bars until the retry
    budget runs out.
    """
    coordinator, trainer, gemini, _hw = wired
    states = []
    coordinator.isReconnectingChanged.connect(states.append)

    gemini.reconnecting.emit(1, 5)
    assert coordinator.isReconnecting is True

    trainer.coachNeeded = False
    trainer.coachNeededChanged.emit(False)

    assert coordinator.isReconnecting is False
    assert states == [True, False]


def test_retries_during_free_play_never_raise_the_overlay(wired):
    """
    The socket closes asynchronously, so a retry can fire just after release.

    This is the failure the whole change exists to prevent, so it is asserted
    directly rather than relying on the release having already taken effect.
    """
    coordinator, trainer, gemini, hw = wired
    trainer.coachNeeded = False
    trainer.coachNeededChanged.emit(False)

    gemini.reconnecting.emit(2, 5)

    assert coordinator.isReconnecting is False, (
        "a reconnect attempt raised the overlay during free play"
    )
    hw.play_reconnect_ping.assert_not_called()


def test_retries_outside_free_play_still_raise_the_overlay(wired):
    """The overlay must still work where it is wanted — during a lesson."""
    coordinator, trainer, gemini, hw = wired

    gemini.reconnecting.emit(1, 5)

    assert coordinator.isReconnecting is True
    hw.play_reconnect_ping.assert_called_once()
