# Phase 2 — Measure-Aware Notation

**Size: L. Dependencies: Phase 1 (schema v2 fields). Read `00-README.md` first.**

⚠️ This phase is **visual QPainter geometry work**. Unit tests cannot validate most of it — the human acceptance pass at the end is the real gate. Budget iteration time with the app running.

## Mission

Add time signatures, dotted notes, tuplets, and dynamics to the existing custom renderer; compute barlines from the time-signature map; fix a latent accidental-spelling bug; land the cheapest meaningful performance fix. **No rewrite** — the renderer stays a linear beat→pixel scroller; measure-awareness comes from richer data, not a layout engine.

## Current state (verified facts — grep for symbols, line numbers are hints)

**Renderer:** `NotationView(QQuickPaintedItem)` in `src/ui/notation_view.py` (~1127 lines), registered to QML as `ChordCoach 1.0 / NotationView` in `src/app.py` (~:281). Hand-rolled QPainter engraving using the **Bravura SMuFL font** (`QFont` + raw codepoints, ~:62-78; family discovery `_get_smufl_family` ~:89). Wrapped by `src/ui/components/EnhancedSheetMusic.qml` (317 lines); consumed by `ChordTrainerView.qml` (~:555) and `OnboardingOverlay.qml` (~:460).

**Two styles** (user setting, `SettingsView.qml` ~:240): `"traditional"` (real SMuFL noteheads via `_draw_traditional_note` ~:1033) and `"enhanced"` (default — rounded capsules whose width encodes duration, finger colors, note letters; `_draw_enhanced_note` ~:1073, `_draw_enhanced_rest` ~:1107).

**Layout:** x position is a pure linear map — `x = start_x + (start_beat - current_beat) * ppb` (~:469; `ppb = width*0.10`, `s = height*0.035`, `noteStartX = width*0.28`, mirrored in the QML). `_get_layout_for_notes` (~:336) does simultaneity clustering, second-interval notehead staggering (~:411), and grid-based accidental collision packing (~:418). `_render_stems` (~:510) is a four-pass beam-aware stem renderer (slope clamped ±0.5 staff spaces; secondary 16th beams ~:679). `_render_ledgers` (~:695) dedups ledger levels with an opposite-staff `forbidden` set.

**The scrolling data:** `ChordTrainerService._setup_song_target` (`src/logic/services/chord_trainer.py` ~:1481) flattens the song's steps into the `scrollingNotes` list of dicts (`sn`) with keys `pitch, spelling, hand, finger, tie, beam, start_beat, duration_beats` plus pseudo-items `{is_rest}` and `{is_barline}` (~:1563-1570). `_render_scrolling_array` (~:767) walks this array each paint and branches on the pseudo-item keys (barline branch ~:859). Rest glyph selection thresholds ~:863; note glyph thresholds inside `_draw_traditional_note`.

**Colors/state:** completed notes gray `#888888`; active note black; future notes fade by distance (`_blend_to_black` ~:745); stems/beams gray independently (`_stem_done` ~:636). Per-note hit/miss coloring exists via `evalNoteStates` (~:824-840) but is **gated to `displayMode == "evaluation"`** (onboarding only) — Phase 4 relaxes this; don't do it here.

**What the renderer cannot draw today:** time signatures (never, anywhere), dotted notes, tuplets, dynamics, articulations, slurs, multi-voice, repeat barlines, 32nds, grace notes, clef changes, mid-piece key changes. Key signatures draw in traditional style only and return early for 0 sharps (`_draw_key_signature` ~:999).

**Perf:** every property setter calls `self.update()` (~:119-230); the beat clock emits ~100×/s; `_render_scrolling_array` runs `_get_layout_for_notes` over the **entire** `sn` array every paint (~:782) and culls only afterwards (~:790). QML adds 150 ms easing on `scrollBeat` (`EnhancedSheetMusic.qml` ~:171).

**Latent bug:** `_draw_traditional_note` (~:1051) calls `_get_accidental_from_spelling(pitch, None)` — hardcoded `None` discards the real spelling that is already present in `sn` (chord_trainer ~:1554), so enharmonics can get a wrong accidental glyph despite correct vertical placement.

**Phase 1 gave you** (via schema v2, always present after normalization): song-level `time_signatures[]`, `dynamics[]`, `tempo_map[]`; per-step parallel `durations[]`, `tuplets[]`, `articulations[]`. `step_schema.compute_barlines(time_signatures, end_beat)` exists and is tested.

## Tasks (in order)

### 1. Timeline items from v2 data (`chord_trainer.py`, `_setup_song_target` only)

Follow the existing `{is_barline}` pseudo-item pattern exactly:
- Inject `{"is_time_sig": True, "start_beat": offset, "numerator": n, "denominator": d}` — one at beat 0 and one per meter change, from `song_data["time_signatures"]`.
- Inject `{"is_dynamic": True, "start_beat": offset, "mark": m, "hand": h}` from `song_data["dynamics"]`.
- Barlines: prefer the music21-extracted `barlines` list (correct for pickups); when absent/empty, fall back to `step_schema.compute_barlines(...)`.
- Per-note fields: thread `durations[i]` and `tuplets[i]` into each note dict (`"duration_beats"` should now come from the per-note value, not the step scalar; add `"tuplet"`).

No other `ChordTrainerService` changes in this phase.

### 2. Glyph selection refactor (`notation_view.py`)

