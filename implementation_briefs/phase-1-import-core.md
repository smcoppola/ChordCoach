# Phase 1 — Import Core: MusicXML + MIDI Fidelity + Step Schema v2

**Size: L. Dependencies: none. Read `00-README.md` first.**

## Mission

1. Add MusicXML (`.xml`, `.mxl`, `.musicxml`) import with full fidelity: real time signatures, dynamics, articulations, native fingerings, dotted/tuplet durations.
2. Fix known MIDI-import defects: hardcoded 4/4 meter, discarded tempo map / velocity / sustain-pedal data, destructive hand-mode round-trips.
3. Introduce **Step Schema v2** — the versioned data model Phases 2–6 depend on.
4. Groundwork: source-file hashing + copies (duplicate detection now; Verovio print view later).
5. Drive-by one-line bug fix in the Gemini tool schema.

This phase is shippable alone: imports become correct and richer even though the renderer can't yet draw the new marks (Phase 2 does that; unknown fields are ignored by current consumers).

## Current state (verified facts — locate symbols by grep, line numbers are hints)

**Import flow:** `src/ui/DashboardView.qml` `FileDialog` (~line 706, `nameFilters: ["MIDI files (*.mid *.midi)"]`) → `Music21Service.import_midi_file(url)` slot (`src/logic/services/music21_service.py` ~:653) → `MidiImportWorker(QThread)` (~:41) → `_do_import(path)` (~:683), which runs:

1. `midi_ingestor.parse_and_quantize(path)` (`src/logic/services/midi_ingestor.py`, 303 lines, pure functions) — pretty_midi parse; keeps only the **two busiest** non-drum tracks (3+ silently dropped); 80 ms chord-onset clustering (`CHORD_WINDOW_SEC`); snap to 16th grid (`GRID = 0.25`); returns `{"title", "bpm", "groups": [{offset, duration, notes: [(pitch, hand)]}]}`.
2. `assign_hands(groups)` (~:96, `HAND_ALGO_VERSION = 2`) — Viterbi DP over split indices; **only for single-track files**. Two-track files derive hands from track membership (lower mean pitch = left).
3. `Music21Service._build_score_from_groups(groups, ...)` (~:730) — Krumhansl key detection on a probe stream, enharmonic respelling, **`meter.TimeSignature('4/4')` hardcoded** (~:762), two-part treble/bass Score, `makeNotation`.
4. `_extract_steps_from_score(score)` (~:413) — **shared with corpus loading**; derives hand from `BassClef`/part index (~:434); injects fingerings via `src/logic/utils/fingering_optimizer.py` (`inject_fingering_to_stream`, `distribute_chord_fingers`); builds the step list keyed by offset.
5. `_score_difficulty(steps)` (~:795) — heuristic Grade 1–10.
6. Saves JSON to `<user_data>/database/user_songs/<slug>-<unix_ts>.json`, id `user::<slug>-<unix_ts>`.

**User-song JSON v1 fields:** `id, title, artist ("Imported MIDI"), level ("Grade N"), key, key_sharps, bpm, hand_algo, hand_mode, barlines, steps, quantized_groups, source_file, imported_at`. `quantized_groups` is the source of truth for re-arrangement. The source `.mid` is **not** copied — `source_file` is just the original path.

**Step v1 shape:** `{offset, pitches[], spellings[], hands[], fingers[], ties[], beams[], duration, rests[]}`. `duration` is a **single scalar per step** — whichever element arrived first at that offset wins (`offset_map[off]['duration']`, ~:449), so a LH whole note under RH quarters is recorded wrong.

**Difficulty levels:** `SIMPLIFY_LEVELS` (4 levels, ~:553) + `_simplify_groups(groups, level)` (~:560). Requested via id suffix `user::<slug>::L<n>`; `_load_user_song_steps` (~:818) parses the suffix and regenerates from `quantized_groups` **synchronously on the UI thread** (blocks UI). It also contains the v1→v2 hand-algo migration precedent (~:844-854): lazy, in-memory, try/except fallback.

**Hand modes:** `get_user_song_hand_mode`/`set_user_song_hand_mode` slots (~:946-976) → `_apply_hand_mode(groups, mode)` (~:902) → `_rebuild_user_song_record` (~:915, **overwrites `quantized_groups`** ~:935). **Defect:** `"auto"` mode always re-runs the single-track Viterbi, so a 2-track file's authoritative track-based hand split is destroyed by any hand-mode round-trip or algo migration.

