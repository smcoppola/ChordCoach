"""
Every name QML reaches for on a Python object must exist on that object.

QML resolves `appState.chordTrainer.foo` at runtime and quietly yields
`undefined` when `foo` is missing, so a renamed or deleted property, slot or
signal breaks the UI without a single error at load time. This test reads the
QML sources and checks every member they use against Qt's own meta-object for
the class behind it — the exact list QML can see, so a plain Python attribute
(invisible to QML) fails here too.

It exists as the safety net for refactoring the services behind these objects:
the Python side may be reorganised freely as long as this stays green.
"""
import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
UI_DIR = SRC / "ui"

# appState.<name> → (module, class) of the object it returns.
EXPOSED = {
    "chordTrainer": ("logic.services.chord_trainer", "ChordTrainerService"),
    "music21Service": ("logic.services.music21_service", "Music21Service"),
    "settingsService": ("logic.services.settings_service", "SettingsService"),
    "circleOfFifths": ("logic.services.circle_of_fifths_service", "CircleOfFifthsService"),
    "playback": ("logic.services.playback_service", "PlaybackService"),
    "curriculumEngine": ("logic.services.curriculum_service", "CurriculumService"),
    "evaluationEngine": ("logic.services.evaluation_service", "EvaluationService"),
    "metronome": ("logic.services.metronome_service", "MetronomeService"),
    "hardware": ("hardware.midi_hardware_service", "MidiHardwareService"),
    "appCoordinator": ("logic.coordinators.app_coordinator", "AppCoordinator"),
    "gemini": ("logic.services.gemini_service", "GeminiService"),
}

# Components that hold one of those objects in a property of their own and use
# it under that name. (file, regex for the alias prefix, exposed name)
ALIASES = [
    ("LibraryView.qml", r"\bmusic21", "music21Service"),
    ("components/PlaybackBar.qml", r"\bplayback", "playback"),
    ("components/OnboardingOverlay.qml", r"\broot\.evalEngine", "evaluationEngine"),
]

_IDENT = r"([A-Za-z_][A-Za-z0-9_]*)"


def _qml_sources():
    return sorted(UI_DIR.rglob("*.qml"))


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # A `//` not preceded by ':' so that "http://" inside a string survives.
    return re.sub(r"(?<!:)//[^\n]*", "", text)


def _connections_blocks(text: str):
    """Yields the body of every `Connections { ... }`, braces balanced."""
    for m in re.finditer(r"\bConnections\s*\{", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        yield text[m.end():i - 1]


def _uses():
    """Yields (exposed name, member, file) for every member access in QML."""
    for path in _qml_sources():
        text = _strip_comments(path.read_text(encoding="utf-8"))
        rel = path.relative_to(UI_DIR).as_posix()

        for m in re.finditer(r"\bappState\." + _IDENT + r"\." + _IDENT, text):
            yield m.group(1), m.group(2), rel

        for file_name, prefix, exposed in ALIASES:
            if rel == file_name:
                for m in re.finditer(prefix + r"\." + _IDENT, text):
                    yield exposed, m.group(1), rel

        # Connections { target: <...appState.X...>; function onSomething() }
        for body in _connections_blocks(text):
            target = re.search(r"target:\s*([^\n]*)", body)
            if not target:
                continue
            exprs = re.findall(r"appState\." + _IDENT, target.group(1))
            if not exprs:
                continue
            exposed = exprs[-1]
            for h in re.finditer(r"function\s+on([A-Z][A-Za-z0-9_]*)\s*\(", body):
                signal = h.group(1)[0].lower() + h.group(1)[1:]
                yield exposed, signal, rel


def _meta_members(cls) -> set:
    mo = cls.staticMetaObject
    names = {mo.property(i).name() for i in range(mo.propertyCount())}
    names |= {bytes(mo.method(i).name()).decode() for i in range(mo.methodCount())}
    return names


def _app_state_members() -> set:
    """
    AppState's QML surface, read from source: importing src/app.py would run
    its bootstrap, which redirects stdout to the log file.
    """
    tree = ast.parse((SRC / "app.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AppState")
    names = set()
    for node in cls.body:
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                call = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(call, ast.Name) and call.id in ("Property", "Slot"):
                    names.add(node.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "Signal":
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_qml_sources_found():
    assert len(_qml_sources()) > 10


def test_every_app_state_member_used_by_qml_exists():
    members = _app_state_members()
    missing = set()
    for path in _qml_sources():
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"\bappState\." + _IDENT, text):
            if m.group(1) not in members:
                missing.add(f"{path.relative_to(UI_DIR).as_posix()}: appState.{m.group(1)}")
    assert not missing, "QML uses names AppState does not expose:\n" + "\n".join(sorted(missing))


def test_every_exposed_object_is_declared_on_app_state():
    members = _app_state_members()
    assert set(EXPOSED) <= members


@pytest.mark.parametrize("exposed", sorted(EXPOSED))
def test_every_member_used_by_qml_exists(qapp, exposed):
    import importlib

    module_name, class_name = EXPOSED[exposed]
    cls = getattr(importlib.import_module(module_name), class_name)
    available = _meta_members(cls)

    missing = sorted({
        f"{rel}: appState.{exp}.{member}"
        for exp, member, rel in _uses()
        if exp == exposed and member not in available
    })
    assert not missing, f"QML uses names {class_name} does not expose:\n" + "\n".join(missing)