Extract `_duration_to_glyph(duration, tuplet) -> (base_glyph, flag_glyph, dots)` unifying the threshold chains in `_draw_traditional_note` and the rest branch (~:863):
- Dotted set: `{6.0: whole+dot, 3.0: half+dot, 1.5: quarter+dot, 0.75: eighth+dot, 0.375: sixteenth+dot}` → base glyph + 1 dot. Double dots optional (skip unless trivial).
- Tuplets: select the glyph from the **normalized** duration `duration * actual / normal` — a triplet eighth (0.333 qL) must render as an eighth, not a sixteenth.
- Unknown/in-between durations: keep today's nearest-threshold behavior (no crash on odd MIDI durations).

### 3. Augmentation dots

Filled ellipse right of the notehead (~`x + notehead_dx + s*1.5`); when the notehead sits **on a line** (parity of the diatonic step already computed in `_get_layout_for_notes`), nudge the dot up half a space. Dots inherit the note's current color state.

### 4. Time signatures

- SMuFL timeSig digits U+E080–U+E089, numerator stacked over denominator, centered on each staff's middle line, on **both** staves.
- Static header: draw the current meter next to the key signature (add `_draw_time_signature` sibling to `_draw_key_signature`; works in **both** styles, unlike the key sig).
- Inline `{is_time_sig}` items: draw at their beat x as they scroll (mid-piece changes). Skip drawing the beat-0 inline item when it would overlap the static header (header already shows it).

### 5. Tuplet brackets

New pass modeled on the beam pass in `_render_stems`: group consecutive notes whose `tuplet.pos` runs start→(continue)→stop; draw a thin horizontal bracket above the stem tips (clamped above beam lines when the group is beamed) with the `actual` digit centered in a gap. Beamed triplets already beam correctly from `beams[]` — this pass adds only bracket+digit. Guard against unterminated groups (missing "stop"): close at the last note of the group.

### 6. Dynamics

Draw `{is_dynamic}` items as italic marks below the owning staff (SMuFL dynamics range U+E520–U+E52F: p, f, mf, etc.). Gray the mark once `current_beat` passes its `start_beat` (match note fade behavior).

### 7. Enhanced-style parity

In enhanced mode: draw time-sig digits and dynamics text too; **skip tuplet brackets** (capsule width already encodes timing); dots unnecessary (width encodes duration).

### 8. Bug fix — spelling threading

`_draw_traditional_note`: pass the note's real `spelling` (already in the note dict) to `_get_accidental_from_spelling` instead of `None`.

### 9. Performance

1. **Cull before layout.** Maintain a sorted `start_beat` index over `sn` (rebuilt in the `scrollingNotes` setter). In `_render_scrolling_array`, `bisect` the visible window `[current_beat - 8, current_beat + width/ppb + 8]` and run layout only on that slice. Carry each item's original index as `orig_i` so future state arrays stay aligned (Phase 4 depends on this). Widen the window by the longest beam/tuplet group span so groups straddling the edge draw complete.
2. **Cap paint-triggering emissions at ~30 Hz.** The beat property can keep 10 ms backend precision, but `update()` storms at 100 Hz are wasted under the 150 ms QML easing. Throttle in the property setter (only `update()` if ≥33 ms since last, or value snapped >0.1 beat).
3. Try `self.setRenderTarget(QQuickPaintedItem.FramebufferObject)` in `__init__` — one line, often free.

Do **not** attempt a QSGNode/scene-graph rewrite or pixmap caching in this phase.

## Out of scope (do not add)

Repeat barlines, multi-voice per staff, grace notes, ornaments, clef changes, mid-piece key signature changes, slurs, lyrics, 8va, articulation glyphs (data exists from Phase 1; rendering them is deferred).

## Acceptance gates

**Automated:** existing `tests/` still pass; add `tests/test_glyph_selection.py` for `_duration_to_glyph` (pure function: dotted set, triplet normalization, fallback thresholds).

**Human (run `python src/app.py`, both notation styles unless noted):**
1. Import the Phase-1 `waltz_34.musicxml`: 3/4 shown in header; barlines every 3 beats aligned with downbeats; dotted quarter shows notehead+dot (traditional); triplet shows bracket+3 over an eighth-note group (traditional); `p` mark appears below the correct staff and grays after the playhead passes.
2. A corpus 4/4 piece renders identically to pre-phase (visual diff by eye; pay attention to beams, accidentals, ties).
3. A piece with F♭/E♯-style spellings (or any flat-key corpus piece) shows correct accidental glyphs in traditional style.
4. Long piece (several hundred measures — a long corpus work or generated fixture): scrolling stays smooth start to end; no beam/tuplet groups pop in half-drawn at screen edges.
5. Onboarding evaluation overlay still renders and colors hit/miss notes as before.

## Do NOT touch

- `evalNoteStates` gating (`displayMode == "evaluation"`) — Phase 4's job.
- `_get_layout_for_notes` clustering/stagger/accidental-packing logic (extend inputs, don't restructure).
- The `enhanced` capsule geometry and finger-color scheme.
- `EnhancedSheetMusic.qml` property contract (`scrollBeat`, `scrollingNotes`, easing) — additions OK, changes no.
- ChordTrainer beyond `_setup_song_target` item injection.

## Regression watch

Onboarding evaluation rendering; pentascale/progression lesson exercises (they use the same renderer with metronome-driven scroll); enhanced-style capsule layout; settings toggle between styles mid-song.