**Other known defects fixed here:**
- Only `tempi[0]` is surfaced as `bpm` (`_make_beat_converter`, `midi_ingestor.py` ~:228); the full tempo map, note velocities, CC64 pedal, and `pm.time_signature_changes` are discarded.
- The Krumhansl probe stream (`music21_service.py` ~:741-744) gives every note `quarterLength=0.25`, losing duration weighting for key detection.
- No duplicate detection (re-import creates a second record).
- Gemini tool schema bug: `src/logic/services/gemini_service.py` — the `exercise_type` description (~:351) lists `chord, pentascale, progression, listen, hands_together, sustain_pedal, steady_pulse` but **omits `song_application`**, which the system prompt (~:289) explicitly requires.

**Signals:** `Music21Service` declares `importSucceeded(str)`, `importFailed(str)`, `userSongsChanged` (~:65-72). `DashboardView.qml` `Connections` (~:750-760) handles success/failure; success auto-opens the difficulty picker via `requestSongWithDifficulty`.

## Tasks (in order)

### 1. Tests + fixtures first

Create `tests/` with `conftest.py` adding `src/` to `sys.path`, and fixture files under `tests/fixtures/`:
- `waltz_34.musicxml` — a short 3/4 piece, two staves (treble+bass), containing at least one dotted quarter, one eighth-note triplet, a dynamic marking (e.g. `p`), a fingering, and a tie. Generate it in a helper script with music21 and commit the XML.
- `two_track.mid` — 2-track MIDI (melody + bass), 3/4 time signature event, one mid-file tempo change, varied velocities, a CC64 pedal down/up pair. Generate with pretty_midi and commit.
- `single_track.mid` — 1-track file spanning both hands (for Viterbi path).
- `v1_song.json` — a **frozen copy** of a v1 user-song record (build one by running the current pipeline on `single_track.mid` before making changes, or hand-author matching the v1 fields above).

