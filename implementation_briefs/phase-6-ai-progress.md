# Phase 6 — AI + Progress Integration

**Size: S–M. Dependencies: Phase 4 (mastery data), Phase 5 (nice-to-have for surfacing). Read `00-README.md` first — especially the Editing discipline section.**

## Rework guardrails (binding)

- **Prompt/description strings only in `gemini_service.py`.** This phase edits exactly two description strings and one system-prompt line — the tool declaration block's structure, the three tool names, `NON_BLOCKING` behavior, and everything else in that file are untouched. Do not regenerate the file.
- **Must survive** (grep after editing): in `gemini_service.py` — the three tool declarations `set_exercise` / `end_lesson` / `update_theory_visual` and the `coach_context` injection; in `curriculum_service.py` — `plan_session` (unchanged), `get_curriculum_context` (gains an appended section only); in `curriculum_tracks.json` — every existing milestone field (`suggested_pieces` is additive; all other milestones must parse unchanged).
- **Wire everything:** `reviewQueueCount` must be a real notifiable Property that the existing QML binding picks up; the library context section must demonstrably appear in the logged prompt.
- **Status note:** the `song_application` enum fix landed in Phase 1 and was verified present after the repair pass — the "verify; fix if skipped" instruction below is satisfied; just confirm it survived.

## Mission

Make the Gemini coach aware of the student's song library so it can assign real (including imported) pieces for repertoire work; surface mastery in the UI; give the repertoire curriculum track its first real piece bindings. **This is prompt-and-context plumbing — no new Gemini tools, no scheduling engine, and full SM-2 spaced repetition stays out of scope.**

## Current state (verified facts — grep for symbols, line numbers are hints)

**Gemini plumbing (`src/logic/services/gemini_service.py`):** three tools declared (~:336-478): `set_exercise`, `end_lesson`, `update_theory_visual`. Flow: tool call → `exerciseReceived(dict)` → `AppCoordinator._on_exercise_received` (gated during onboarding evaluation and the Circle-of-Fifths tutorial) → `ChordTrainer.receive_exercise`. On the Live model `set_exercise` is `NON_BLOCKING`; the performance report returns as the delayed tool result.

- `exercise_type` description (~:351): Phase 1 already appended `song_application`. Verify it's there; fix if Phase 1 was skipped.
- `piece_name` description (~:429-431): currently *"For song_application exercises: music21 corpus identifier, e.g. 'bach/bwv1.6.mxl' or 'essenFolksong/erk5'"* — **corpus-only; the AI has no way to reference imported songs.**
- System prompt (~:289): requires `song_application` + `piece_name` when the curriculum calls for it.
- The curriculum context string is injected via `coach_context` (~:301); it is built by `CurriculumService.get_curriculum_context()` (`src/logic/services/curriculum_service.py` ~:160) — milestones, accuracy, recent sessions. **No song lists of any kind.**

**Song loading already handles everything:** `ChordTrainer._setup_song_target` → `Music21Service.load_song_as_steps` branches on the `user::` prefix (~:315) — an AI-supplied `user::` id would work **today** end-to-end. A bad/hallucinated id fails gracefully: load returns an error record and `_setup_song_target` (~:1490-1503) resets to IDLE with a status message (verified path). Fallback default piece: `chord_data.get("piece_name", "bach/bwv1.6.mxl")` (~:1483).

**Curriculum (`src/resources/curriculum_tracks.json` + `curriculum_service.py`):** 4 tracks (technique 10, theory 9, repertoire 3, ear 2 milestones). Repertoire milestones `song_breakdown_intro` and `dream_song_prep` declare `exercise_types: ["song_application"]` **with no piece references** (empty `target_keys`/`target_chords`; no piece field exists in the schema). `plan_session()` (~:67) builds blocks from `exercise_types`/`target_keys`/`target_chords`/`step_count` only.

**Progress:** `songs.mastery_score` written by `record_song_play` from Phase 4 onward. `DatabaseManager.calculate_skill_decay(decay_hours=48, decay_rate=0.95)` exists and runs. **Dead UI binding:** `DashboardView.qml` (~:174) renders `appState.curriculumEngine.reviewQueueCount` — no such property exists on `CurriculumService`; it renders blank today.

**Free play stays AI-free:** `start_song` bypasses Gemini by design; `AppCoordinator._on_song_finished` (~:257) branches free-play → dashboard vs lesson-mode → AI feedback. Don't change this.

## Tasks (in order)

### 1. `piece_name` tool description (`gemini_service.py` ~:429)

