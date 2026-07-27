# Phase 4 — Dual Pacing Modes: Self-Paced + Rhythm Scoring

**Size: L. Dependencies: Phase 1 (per-note durations); Phase 3 recommended first (loop semantics, duet suppression). Read `00-README.md` first.**

## ⚠️ THE HARD CONSTRAINT

**Self-paced play is the product's core interaction and must not regress in any way.** In self-paced mode the piece advances only when the user plays the correct notes — no clock, no timing pressure. It is the default for every song the user has never played, permanently. Rhythm mode is **opt-in per song**. If any change in this phase alters self-paced behavior, the change is wrong.

## Mission

1. Extract `EvaluationService`'s proven beat-clock/hit-window engine into a reusable `RhythmEngine`.
2. Add an opt-in **rhythm mode** to song practice: the piece scrolls on a clock, each note scores hit/miss in a timing window, misses turn red on the sheet.
3. Give song practice **per-note visual feedback** (currently only onboarding has it).
4. Add live **hand-filtered practice** in both modes (duet with Phase 3 playback).
5. Finally record song progress: wire the never-called `record_song_play` mastery path.

## Current state (verified facts — grep for symbols, line numbers are hints)

**Self-paced song path (`src/logic/services/chord_trainer.py`) — the protected path:** `start_song(piece_name)` (~:770) → `_apply_step` → `_setup_song_target` (~:1481) loads steps, flattens to `scrollingNotes`, sets `_scroll_bpm = 0` (~:1592). Input: `handle_midi_note` → `_check_input` → `_check_chord` (~:2500) does **set-equality** of held pitches vs `_target_pitches`; on match `_complete_chord` → `_advance_song_chord` (~:2297) moves `_scroll_beat` to the next step's offset. `mistakeActive` (~:472) tolerates the previous step's pitches for legato. Wrong-note feedback is a full-screen `failFlash` (`ChordTrainerView.qml` ~:214) + whole-sheet dim (~:561) — **no per-note coloring**. Every completed step is recorded to the `chords` DB table under `f"Song: {self._song_title}"` (~:1596).

**The timing engine to extract (`src/logic/services/evaluation_service.py`) — onboarding-only today:** hard-loads `src/resources/sequences.json` in `__init__`, indexes by level. Internals: `PreciseTimer` 10 ms (~:43-47); `_advance_beat` from wall-clock delta × BPM (~:248-257); start at beat −4.0 for count-in with `metronomeTick` (~:259-265); per-note states `"pending"/"hit"/"miss"` (~:39); `_hit_window_beats = 0.35` (~:55); `handle_midi_note` (~:305) → `_check_note_hit` (~:316) matches pitch + `abs(currentBeat - start_beat) <= window`; `_check_missed_notes` (~:332) marks misses once the playhead passes; pause/resume (~:142-172); `_end_level` computes accuracy with 0.70 advance / 0.60 fail thresholds. Consumed by `OnboardingOverlay.qml` via `evalNoteStates`/`evalBeat`.

**Renderer feedback channel:** `NotationView` colors per-note states from `evalNoteStates` (gray hit, red `#F44336` @ 0.4 miss, ~:824-840) but the branch is **gated on `displayMode == "evaluation"`**. `EnhancedSheetMusic.qml` already forwards the array (~:25, ~:228).

**Progress dead-ends:** `DatabaseManager.record_song_play(filepath, title, mastery_gained)` (`src/logic/services/database_manager.py` ~:143) writes `songs.mastery_score` — **never called from any song path**. `calculate_skill_decay` exists and runs; imported songs participate in nothing.

**From earlier phases:** per-note `durations[]` (P1); `orig_i` original-index mapping through render culling (P2); `PlaybackService` with `loopStartBeat/loopEndBeat`, `handFilter`, `was_just_sent(pitch)` (P3).

## Tasks (in order)

### 1. Extract `src/logic/services/rhythm_engine.py` — `class RhythmEngine(QObject)`

Move (not rewrite) the mechanics listed above out of `EvaluationService`, generalized:
- `load(notes: list[{pitch, start_beat, duration_beats, hand}], tempo_bpm: float, count_in_beats: int = 4)` — arbitrary note lists, one entry per pitch (chords become multiple entries at the same `start_beat`; each scores independently — partial chords score partially, which is correct).
- Hit window constant **in beats** (±0.35) — practicing slower automatically gives proportionally more wall-clock leeway.
- Optional `set_loop(start_beat, end_beat)` — on wrap, reset the states of notes inside the loop to `"pending"` (per-pass scoring); accumulate pass stats.
- Signals: `beatChanged(float)` (30 Hz throttled — Phase 2 convention), `noteStateChanged(int index, str state)`, `metronomeTick(bool accent)`, `finished(float accuracy, int hits, int misses)`.
- Pause/resume preserved.

### 2. Refactor `EvaluationService` to delegate

`EvaluationService` keeps: sequences.json loading, level ladder, thresholds, its public signal/property surface (QML contract **unchanged**). It internally drives a `RhythmEngine` instance. Onboarding must be behavior-identical.

### 3. ChordTrainer pacing modes

