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

| # | Brief | Delivers | Size | Depends on | Status |
|---|-------|----------|------|------------|--------|
| 1 | `phase-1-import-core.md` | MusicXML import, MIDI fidelity fixes, Step Schema v2, dedupe groundwork | L | — | ✅ Code complete 2026-07-27 (after one repair pass; human acceptance gates still pending) |
| 2 | `phase-2-measure-notation.md` | Time signatures, dotted notes, tuplets, dynamics, renderer perf | L | 1 | ✅ Code complete 2026-07-27 (one blocker fixed post-review; human gates pending) |
| 3 | `phase-3-playback-sequencer.md` | Piece playback, tempo scale, A/B loop, hand filter, metronome | M | 1 | ✅ Code complete 2026-07-27 (four defects fixed post-review; **human gates pending — this phase's value is audible, so the manual pass is mandatory**) |
| 4 | `phase-4-dual-pacing.md` | Opt-in rhythm scoring beside untouched self-paced play; mastery recording | L | 1 (better after 3) | ✅ Code complete 2026-07-30 (human gates pending — **gate 1, the self-paced regression, and gate 6, onboarding end-to-end, are the mandatory ones**) |
| 5 | `phase-5-library-view.md` | Library screen: drag-and-drop, rename/delete, dedupe UI | M | 1 (may run before 3/4) | ✅ Code complete 2026-07-30 (human gates pending — **gates 2/3, the drag-and-drop import strip, and gate 6, delete refusal during practice, are the mandatory ones**) |
| 6 | `phase-6-ai-progress.md` | Gemini library awareness, repertoire binding, mastery surfacing | S–M | 4, 5 | Pending |

Phase 7 (Verovio-based print-quality sheet view, fed by the source copies Phase 1 stores) is future work — no brief exists; do not attempt it.

## ⚠️ Editing discipline — MANDATORY, added after the Phase 1 rework

Phase 1 was first implemented by **regenerating `music21_service.py` from scratch** instead of editing it. That rewrite silently deleted the corpus catalog API (breaking the app's song browser), replaced the shipped difficulty-simplification algorithm with an unrelated one, left new async machinery unwired, skipped cache invalidation, and let tests write junk records into the live user library. A full repair pass was required. These rules are binding for every remaining phase:

1. **Edit in place. Never regenerate a file.** If `git diff` on a file you touched shows wholesale churn, or deletes/rewrites any function you did not set out to change, your change is wrong — restore the file and re-apply the change surgically.
2. **Symbol preservation check.** Each brief has a "Must survive" list. When you believe you are done, grep the file for every listed symbol: each must still exist with unchanged behavior. A missing symbol means the phase fails review regardless of tests.
3. **Wire everything you build.** Every new class, slot, or signal must have a live caller by the end of the phase, and any old call site it replaces must actually be switched over. Machinery that exists but is never invoked counts as an incomplete task, not a bonus.
4. **Cache and state invalidation.** If you add or read a cache, enumerate every mutation site that must invalidate it and cover at least one in a test. (Phase 1's `_level_cache` initially served stale steps after hand-mode changes.)
5. **Async UI contract.** Any operation that sets a QML busy/loading state must clear it on the failure path as well as the success path.
6. **Test hygiene.** Tests must never write to live user data. `tests/conftest.py` provides `tmp_user_songs_dir` (monkeypatches `Music21Service._user_songs_dir` to a temp dir) — use it for anything that touches user songs, and follow the same pattern for any new data location.
7. **Finish with a self-review.** Read your own full `git diff` against the brief's "Do NOT touch" and "Must survive" lists before declaring done, and write an accurate commit message naming the phase (Phase 1's commit was mislabeled "playback sequencer").

## Execution protocol (applies to every phase)

1. **One phase per working session.** Do not start a phase until the previous one's acceptance gates have passed.
2. **Line numbers are hints, not addresses.** Briefs cite symbols with approximate line numbers from a July 2026 snapshot (and `music21_service.py` shifted substantially in Phase 1). Always locate code by searching for the symbol name; never edit by line number alone.
3. **Write the phase's unit tests first.** All specified tests are pure Python (no Qt event loop needed) and are the objective completion gate. Run the **canonical suite** and append your phase's files to it:
   `python -m pytest tests/test_step_schema.py tests/test_midi_ingestor.py tests/test_simplify.py tests/test_musicxml_import.py tests/test_catalog_and_pickup.py tests/test_playback_compile.py tests/test_rhythm_engine.py tests/test_evaluation_regression.py tests/test_mastery.py tests/test_library_ops.py -q`
   Do **not** run bare `pytest tests/` — three legacy files (`test_lesson_timing.py`, `test_full_lesson_timing.py`, `test_onboarding_flow.py`) fail at collection on a pre-existing PySide6 stub issue unrelated to this work.
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

## Carry-over punch list

Small known issues, none blocking. Fold each into whichever later session next touches the relevant file.

From Phase 4:

- Rhythm mode and `PlaybackService` run independent clocks, so a duet (app plays LH while the engine scores your RH in rhythm mode) will drift — they start at different times because only the engine has a count-in. Self-paced duet, which is what the brief's acceptance gate covers, is unaffected. Sharing one transport is the fix; fold it into whichever phase next touches `playback_service.py`.
- `_on_trainer_metronome` in `app_coordinator.py` derives its beat number from `_pentascale_beat_count`, an attribute `ChordTrainerService` does not define, so it always clicks beat 1. Rhythm mode sidesteps it with its own `rhythmCountInTick` signal, but the pentascale/steady-pulse click is still wrong.

From Phase 2 (`notation_view.py`):
- The rest branch in `_render_scrolling_array` calls `_duration_to_glyph` and discards the result, keeping its own threshold chain — so dotted rests don't render, and there's a dead call to remove.
- `_render_scrolling_array` rebuilds the `beats_only` list from `_scrolling_beats_index` on every paint (O(n) per frame) — cache it alongside the index to complete the O(visible) goal.
- Culling margin is a fixed ±8 beats rather than beam/tuplet-group-aware widening.

From Phase 1:

- ~~`Music21Service._on_simplify_failed` only logs — QML's `isLoadingSong` spinner is never cleared when async level regeneration fails.~~ Fixed in Phase 5: emits `songLevelFailed`, consumed by both DashboardView's picker and LibraryView.
- `request_song_level` calls `worker.wait()` on the UI thread when a previous regeneration is still running — brief UI freeze on rapid difficulty switching. Queue instead of blocking.
- `_simplify_groups` is missing the original final transform: stretch each kept note's duration to the next same-hand onset, clamped to [0.25, 4.0]. Simplified levels can sound clipped without it.
- `tests/test_catalog_and_pickup.py::test_catalog_methods_restored` requires `database/music21_catalog.json` to exist — make it `pytest.skip` cleanly when absent so the suite is portable.
- ~~Source copies under `user_songs/sources/` can be orphaned when no record references the hash.~~ Fixed in Phase 5: `_sweep_orphan_sources` runs on every delete and removes every unreferenced copy, pre-existing ones included.

## Global regression watch

After any phase, verify these still work:
- Onboarding skill evaluation (`EvaluationService` + `OnboardingOverlay.qml`) — especially after Phase 4.
- Corpus song loading and display (shared `_extract_steps_from_score`) — especially after Phase 1.
- Loading a v1 user-song JSON saved before Phase 1 (keep a fixture copy).
- Lesson mode with the AI coach (exercise dispatch via `AppCoordinator`).