Extend to: *"For song_application exercises: a music21 corpus identifier (e.g. 'bach/bwv1.6.mxl' or 'essenFolksong/erk5') OR a user-library id starting with 'user::' taken EXACTLY from the Student's Song Library list in your context. Never invent user:: ids."*

### 2. Library context section

- New `Music21Service.get_user_song_summaries() -> list[dict]`: id, title, grade (numeric from `level`), mastery, last_played (join via `DatabaseManager.get_song_masteries` from Phase 5; return mastery 0 when absent).
- `CurriculumService.get_curriculum_context()` appends:

```
STUDENT'S SONG LIBRARY (assignable via song_application piece_name):
- user::fur-elise-1721912345 — "Für Elise" (Grade 4, mastery 35%, last played 2026-07-20)
- ...
Recently played corpus pieces: bach/bwv1.6.mxl, ...
```

- **Cap it:** max ~20 library lines (sort: in-progress mastery 1–79 first, then unplayed, then mastered), max 5 recent corpus lines. Truncate titles > 40 chars. CurriculumService needs a reference to Music21Service — pass it at construction in `src/app.py` (follow the existing service-wiring pattern there).

### 3. System-prompt rule (`gemini_service.py`, near the `song_application` rule ~:289)

Add one line: *"For repertoire milestones, prefer pieces from the STUDENT'S SONG LIBRARY at or slightly below the student's level; fall back to a corpus piece only if the library has nothing suitable."*

### 4. Repertoire milestone bindings (`src/resources/curriculum_tracks.json`)

Add an optional `suggested_pieces: [<corpus-or-user-id>, ...]` field to milestone objects; populate the three repertoire milestones with 2–3 easy corpus ids each (pick short Grade 1–3 pieces from the catalog, e.g. simple Bach chorale/folk-song entries verified to load). `get_curriculum_context()` includes them in the milestone lines. `CurriculumService` must tolerate the field being absent (all other milestones). No `plan_session()` changes.

### 5. Mastery surfacing (UI)

- Dashboard: a small "Repertoire" strip/tile showing top-3 in-progress pieces (mastery 1–79) with mini mastery bars; tapping one routes through the existing `requestSongWithDifficulty`. (LibraryView from Phase 5 already shows full mastery.)
- **Fix the dead binding:** add a `reviewQueueCount` read-only property (with change signal) to `CurriculumService`: count of songs whose `last_played` is older than 48 h with `mastery_score > 0` (reuse the `calculate_skill_decay` query logic — a read-only count, do not trigger decay writes). `DashboardView.qml` ~:174 starts rendering a real number. **Do not build SM-2.**

### 6. Verify the failure path

Write a quick integration-style check (can be manual + logged): feed `receive_exercise` a `song_application` dict with a nonexistent `user::bogus` id → trainer resets to IDLE with the status message, no crash, next exercise still accepted.

## Tests (write first)

- `tests/test_ai_context.py` — `get_user_song_summaries` shape and mastery join (mock DB); context string contains the library section, respects the 20-line cap and sort order; milestones with and without `suggested_pieces` both render; `reviewQueueCount` logic against a mocked `songs` table (fresh vs stale `last_played`).

## Acceptance gates

**Automated:** tests pass.

**Human (run `python src/app.py` with `GOOGLE_API_KEY` set):**
1. Import a piece, then start a Daily Lesson → the logged Gemini system context (service logs the prompt) contains the STUDENT'S SONG LIBRARY section with the imported song's `user::` id.
2. During a repertoire block, the AI assigns a library piece via `song_application` and it loads and plays in the trainer. (May take a few sessions to reach a repertoire block — acceptable to verify by temporarily activating a repertoire milestone in the DB/curriculum state.)
3. Simulated bad id (task 6) recovers gracefully.
4. Dashboard shows the Repertoire strip with mastery; review count shows a real number (0 is fine on a fresh profile).
5. Free play still bypasses the AI entirely.

## Do NOT touch

- Tool set: no new Gemini tools, no schema changes beyond the two description strings.
- `plan_session()` block-building logic and step-count allocations.
- `AppCoordinator` exercise gating (evaluation / Circle-of-Fifths).
- Free-play bypass behavior.
- No SM-2 columns/algorithms — `reviewQueueCount` is a derived count only.

## Regression watch

Lesson mode end-to-end with the AI (context string growth must not break the session prompt — watch token/length limits and keep the cap); onboarding; exercise variety for non-repertoire tracks; dashboards on a fresh profile with zero songs (empty library section must render as a clean "(none yet)" line, not an error).