- New state `self._pacing_mode: str = "self_paced"` + property. **The self-paced code path is byte-for-byte untouched.**
- `"rhythm"` mode in `_setup_song_target`: additionally flatten steps per-note (using v2 `durations[i]`) into engine input; start the engine (count-in 4 beats, tempo from the song's `tempo_map[0]` × the user's tempo scale if Phase 3 landed); drive `_scroll_beat` from `engine.beatChanged`; route note-ons in `handle_midi_note` to `engine.handle_midi_note`.
- **Hard mode gate:** a single `if self._pacing_mode == "rhythm": ... return` branch at the top of the note-on handling ensures the engine path and `_check_chord` path can never both run. Same gate wherever `_advance_song_chord` could fire.
- Respect Phase 3 duet suppression (`playback.was_just_sent`) before scoring any note-on in either mode.

### 4. Per-note visual feedback

- New ChordTrainer property `songNoteStates` (list[str]) aligned index-for-index with `scrollingNotes` — build a note-entry→sn-index map at setup; pseudo-items (barline/rest/time-sig/dynamic) get a placeholder state that renders as no-op.
- Relax the NotationView gate: color from the states array whenever it is **non-empty** (instead of `displayMode == "evaluation"`). Self-paced mode passes an empty array → zero visual change there. Phase 2's `orig_i` keeps indices correct under culling.
- Wire `engine.noteStateChanged` → update `songNoteStates` → renderer shows gray hits / red misses live.

### 5. Hand-filtered practice (both modes)

`set_practice_hands(mode: "both"|"right"|"left")`: filters `_target_pitches` per step (self-paced) or the engine note list (rhythm) by hand; steps left empty are auto-skipped. Combined with Phase 3's playback `handFilter` → duet ("app plays LH, you play RH"). Persist per song alongside `practice_mode`.

### 6. Mode toggle UI + persistence

- Segmented control "Self-paced ⟷ Rhythm" in the `ChordTrainerView.qml` song header (near the title), plus hands control if not already visible via PlaybackBar. Switching modes restarts the current section (loop-aware if a loop is set).
- Persist per song: `practice_mode` field in the user-song JSON via a new `Music21Service.set_user_song_pref(song_id, key, value)` slot (reuse the save helper from the hand-mode path). Corpus pieces: store in the existing `app_settings` table keyed by song id. **A never-played song always starts self-paced.**

### 7. Progress recording

On song completion in **either** mode, call `db.record_song_play(song_id, title, mastery_gained)` (key `filepath` arg by song id — `user::…` or corpus id):
- Rhythm mode: `mastery_gained = f(accuracy)` — use `accuracy² × 10`, halved if the run was loop-only (not full-piece).
- Self-paced: small completion-based gain (e.g. 3 points) reduced by wrong-note count (floor 1).
- Completion overlay in QML: accuracy % (rhythm), hits/misses, mastery delta, and a **"Practice trouble spots"** button — clusters misses by measure (barline math from `step_schema`) and sets the Phase 3 A/B loop around the worst measure.

## Tests (write first)

- `tests/test_rhythm_engine.py` — synthetic note list: hit inside ±0.35 beats scores; outside scores miss once passed; chord entries score independently; loop wrap resets in-loop states and accumulates stats; count-in emits no misses before beat 0; accuracy math.
- `tests/test_evaluation_regression.py` — drive the refactored `EvaluationService` through a scripted level-1 sequence from `sequences.json` (simulated clock + injected note events) and assert identical outcomes to the pre-refactor logic (compute expected values from the same file: hit/miss counts, accuracy, level advance at ≥0.70).
- `tests/test_mastery.py` — mastery formulas; `record_song_play` called once per completion with the song id (mock DB).

## Acceptance gates

**Automated:** all tests pass.

**Human (run `python src/app.py`):**
1. **Self-paced regression first:** open a never-played imported song → starts in self-paced; behavior identical to pre-phase (advance on correct notes, legato tolerance, fail flash); `songNoteStates` empty (no new coloring).
2. Toggle Rhythm: 4-beat count-in with metronome; sheet scrolls on the clock; correct notes gray, missed notes turn red as the playhead passes.
3. Completion overlay shows accuracy + mastery; "Practice trouble spots" sets a loop around the worst measure and it plays/loops.
4. Hands = RH in self-paced: LH-only steps are skipped; with playback duet (app plays LH), user's RH scores normally.
5. Mode choice persists per song across app restart; a different never-played song still defaults to self-paced.
6. **Onboarding end-to-end:** full skill evaluation flow runs identically (count-in, hit/miss colors, level advance).
7. `songs` table shows a row with updated `mastery_score` after a completion (inspect `<user_data>/database/userdata.db`).

## Do NOT touch

- The self-paced path: `_check_chord`, `_complete_chord`, `_advance_song_chord`, `mistakeActive` logic — the mode gate routes around them; it does not modify them.
- `EvaluationService`'s public QML contract and sequences.json format.
- `SIMPLIFY_LEVELS`, hand-mode machinery, import pipeline.
- Gemini prompt/tools (Phase 6).

## Regression watch

Onboarding evaluation (the big one — delegation refactor); self-paced feel on both imported and corpus songs; lesson-mode non-song exercises (chord/pentascale/progression use metronome-driven scroll — unrelated code, but same file); `chords`-table recording still happens in self-paced mode.
