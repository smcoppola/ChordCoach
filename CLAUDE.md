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

No test suite exists in this project.

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

**Gemini Tool-Calling:** AI responses contain JSON function calls (`set_exercise`, `update_theory_visual`, `end_lesson`). `AppCoordinator` parses and routes these to the appropriate service. Exercises are gated — not accepted during Evaluation mode or Circle of Fifths tutorial.

**Music21 Lazy Loading:** `Music21Service` imports music21 on first use. All analysis (key detection, Roman numeral analysis, difficulty scoring, transposition) is synchronous. No background threading around music21 calls.

**Frozen Binary Support:** `bootstrap.py` handles PyInstaller `_MEIPASS` paths and redirects logging to file. Assets are bundled via `chordcoach.spec` (music21 corpus filtered to exclude tests/docs).

### Data Flow (Lesson Mode)

1. MIDI keypress → C++ `chordcoach_hw` → `MidiHardwareService`
2. `AppCoordinator._dispatch_midi_note()` routes to `ChordTrainerService` or `EvaluationService`
3. `ChordTrainerService` compares input vs. exercise spec, sends metrics to Gemini
4. Gemini responds with tool calls → `AppCoordinator` routes → services update state → Qt signals → QML updates

### Important Files

| File | Purpose |
|------|---------|
| `src/app.py` | Entry point; initializes all services and AppState QObject |
| `src/core/bootstrap.py` | Path resolution, logging setup, frozen binary support |
| `src/logic/coordinators/app_coordinator.py` | Orchestrates AI ↔ services ↔ hardware |
| `src/logic/services/chord_trainer.py` | Lesson state machine (~133KB, largest file) |
| `src/logic/services/gemini_service.py` | Gemini WebSocket client with auto-reconnect |
| `src/logic/services/database_manager.py` | SQLite schema + ORM for user sessions/progress |
| `src/logic/services/music21_service.py` | Music theory analysis wrapper |
| `src/ui/notation_view.py` | Python/QML bridge for notation rendering |
| `design_spec.md` | Full technical design document — read this for deep context |

### Curriculum & Data

- `CurriculumService` manages 4 learning tracks (Technique, Theory, Repertoire, Ear/Listen)
- SM-2 spaced repetition algorithm tracks chord/concept review
- All user data is local SQLite (`database/`)
- Curriculum definitions loaded from `src/resources/` JSON files at startup

### Environment

- `GOOGLE_API_KEY` in `.env` is required for Gemini features
- The built `chordcoach_hw` extension (`.pyd` on Windows, `.so` on Linux, `.dylib` on macOS) must be present in the build output path for MIDI hardware to work