Test files (write them as you implement, but define expected behavior up front):
- `tests/test_midi_ingestor.py` — time-signature extraction (3/4 comes through with correct beat offset), tempo map has 2 entries, velocities captured per note, pedal events captured, tracks/hand tagging unchanged for 2-track input.
- `tests/test_step_schema.py` — `migrate_record` on `v1_song.json` yields v2 shape (per-step `durations[]` == broadcast of v1 `duration`, `time_signatures == [{"offset": 0, "numerator": 4, "denominator": 4}]`, empty `tuplets`/`articulations`, `schema_version == 2`) and is **idempotent** on v2 input; `compute_barlines` for 4/4, 3/4, 6/8, and a mid-piece 4/4→3/4 change; `groups_from_steps` round-trip sanity.
- `tests/test_simplify.py` — `_simplify_groups` output at each level respects note caps/spans; a simplified 3/4 piece still carries 3/4 (meter preserved through rebuild).
- `tests/test_musicxml_import.py` — importing `waltz_34.musicxml` (call the worker's internal `_do_import_musicxml` directly, no Qt loop) produces: 3/4 in `time_signatures`, per-note `durations` including 1.5 (dotted quarter), a tuplet descriptor on the triplet notes, the dynamic in `dynamics[]`, the native fingering preserved (not overwritten by the optimizer), hands split by clef.

Note: `Music21Service` methods need a QObject instance; keep pure logic (schema, barlines, groups) in the new `step_schema.py` so most tests avoid Qt entirely. For `_do_import_musicxml`-level tests, instantiating `Music21Service` without an event loop is acceptable if construction has no hard Qt-loop dependency — if it does, factor the import body into a module-level function taking the service's dependencies explicitly.

### 2. New module `src/logic/utils/step_schema.py`

Owns the versioned data model. Public API:

- `CURRENT_SCHEMA_VERSION = 2`
- `migrate_record(record: dict) -> dict` — normalizes any record (v1 user-song JSON, corpus-derived song dict) to v2 **in memory**. v1→v2: per-step `durations = [duration] * len(pitches)`, `tuplets = [None] * n`, `articulations = [[] for _ in pitches]`, `velocities = [None] * n`; song-level defaults `time_signatures = [{"offset": 0, "numerator": 4, "denominator": 4}]`, `tempo_map = [{"offset": 0, "bpm": record.get("bpm") or 100}]`, `pedal_events = []`, `dynamics = []`, `source_type = "midi"`. Must be idempotent. Files are **only rewritten on user-initiated saves** (hand-mode change, rename) — same policy as the existing hand-algo migration.
- `compute_barlines(time_signatures: list, end_beat: float) -> list[float]` — barline beat offsets from the time-sig map (handles mid-piece changes; a change resets the measure origin at its offset).
- `groups_from_steps(steps: list) -> list` — projects v2 steps to `[{offset, duration, notes: [(pitch, hand)]}]` so `_simplify_groups` works for MusicXML imports that have no MIDI-derived `quantized_groups`.

### Step Schema v2 definition (authoritative)

Song-level additions: `schema_version: 2`, `source_type: "midi"|"musicxml"`, `source_hash` (SHA-1 hex of source bytes), `source_copy` (relative path under `user_songs/sources/`), `time_signatures: [{offset, numerator, denominator}]`, `tempo_map: [{offset, bpm}]`, `pedal_events: [{offset, down: bool}]`, `dynamics: [{offset, mark, hand}]`, `track_hands_reliable: bool`, `pristine_groups` (only when `track_hands_reliable`), `practice_mode` (reserved for Phase 4; absent now).

Step-level additions (all arrays parallel to `pitches[]`): `durations[]` (true per-note quarterLength), `tuplets[]` (`None` or `{"actual": int, "normal": int, "pos": "start"|"continue"|"stop"}`), `articulations[]` (list of strings per note: `"staccato"`, `"accent"`, `"tenuto"`, ...), `velocities[]` (int or `None`). Keep `duration` = `max(durations)` for v1 consumers.

Wire `migrate_record` into `load_song_as_steps` and `_load_user_song_steps` so **every consumer always sees v2 shape** — no branching in `ChordTrainerService` or `NotationView`.

### 3. `midi_ingestor.py` extensions (pure-function additions; do not alter Viterbi weights or `notes` tuple shape)

- Read `pm.time_signature_changes` → `time_signatures` (offsets converted via the existing `_BeatConverter`); default `[{offset: 0, 4/4}]`.
- Export the full tempo map from `pm.get_tempo_changes()` (offsets in beats); keep `bpm` = first entry for compatibility.
- Capture per-note velocity in a **parallel structure** (e.g. per-group `velocities` list aligned to `notes`) so `assign_hands` is untouched.
- Extract CC64 → `pedal_events: [{offset, down}]` (threshold ≥64 = down).
- `parse_and_quantize` return dict gains `time_signatures`, `tempo_map`, `pedal_events`; existing keys unchanged.

### 4. `_build_score_from_groups` fixes

- Accept a `time_signatures` list parameter; insert each `meter.TimeSignature` at its offset (replaces the 4/4 hardcode). All callers (import, simplify rebuild, hand-mode rebuild) pass the song's map — this is what keeps meter through SIMPLIFY re-arrangement.
- Key-detection probe stream: use each group's real `duration` for `quarterLength` instead of uniform 0.25.

### 5. Hand-mode destruction fix

At MIDI import time, when the source had ≥2 tracks (`single_track == False`): store `track_hands_reliable: true` and `pristine_groups` (deep copy of the quantized groups with track-derived hands). In `_apply_hand_mode`, `"auto"` **restores hands from `pristine_groups`** when `track_hands_reliable`, instead of running the single-track Viterbi. Single-track sources behave as today.

### 6. MusicXML import path

In `music21_service.py`:
- Rename `MidiImportWorker` → `ImportWorker`; add `@Slot(str) def import_file(self, file_url)`; keep `import_midi_file` as a one-line alias (QML compatibility).
- Worker dispatches on extension: `.mid/.midi` → `_do_import_midi` (current body); `.xml/.mxl/.musicxml` → `_do_import_musicxml`: `music21.converter.parse(path)` → **directly** into `_extract_steps_from_score` (no quantization, no hand inference — the clef heuristic already maps BassClef→left; single-staff scores default all notes to `"right"` and remain eligible for hand-mode overrides). Synthesize `quantized_groups = step_schema.groups_from_steps(steps)` so difficulty levels work. Both paths converge on a shared `_finalize_import(record_fields)` (difficulty scoring, slug/id, JSON save, signals) — extract it from the current `_do_import`.
- `_extract_steps_from_score` extensions: collect per-note `durations`, `tuplets` (from `note.duration.tuplets` — map to actual/normal/pos), `articulations` (staccato/accent/tenuto class names), `dynamics` (from `dynamics.Dynamic` objects, with owning-hand attribution by part), time signatures (`getTimeSignatures` dedup by offset), and metronome marks (`tempo.MetronomeMark`) → `tempo_map`. **Fingering guard:** run `inject_fingering_to_stream` only when the part contains no native `Fingering` articulations — MusicXML fingerings win.
- Documented trade-off (add a comment where levels regenerate): simplified levels (`::L<n>`) of a MusicXML import are re-quantized arrangements and lose tuplet/articulation fidelity; Level-0 (no suffix) always loads full-fidelity stored steps.

### 7. Duplicate detection + source copy

In `_finalize_import`: SHA-1 the source file bytes → `source_hash`; copy the source to `<user_songs_dir>/sources/<hash><ext>` → `source_copy` (create dir; skip copy if already present). Before importing, scan `_user_songs` for a matching `source_hash`; on match emit new signal `importDuplicate(str existing_song_id, str title)` and abort the import (no record written).

### 8. QML changes (`src/ui/DashboardView.qml`)

- `FileDialog.nameFilters` → `["Music files (*.mid *.midi *.xml *.mxl *.musicxml)", "MIDI files (*.mid *.midi)", "MusicXML files (*.xml *.mxl *.musicxml)"]`; call `import_file` instead of `import_midi_file`.
- Handle `onImportDuplicate` in the existing `Connections` block: toast "Already in your library" with an "Open existing" action that calls the existing `requestSongWithDifficulty(existingId)`.
- Update the two "IMPORT MIDI" button labels (~:841, ~:1351) to "IMPORT MUSIC".

### 9. Async level regeneration

`::L<n>` regeneration currently runs on the UI thread inside `start_song` → `_load_user_song_steps`. Move the rebuild (`_simplify_groups` → `_build_score_from_groups` → `_extract_steps_from_score`) onto the same worker-thread pattern as import. `ChordTrainerService` already exposes an `isLoading` state that QML watches (`DashboardView.qml` ~:742) — keep the UI contract identical, just non-blocking. Ensure two rapid difficulty switches serialize (reuse the worker-busy guard, ~:659-661).

### 10. Gemini enum drive-by

`gemini_service.py` `exercise_type` description (~:351): append `song_application` to the listed values. One line; no other prompt changes in this phase (Phase 6 does the rest).

## Acceptance gates

**Automated:** all `tests/` pass (`python -m pytest tests/ -x -q`).

**Human (run `python src/app.py`):**
1. Import `waltz_34.musicxml` → correct key shown; song plays through in the trainer; barlines every 3 beats (verify count vs. the piece, even though the renderer can't yet draw the 3/4 numeral).
2. Import `two_track.mid` → hands match tracks; open hand-mode chips, switch Split C4 → back to Auto → hands are the **original track split** (not re-derived).
3. Re-import the same file → duplicate prompt appears, no second "My Songs" entry.
4. Import the pre-phase `v1_song.json`'s source again is not required — instead: place `v1_song.json` in the user_songs dir, launch, play it → loads and plays normally (lazy migration).
5. Difficulty picker Level 2 on a long imported song → UI stays responsive during regeneration.
6. A corpus song (e.g. via song picker) still loads and displays identically to before.

## Do NOT touch

- `assign_hands` Viterbi weights/logic and the `notes: [(pitch, hand)]` tuple shape.
- `_score_difficulty` heuristic, slug/id format, `songRequested` relay, difficulty-picker UX.
- `ChordTrainerService` and `NotationView` — zero changes in this phase (the normalizer guarantees they see v2 shape).
- Corpus catalog machinery (`get_catalog_level`, `search_catalog`, `corpus_indexer.py`).
- On-disk v1 files except on explicit user-initiated saves.

## Regression watch

Corpus loading (shared extractor), existing v1 saved songs, onboarding evaluation (unaffected but verify launch), lesson mode exercise dispatch.
