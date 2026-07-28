# Phase 3 — Piece Playback Sequencer

**Size: M. Dependencies: Phase 1 (shipped 2026-07-27 — per-note `durations[]`/`velocities[]`, `tempo_map`, `time_signatures`, `pedal_events` are guaranteed present on every loaded song via `step_schema.migrate_record` normalization). Read `00-README.md` first — especially the Editing discipline section.**

## Rework guardrails (binding)

- `PlaybackService` and `PlaybackBar.qml` are **new files** — the existing files you touch (`midi_hardware_service.py`, `chord_trainer.py`, `ChordTrainerView.qml`, `EnhancedSheetMusic.qml`, `app.py`) take only additive, surgical edits. Never regenerate any of them.
- **Must survive** (grep after editing): in `midi_hardware_service.py` — `LowLevelMidiOutput`, `_safe_bulk_send`, `_cmdBulkSend`, `play_chord_preview`, `play_metronome_tick`, `play_startup_riff`, `play_happy_tone`, `play_sad_tone`, `play_reconnect_ping`; in `chord_trainer.py` — `_check_chord`, `_complete_chord`, `_advance_song_chord`, `handle_midi_note` (gains only the suppression early-return), `_ignore_midi_until`.
- **Wire everything:** the PlaybackBar must be visible and functional in song mode by phase end; `PlaybackService` must be registered in `AppState` and driven by the bar — a service with no UI caller is an incomplete phase.
- **Async UI contract:** any loading/busy state the bar sets must clear on failure paths too (see the Phase 1 punch-list item about `_on_simplify_failed` for the anti-pattern).
- `music21_service.py` line numbers cited anywhere are stale after Phase 1's reorganization — grep for symbols.

## Mission

Let the user **hear any piece** (corpus or imported) through MIDI out, with tempo scaling, A/B section looping, per-hand filtering, and a meter-correct metronome. New `PlaybackService` + a `PlaybackBar` QML component. This is the first real consumer of the stored tempo data.

## Current state (verified facts — grep for symbols, line numbers are hints)

**MIDI output:** `LowLevelMidiOutput` in `src/hardware/midi_hardware_service.py` (~:17) is a ctypes binding to the RtMidi DLL (`rtmidi_out_send_message`). `MidiHardwareService` wraps it and already has a **thread-safe send pattern**: a `_cmdBulkSend` Qt signal marshals messages onto the service's own thread (~:84), and `_safe_bulk_send` (~:449) trickles chord messages 2 ms apart. Existing fixed gestures: `play_chord_preview(pitches)` (~:551, 1.5 s, velocity 80), `play_metronome_tick` (~:534, GM channel 10 wood block, accent parameter for downbeats), plus startup/happy/sad jingles. There is a `midiOutEnabled` user setting — respect it. **There is no sequencer anywhere.**

**Timing pattern to copy:** `EvaluationService` (`src/logic/services/evaluation_service.py`) runs a `PreciseTimer` (`QTimer` with `Qt.PreciseTimer`, 10 ms interval, ~:43-47) and advances a float beat position from wall-clock elapsed × beats-per-second (~:248-257). This pattern is proven in this codebase — reuse it. **Do not use a background thread** for the sequencer: it buys nothing audible (≤10 ms jitter is fine for a practice aid) and adds cross-thread hazards with the ctypes output.

**Song playhead:** in song practice, `ChordTrainerService` exposes `scrollBeat` (property, ~:325) which `EnhancedSheetMusic.qml` binds to; in song mode it is **user-driven** (`_scroll_bpm = 0` ~:1592; advance on correct notes via `_advance_song_chord` ~:2297). ChordTrainer also has a MIDI **loopback-ignore** pattern: `_ignore_midi_until` (~:2349) suppresses self-triggered input after previews.

**Services wiring:** `AppState` in `src/app.py` constructs and exposes services as QML context properties (~:106-116 area). Follow the same pattern for the new service.

**Song data at hand:** after Phase 1, `ChordTrainerService._setup_song_target` holds the loaded v2 song dict (steps + `tempo_map` + `time_signatures` + `pedal_events`) and the flattened `scrollingNotes`.

## Design (authoritative)

### New file `src/logic/services/playback_service.py` — `class PlaybackService(QObject)`

**Model.** `load(steps, tempo_map, time_signatures, pedal_events)` compiles a flat, sorted event list:
- Per note i in each step: `(beat=offset, NOTE_ON, pitch, vel)` and `(beat=offset+durations[i], NOTE_OFF, pitch)`. Velocity from `velocities[i]`, default 80 when `None`.
- Pedal: `(beat=offset, CC64, 127|0)` from `pedal_events`.
- Each event carries its note's `hand` for filtering.
Keep a cursor index; never rescan the list per tick.

