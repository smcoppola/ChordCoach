"""
Signal wiring between services lives in AppCoordinator; AppState only builds
the services and re-exposes signals to QML. These check that split, and the
connections that were once doubled, missing or reading the wrong thing.
"""
import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal

from logic.coordinators.app_coordinator import AppCoordinator

SRC = Path(__file__).resolve().parent.parent / "src"


class StubTrainer(QObject):
    coachNeededChanged = Signal(bool)
    speakInstruction = Signal(str)
    speakBrief = Signal(str)
    isCircleOfFifthsModeChanged = Signal(bool)
    theoryVisualDirect = Signal(dict)
    midiOutRequested = Signal(list)
    metronomeTick = Signal()
    rhythmCountInTick = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self.coachNeeded = True
        self.isLoading = False
        self.isCircleOfFifthsMode = False
        self.pentascaleBeatCount = 0
        self.loading_status = None
        self.pedal = []
        self.pedal_times = []
        self.notes = []

    def handle_pedal_event(self, down, event_time=None):
        self.pedal.append(down)
        self.pedal_times.append(event_time)

    def handle_midi_note(self, *a):
        self.notes.append(a)

    def pause_for_speech(self):
        pass

    def resume_lesson(self):
        pass

    def set_coach_available(self, available):
        pass

    def notify_visual_received(self):
        pass

    def set_loading_status(self, text):
        self.loading_status = text


class StubGemini(QObject):
    theoryVisualReceived = Signal(dict)
    aiStartedSpeaking = Signal()
    aiFinishedSpeaking = Signal()
    connectionStatusChanged = Signal(bool)
    reconnecting = Signal(int, int)
    audioDataReceived = Signal(bytes)
    connected = True

    def send_prompt(self, *a):
        pass

    def set_tools_disabled(self, *a):
        pass


class StubEval(QObject):
    metronomeTick = Signal(int)
    evaluationFinished = Signal()
    isRunning = False


class StubHardware(QObject):
    midiNoteReceived = Signal(int, bool)
    sustainPedalChanged = Signal(bool)
    midiNoteTimed = Signal(int, bool, float)
    sustainPedalTimed = Signal(bool, float)

    def __init__(self):
        super().__init__()
        self.previews, self.ticks = [], []
        self.is_connected = True

    def play_chord_preview(self, pitches):
        self.previews.append(pitches)

    def play_metronome_tick(self, beat):
        self.ticks.append(beat)


@pytest.fixture
def wired(qapp):
    trainer, gemini, hw, circle = StubTrainer(), StubGemini(), StubHardware(), MagicMock()
    coordinator = AppCoordinator(gemini, StubEval(), trainer, hw, MagicMock(), circle)
    return coordinator, trainer, gemini, hw, circle


def test_a_chord_preview_is_sent_once(wired):
    _c, trainer, _g, hw, _circle = wired
    trainer.midiOutRequested.emit([60, 64, 67])
    assert hw.previews == [[60, 64, 67]]


def test_the_pedal_reaches_the_trainer(wired):
    _c, trainer, _g, hw, _circle = wired
    hw.sustainPedalChanged.emit(True)   # what QML listens to
    hw.sustainPedalTimed.emit(True, 12.5)
    assert trainer.pedal == [True]
    assert trainer.pedal_times == [12.5]


def test_a_note_reaches_the_trainer_once_with_its_time(wired):
    _c, trainer, _g, hw, _circle = wired
    hw.midiNoteReceived.emit(60, True)  # what QML listens to
    hw.midiNoteTimed.emit(60, True, 12.5)
    assert trainer.notes == [(60, True, 12.5)]


def test_theory_visuals_reach_the_circle_view_once(wired):
    _c, trainer, _g, _hw, circle = wired
    trainer.theoryVisualDirect.emit({"highlight_key": "G"})
    circle.set_tutorial_state_v2.assert_called_once_with({"highlight_key": "G"})


@pytest.mark.parametrize("count,click", [(-3, 2), (-2, 3), (-1, 4), (0, 1), (1, 2), (3, 4), (4, 1)])
def test_the_metronome_accents_only_the_downbeat(wired, count, click):
    _c, trainer, _g, hw, _circle = wired
    trainer.pentascaleBeatCount = count
    trainer.metronomeTick.emit()
    assert hw.ticks == [click]


def test_coach_audio_updates_the_loading_line_through_the_public_method(wired):
    _c, trainer, gemini, _hw, _circle = wired
    trainer.isLoading = True
    gemini.audioDataReceived.emit(b"x")
    assert trainer.loading_status == "LISTEN TO YOUR COACH..."


# ── Structure ───────────────────────────────────────────────────────────────

def _connects(path, class_name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    for node in ast.walk(cls):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect" and node.args):
            yield ast.unparse(node.func.value), ast.unparse(node.args[0])


def test_app_state_only_forwards_signals_to_itself():
    """Service-to-service connections belong in AppCoordinator."""
    stray = [(sig, slot) for sig, slot in _connects(SRC / "app.py", "AppState")
             if slot.count(".") != 1 or not slot.startswith("self.")]
    assert not stray, f"AppState wires services together: {stray}"


def test_no_connection_is_made_twice():
    for path, cls in ((SRC / "app.py", "AppState"),
                      (SRC / "logic/coordinators/app_coordinator.py", "AppCoordinator")):
        pairs = list(_connects(path, cls))
        assert len(pairs) == len(set(pairs)), f"duplicate connect in {cls}"
    both = list(_connects(SRC / "app.py", "AppState")) + \
        list(_connects(SRC / "logic/coordinators/app_coordinator.py", "AppCoordinator"))
    norm = lambda s: s.replace("self._gemini", "self.gemini").replace("self.coordinator.", "self.")
    seen = [(norm(a), norm(b)) for a, b in both]
    assert len(seen) == len(set(seen))


def test_nothing_reaches_into_another_services_private_state():
    import re
    pattern = re.compile(r"\b(?:self\.)?_?(?:chord_trainer|hw_service|gemini|evaluation|curriculum|"
                         r"music21_service|metronome|settings|coordinator)\._[a-z]\w*")
    hits = []
    for path in list((SRC / "logic").rglob("*.py")) + [SRC / "app.py"]:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in pattern.finditer(line):
                hits.append(f"{path.relative_to(SRC)}:{n}: {m.group(0)}")
    assert not hits, "\n".join(hits)
