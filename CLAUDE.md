# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Tech Stack

**Languages:** Python 3.11 (logic + UI bridge), C++17 (MIDI hardware), QML/Qt Quick (UI)
**UI Framework:** PySide6 (Qt6 Python bindings) with QML for rendering
**AI:** Google Gemini Multimodal Live API via WebSocket (google-genai SDK)
**Music Theory:** music21 (lazy-loaded — expensive import)
**Build:** CMake for C++ extension, PyInstaller for distribution

## Commands

### Development

```bash
# Build the C++ MIDI hardware extension (required before running)
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release --parallel  # Windows
# OR: make -j$(nproc)                        # Linux/macOS

# Run the app
python src/app.py
```

### Distribution Builds

```bash
# Windows
pyinstaller chordcoach.spec --clean --noconfirm
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
# Output: installer_output/ChordCoachCompanion_Setup.exe

# macOS
pyinstaller chordcoach.spec --clean --noconfirm
create-dmg --volname "ChordCoach Companion" ChordCoachCompanion-macOS.dmg dist/
```

### Tests

```bash
pytest tests/ -q
```

Tests run headless — `tests/conftest.py` creates a single offscreen
`QGuiApplication` at import time. Qt allows only one application object per
process and a `QCoreApplication` cannot be promoted to a `QGuiApplication`, so
never construct one inside a test; depend on the `qapp` fixture instead.
Use `notation_fonts` when a test needs the bundled Bravura/Inter metrics.

## Architecture

### Layer Overview

```
QML UI (*.qml) — hardware-accelerated, 60fps
    ↕ signals/slots
AppState QObject (src/app.py) — Qt root, connects all services
    ↕
AppCoordinator (src/logic/coordinators/app_coordinator.py) — routes events between services
    ↕                             ↕
Gemini WebSocket service ←→  ChordTrainer + other services
    ↕
Hardware C++ extension (chordcoach_hw) — sub-ms MIDI I/O
```

### Key Design Patterns

**QML Bridge:** Python services expose Qt signals/slots via `QObject` subclasses. QML calls Python slots; Python fires signals that update QML properties. `notation_view.py` is the largest Python-QML bridge (~42KB).

**Dual MIDI Strategy:** Input uses the C++ `chordcoach_hw` pybind11 extension (zero-latency controller keypress detection). Output uses a ctypes wrapper calling RtMidi DLL directly (bypasses Python overhead for metronome/chord preview).

**Local lesson sequencing:** `LessonSequencer` (`src/logic/services/lesson_sequencer.py`) chooses every exercise of a lesson from the curriculum plan, so lessons run the same with or without a coach connection. The coach (Gemini) only speaks: `coach_prompts.py` builds what it is asked to say (lesson intro, new exercise types, struggle tips, theory cards, the goodbye), and `ChordTrainerService._coach_say` pauses input while it talks — or carries straight on when no coach is connected. Gemini's only tool is `update_theory_visual`, ignored during the scripted Circle of Fifths tutorial. Optional per-milestone hints for the sequencer (`inversions`, `hand`, `single_notes`, `pedal_type`, `progressions`, `follow_up`) live in `src/resources/curriculum_tracks.json`.

**Music21 Lazy Loading:** `Music21Service` imports music21 on first use. All analysis (key detection, Roman numeral analysis, difficulty scoring, transposition) is synchronous. No background threading around music21 calls.

**Frozen Binary Support:** `bootstrap.py` handles PyInstaller `_MEIPASS` paths and redirects logging to file. Assets are bundled via `chordcoach.spec` (music21 corpus filtered to exclude tests/docs).

### Data Flow (Lesson Mode)

1. MIDI keypress → C++ `chordcoach_hw` → `MidiHardwareService`. The C++ input thread stamps each message; the service converts that to a `time.perf_counter()` value and emits `midiNoteTimed` / `sustainPedalTimed`. Timing is scored at that event time (`RhythmEngine`, `MetronomeService.get_timing_offset_ms`, the trainer's `_now()`), not when the main thread got to it
2. `AppCoordinator._dispatch_midi_note()` routes to `ChordTrainerService` or `EvaluationService`
3. `ChordTrainerService` compares input vs. exercise spec and records the attempt
4. On completion it asks its `LessonSequencer` for the next exercise (repeat or simplify after a struggle) and, when worth a word, prompts the coach → services update state → Qt signals → QML updates

### Important Files

| File | Purpose |
|------|---------|
| `src/app.py` | Entry point; initializes all services and AppState QObject |
| `src/core/bootstrap.py` | Path resolution, logging setup, frozen binary support |
| `src/logic/coordinators/app_coordinator.py` | Orchestrates AI ↔ services ↔ hardware |
| `src/logic/services/chord_trainer.py` | Lesson state machine and the QML surface for practice: current target, held keys, holds, coach pauses |
| `src/logic/services/exercises/` | One handler per exercise type (setup, input check, what follows success) |
| `src/logic/services/song_session.py` | The piece being played: steps, practice prefs, rhythm mode, scoring |
| `src/logic/services/circle_tutorial.py` | Scripted Circle of Fifths tutorial and V→I drill |
| `src/logic/services/lesson_sequencer.py` | Chooses each lesson's exercises from the curriculum plan |
| `src/logic/services/gemini_service.py` | Gemini WebSocket client with auto-reconnect |
| `src/logic/services/database_manager.py` | SQLite schema + ORM for user sessions/progress |
| `src/logic/services/music21_service.py` | Score → steps analysis; the QML-facing front that delegates to the two below |
| `src/logic/services/song_library.py` | Imported songs: JSON records, import, difficulty levels, note editor, rename/delete |
| `src/logic/services/corpus_catalog.py` | Built-in corpus browser: catalogue, search, recents, corpus download |
| `src/ui/notation_view.py` | Python/QML bridge for notation rendering |
| `design_spec.md` | Full technical design document — read this for deep context |

### Curriculum & Data

- `CurriculumService` manages 4 learning tracks (Technique, Theory, Repertoire, Ear/Listen)
- SM-2 spaced repetition (`src/logic/utils/sm2.py`, `review_items` table) schedules chords and songs: graded from latency, wrong notes or song accuracy, first attempt of each day only. Due items open each lesson as a "Review" block, and the dashboard's Quick Review card shows and runs them (plus anything struggled with earlier in the session). Mastery decay (`apply_daily_skill_decay`) is separate and still runs once a day.
- All user data is local SQLite (`database/`)
- Curriculum definitions loaded from `src/resources/` JSON files at startup

### Environment

- `GOOGLE_API_KEY` in `.env` is required for Gemini features
- The built `chordcoach_hw` extension (`.pyd` on Windows, `.so` on Linux, `.dylib` on macOS) must be present in the build output path for MIDI hardware to work