**Clock.** `PreciseTimer` at 10 ms. Per tick: `playback_beat += elapsed_sec * (bpm_at(playback_beat)/60) * tempoScale`, where `bpm_at` reads the `tempo_map` (piecewise-constant; binary search or cached segment). Dispatch every event with `beat <= playback_beat` (respecting `handFilter` — filtered-out hands' events are skipped entirely, including their note-offs, since their note-ons never fired). Emit `playbackBeatChanged` throttled to ~30 Hz (Phase 2 convention).

**Sounding-note set.** Track every pitch currently on. `stop()`, `pause()`, `seek()`, and loop-wrap **flush the set with explicit NOTE_OFFs** — never rely on CC123 All-Notes-Off (cheap keyboards ignore it).

**A/B loop.** Properties `loopStartBeat`/`loopEndBeat` (−1 = unset). When `playback_beat >= loopEnd`: flush sounding set, rewind cursor to first event `>= loopStart`, set `playback_beat = loopStart`. Loop bounds are also read by ChordTrainer/NotationView in Phase 4 — keep them plain float properties.

**Metronome.** When `metronomeEnabled`: derive beat-in-measure from the `time_signatures` map (share/reuse the measure math in `step_schema.compute_barlines` — extract a helper if needed rather than duplicating) and call `MidiHardwareService.play_metronome_tick(accent=is_downbeat)` on integer-beat crossings. Correct for 3/4 and 6/8, including mid-piece meter changes.

**Output path.** All sends go through `MidiHardwareService` using the existing `_cmdBulkSend` signal pattern (queued connection onto the hardware service's thread). Do not call the ctypes object directly from PlaybackService.

**QML API.** Properties: `isPlaying`, `playbackBeat`, `tempoScale` (0.25–1.5, default 1.0), `loopStartBeat`, `loopEndBeat`, `handFilter` (`"both"|"right"|"left"`), `metronomeEnabled`. Slots: `play()`, `pause()`, `stop()`, `seek(beat)`, `setLoopA()` (captures current beat), `setLoopB()`, `clearLoop()`.

### Coordination with ChordTrainerService

- Register in `AppState` as `appState.playback`; construct after `MidiHardwareService`.
- **Full-demo suppression:** while `isPlaying` and `handFilter == "both"`, `ChordTrainerService.handle_midi_note` early-returns for note-ons (reuse/extend the `_ignore_midi_until` mechanism — simplest: ChordTrainer checks `playback.isPlaying` via a reference AppState hands it). Prevents the app hearing its own output through a physical MIDI-thru loop and prevents demo notes scoring as user input.
- **Pitch-selective suppression (duet groundwork for Phase 4):** PlaybackService keeps a ring buffer of `(pitch, send_monotonic_time)`; expose `was_just_sent(pitch, window_ms=80) -> bool`. In this phase, wire ChordTrainer to consult it only when `handFilter != "both"`; full duet scoring lands in Phase 4.
- **Playhead binding:** in `ChordTrainerView.qml`, while `playback.isPlaying`, bind the sheet's `scrollBeat` source to `playback.playbackBeat`; revert to `chordTrainer.scrollBeat` when stopped. On `stop()`, `seek` the trainer's current step position back so practice resumes where the user was, not where the demo ended.
- **Seek-by-tap (small, high value):** a `MouseArea`/`TapHandler` on the sheet maps click x → beat via the inverse linear map (`beat = current_beat + (x - noteStartX)/ppb`; both values already mirrored in `EnhancedSheetMusic.qml`) and calls `playback.seek(beat)` while playing.

### New file `src/ui/components/PlaybackBar.qml`

Shown in `ChordTrainerView.qml` **song mode only**: play/pause button, stop, tempo slider (25–150 %, live label "×0.75 / 90 BPM" using the piece's base bpm), A and B loop buttons (set at current beat; active loop shows a clear-loop button), hands segmented control (Both/RH/LH), metronome toggle. Disable the whole bar with a tooltip hint when `midiOutEnabled` is off or no output device is present.

**Loop shading:** add two float properties to `NotationView` (`loopStartBeat`, `loopEndBeat`, −1 default); when set, paint a translucent fill between their x positions behind the notes. (Small, isolated renderer addition — allowed despite Phase 2 ownership of the renderer.)

## Tests (write first)

`tests/test_playback_compile.py` — pure-logic tests on the event compiler and clock math (factor them so they're testable without Qt: e.g. module-level `compile_events(steps, pedal_events)` and `bpm_at(tempo_map, beat)`):
- Event list sorted; NOTE_OFF beats = onset + per-note duration (LH whole under RH quarters produces staggered offs).
- Velocity default 80 when `None`; imported velocities pass through.
- `bpm_at` honors a 2-entry tempo map; tempoScale multiplies rate not pitch of events.
- Hand filter drops both on and off events of the filtered hand.
- Loop wrap: cursor lands on first event ≥ loopStart; sounding set flushed (assert via injected fake sender).
- Metronome downbeat pattern for 3/4 and 6/8 maps.

## Acceptance gates

**Automated:** all tests pass.

**Human (run `python src/app.py`, MIDI output device connected):**
1. Open an imported song → PlaybackBar appears → Play: piece sounds correct, sheet scrolls with playback, notes gray as they pass.
2. Tempo slider to 50 %: audibly half speed; metronome stays locked; pitch unchanged.
3. Set A at bar 2, B at bar 4: loops seamlessly; **no stuck notes** across many wraps; Clear resumes linear play.
4. Hands = LH only: only left hand sounds; user can play RH along without their input being eaten (suppression is pitch-selective).
5. Stop mid-piece: silence immediately (no hanging tones); practice playhead is back at the user's step; user's own key presses register again.
6. 3/4 piece: metronome accents every 3rd beat.
7. `midiOutEnabled` off: bar disabled with hint; nothing crashes.

## Do NOT touch

- `ChordTrainerService` scoring/advance logic (`_check_chord`, `_advance_song_chord`) — only the input-suppression early-return and playhead binding described above.
- `LowLevelMidiOutput` internals and the C++ input extension.
- Existing preview/jingle functions (PlaybackService is additive).
- `EvaluationService`.

## Regression watch

Chord preview + ear-training replay still work during/after playback use; metronome in lesson exercises unaffected; onboarding unaffected; no MIDI feedback loop with a physical thru connection (test with suppression logging if hardware available).
