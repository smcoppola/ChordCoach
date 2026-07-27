# Implementation Briefs — Music Import & Sheet Music Presentation

This folder contains self-contained implementation briefs for a six-phase upgrade of ChordCoach Companion's music import and sheet-music presentation. Each brief is written to be executed by an AI coding agent **without any other context** — everything needed is in the brief plus the repository itself.

## The app in one paragraph

ChordCoach Companion is a piano learning app: Python 3.11 logic + PySide6/QML UI, a Gemini AI coach over WebSocket (`src/logic/services/gemini_service.py`), music21 for theory analysis (lazy-loaded), a C++ pybind11 extension (`chordcoach_hw`) for zero-latency MIDI input, and a ctypes RtMidi wrapper for MIDI output. Entry point: `python src/app.py` (requires the built C++ extension; see `CLAUDE.md` at repo root for build commands). `AppState` in `src/app.py` wires all services together; `AppCoordinator` routes events between the AI, services, and hardware. There is currently **no test suite** — Phase 1 introduces the first one under `tests/`.

## The architecture backbone (read this before any phase)

The app's lingua franca is the **note-step list** produced by `Music21Service._extract_steps_from_score` (`src/logic/services/music21_service.py`) and consumed by `ChordTrainerService._setup_song_target` (`src/logic/services/chord_trainer.py`) and the `NotationView` renderer (`src/ui/notation_view.py`):

```
steps:      [{offset, pitches[], spellings[], hands[], fingers[], ties[], beams[], duration, rests[]}]
song-level: barlines[], title, composer, key, key_sharps
```

Imported songs are stored as **one JSON file per song** in `<user_data>/database/user_songs/` with ids `user::<slug>-<timestamp>` (`%LOCALAPPDATA%\ChordCoach\...` on Windows for frozen builds; the project root in dev mode — the split is a known quirk). Corpus songs load through `music21.corpus.parse`; both paths share `_extract_steps_from_score`.

Phase 1 versions this format (**Step Schema v2**, defined fully in `phase-1-import-core.md`) and every later phase extends it additively. **No phase replaces the step format or rewrites a consumer.**

Song selection flows through a global signal relay: `Music21Service.songRequested(songId)` → `CenterWorkspace.qml` → `chordTrainer.start_song(songId)`.

## Phases, order, and dependencies

| # | Brief | Delivers | Size | Depends on |
|---|-------|----------|------|------------|
| 1 | `phase-1-import-core.md` | MusicXML import, MIDI fidelity fixes, Step Schema v2, dedupe groundwork | L | — |
| 2 | `phase-2-measure-notation.md` | Time signatures, dotted notes, tuplets, dynamics, renderer perf | L | 1 |
| 3 | `phase-3-playback-sequencer.md` | Piece playback, tempo scale, A/B loop, hand filter, metronome | M | 1 |
| 4 | `phase-4-dual-pacing.md` | Opt-in rhythm scoring beside untouched self-paced play; mastery recording | L | 1 (better after 3) |
| 5 | `phase-5-library-view.md` | Library screen: drag-and-drop, rename/delete, dedupe UI | M | 1 (may run before 3/4) |
| 6 | `phase-6-ai-progress.md` | Gemini library awareness, repertoire binding, mastery surfacing | S–M | 4, 5 |

Phase 7 (Verovio-based print-quality sheet view, fed by the source copies Phase 1 stores) is future work — no brief exists; do not attempt it.

## Execution protocol (applies to every phase)

1. **One phase per working session.** Do not start a phase until the previous one's acceptance gates have passed.
2. **Line numbers are hints, not addresses.** Briefs cite symbols with approximate line numbers from a July 2026 snapshot. Always locate code by searching for the symbol name; never edit by line number alone.
3. **Write the phase's unit tests first.** All specified tests are pure Python (no Qt event loop needed) and are the objective completion gate. Run with `python -m pytest tests/ -x -q` from the repo root.
4. **Human acceptance gates are mandatory.** Each brief ends with manual checks a human performs by running `python src/app.py`. The phase is not done until a human signs off — especially Phase 2, whose output is visual.
5. **Respect every "Do NOT touch" list.** These protect working behavior (the self-paced play path, onboarding evaluation, v1 saved-song compatibility, corpus loading).
6. **Additive schema changes only.** New step/song fields must default sensibly for old data; existing fields keep their meaning. The v1→v2 normalizer in `step_schema.py` (Phase 1) is the single place shape differences are absorbed.
7. Do not commit secrets; `GOOGLE_API_KEY` lives in `.env` and is required only for AI features — none of the phases need a live Gemini connection to be implemented or unit-tested.

### Recommended implementing model & effort (as of 2026-07)

Use **Gemini 3.6 Flash for every phase** — on published benchmarks it outperforms Gemini 3.1 Pro on agentic coding (SWE-Bench Pro 58.7% vs 54.2%, Terminal-Bench 2.1 78% vs ~69–74%) at ~40% lower cost with the same 1M-token context. Vary the `thinking_level` parameter rather than the model:

| Phases | `thinking_level` | Why |
|---|---|---|
| 1, 2, 4 | `high` | Schema migration, renderer geometry, behavior-identical refactor — subtle failure modes |
| 3, 5 | `medium` (default) | Well-specified new modules with clear APIs |
| 6 + trivial tasks | `low`–`medium` | Short-step plumbing; low thinking is strong for these |

Consult Gemini 3.1 Pro only as a second opinion on a stuck design puzzle — its edge is deep abstract reasoning, not coding. Sanity-check Phase 1's output quality before relying on the cheaper settings in later phases.

## Global regression watch

After any phase, verify these still work:
- Onboarding skill evaluation (`EvaluationService` + `OnboardingOverlay.qml`) — especially after Phase 4.
- Corpus song loading and display (shared `_extract_steps_from_score`) — especially after Phase 1.
- Loading a v1 user-song JSON saved before Phase 1 (keep a fixture copy).
- Lesson mode with the AI coach (exercise dispatch via `AppCoordinator`).
