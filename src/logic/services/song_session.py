"""
The song player: one piece in front of the student, self-paced or in rhythm.

Moved out of ChordTrainerService. The trainer still owns what every exercise
shares — the current target, the scroll position, input gating, the signals
QML binds to — and SongSession works through it (`self._t`) for those. What
belongs to the piece lives here: the loaded steps and the step index, title
and key, the practice preferences, the RhythmEngine and its note states, and
the result of the last run.

Self-paced play is the permanent default: a song the user has never played
always starts there, and its code path is untouched by rhythm mode.
"""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Dict, List

from PySide6.QtCore import QTimer  # type: ignore

from logic.services import coach_prompts  # type: ignore
from logic.services.rhythm_engine import RhythmEngine  # type: ignore
from logic.utils.sm2 import quality_for_song  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    from logic.services.chord_trainer import ChordTrainerService


class SongSession:
    """The piece being played and everything derived from it."""

    # Per-pitch parallel arrays carried on every v2 step; all must be sliced
    # together so indices stay aligned after a hand filter.
    PER_PITCH_STEP_KEYS = ("pitches", "hands", "fingers", "spellings", "ties",
                            "beams", "durations", "tuplets", "velocities")

    def __init__(self, trainer: "ChordTrainerService"):
        self._t = trainer

        self.song_id: str = ""
        self.title: str = ""
        self.key: str = ""
        self.key_sharps: int = 0
        self.composer: str = ""
        self.completed: bool = False
        self.end_beat: float = 0.0
        self.steps: List[Dict] = []
        self.index = 0
        self.tempo_map: List[Dict] = []
        self.barlines: List[float] = []
        self.wrong_notes: int = 0
        self.result: Dict = {}

        # ── Dual pacing (self-paced ⟷ rhythm) ──
        self.pacing_mode: str = "self_paced"   # "self_paced" | "rhythm"
        self.practice_hands: str = "both"      # "both" | "right" | "left"
        self.note_states: List[str] = []       # aligned with the trainer's scrolling notes
        self.sn_index: List[int] = []          # engine note index → scrolling-notes index
        self.loop_only: bool = False

        self.engine = RhythmEngine(trainer)
        self.engine.beatChanged.connect(self.on_rhythm_beat)
        self.engine.noteStateChanged.connect(self.on_rhythm_note_state)
        self.engine.metronomeTick.connect(self.on_rhythm_metronome_tick)
        self.engine.finished.connect(self.on_rhythm_finished)

    def on_finished(self):
        """Called 1.5 s after the last song note is played."""
        # Self-paced completion: a small fixed gain, docked per wrong note.
        # (Rhythm mode records from on_rhythm_finished instead — it never
        # reaches the trainer's _complete_chord, which is what schedules this
        # callback for self-paced play.)
        if self.pacing_mode == "self_paced":
            mastery = max(1.0, 3.0 - float(self.wrong_notes))
            self.record_completion(
                mastery_gained=mastery,
                result={
                    "mode": "self_paced",
                    "wrongNotes": self.wrong_notes,
                    "masteryGained": mastery,
                },
            )

        if not self._t._is_lesson_mode:
            # Free-play song — just return to the home screen
            print(f"ChordTrainer: Song '{self.title}' complete (free-play). Returning to home.")
            self._t.stop_session()
            return

        # Lesson song — the coach acknowledges it while introducing what comes next.
        self._t._pending_coach_note = coach_prompts.note_song_finished(self.title or "the piece")
        self._t._next_chord()

    def setup(self, chord_data):
        """Sets up a Music21 song playback exercise."""
        piece_name = chord_data.get("piece_name", "bach/bwv1.6.mxl")

        # Songs can also arrive from the AI coach, which never goes through
        # start_song. Re-read the practice preferences whenever the piece
        # changes so a previous song's rhythm mode is never inherited.
        if piece_name != self.song_id:
            self.song_id = piece_name
            self.load_prefs(piece_name)

        # Load from the new service
        assert self._t.music21 is not None, "Music21Service is not initialized!"
        song_data = self._t.music21.load_song_as_steps(piece_name)
        self.steps = song_data.get("steps", [])
        
        if not self.steps:
            print(f"ChordTrainer: Failed to load {piece_name}")
            self._t.statusMessageRequested.emit("error", f"Failed to load piece: {piece_name}")
            
            # Reset to IDLE so the user can try another song
            self._t._exercise_type = "chord"
            self.title = ""
            self.key = ""
            self.key_sharps = 0
            self._t.songTitleChanged.emit()
            self._t.songKeyChanged.emit()
            self._t.songKeySharpsChanged.emit()
            # In a lesson the sequencer moves on to another exercise; dropping
            # to IDLE would flash the dashboard between the two.
            if not self._t._is_lesson_mode:
                self._t._set_state(self._t.State.IDLE)
            return
            
        self._t._exercise_type = "song_application"
        self.title = song_data.get("title", "Unknown Piece")
        self.key = song_data.get("key", "Unknown Key")
        self.key_sharps = song_data.get("key_sharps", 0)
        self.composer = song_data.get("composer", "Unknown Composer")
        self._t.songTitleChanged.emit()
        self._t.songKeyChanged.emit()
        self._t.songKeySharpsChanged.emit()
        self._t.songComposerChanged.emit()

        self.tempo_map = song_data.get("tempo_map", []) or []

        if self._t._playback_service:
            self._t._playback_service.load(
                steps=self.steps,
                tempo_map=self.tempo_map,
                time_signatures=song_data.get("time_signatures", []),
                pedal_events=song_data.get("pedal_events", [])
            )

        self.index = 0
        self._t._required_hold_ms = 0
        self._t.lessonStateChanged.emit()

        # Build scrolling notes for the whole song
        sn = []
        for step in self.steps:
            offset = step['offset']
            duration = step['duration']
            
            # 1. Rests
            if 'rests' in step:
                for r in step['rests']:
                    sn.append({
                        "is_rest": True,
                        "duration_beats": float(r['duration']),
                        "start_beat": float(offset),
                        "hand": "R" if r['hand'] == "right" else "L"
                    })
            
            # 2. Notes
            if 'pitches' in step:
                pitches = step['pitches']
                hands = step['hands']
                fingers = step.get('fingers', [1] * len(pitches))
                ties = step.get('ties', [None] * len(pitches))
                beams = step.get('beams', [None] * len(pitches))
                spellings = step.get('spellings', [None] * len(pitches))
                durations = step.get('durations', [duration] * len(pitches))
                tuplets = step.get('tuplets', [None] * len(pitches))
                
                for i, p in enumerate(pitches):
                    hand_tag = hands[i] if i < len(hands) else "right"
                    f_num = fingers[i] if i < len(fingers) else 1
                    t_val = ties[i] if i < len(ties) else None
                    b_val = beams[i] if i < len(beams) else None
                    s_val = spellings[i] if i < len(spellings) else None
                    d_val = durations[i] if i < len(durations) else duration
                    tuplet_val = tuplets[i] if i < len(tuplets) else None
                    
                    sn.append({
                        "pitch": p,
                        "spelling": s_val,
                        "hand": "R" if hand_tag == "right" else "L",
                        "finger": f_num,
                        "tie": t_val,
                        "beam": b_val,
                        "start_beat": float(offset),
                        "duration_beats": float(d_val),
                        "tuplet": tuplet_val
                    })

        # 3. Time Signatures
        time_sigs = song_data.get("time_signatures", [])
        for ts in time_sigs:
            sn.append({
                "is_time_sig": True,
                "start_beat": float(ts.get("offset", 0.0)),
                "numerator": int(ts.get("numerator", 4)),
                "denominator": int(ts.get("denominator", 4))
            })

        # 4. Dynamics
        dynamics = song_data.get("dynamics", [])
        for d in dynamics:
            sn.append({
                "is_dynamic": True,
                "start_beat": float(d.get("offset", 0.0)),
                "mark": str(d.get("mark", "p")),
                "hand": "R" if d.get("hand") == "right" else "L"
            })

        # The beat at which all notation has finished (also the barline fallback's end)
        if self.steps:
            last = max(self.steps, key=lambda s: float(s['offset']) + float(s['duration']))
            self.end_beat = float(last['offset']) + float(last['duration'])
        else:
            self.end_beat = 0.0

        # 5. Barlines
        barlines = song_data.get("barlines", [])
        if not barlines and time_sigs:
            from logic.utils.step_schema import compute_barlines
            barlines = compute_barlines(time_sigs, self.end_beat)
        self.barlines = sorted(float(b) for b in barlines)
        for b in barlines:
            sn.append({
                "is_barline": True,
                "start_beat": float(b),
                "duration_beats": 0.0
            })

        # Ensure purely deterministic timeline ordering
        sn.sort(key=lambda x: (x.get("start_beat", 0.0), not bool(x.get("is_time_sig", False)), not bool(x.get("is_dynamic", False)), not bool(x.get("is_barline", False)), x.get("pitch", 0)))

        self._t._scrolling_notes = sn
        self._t.scrollingNotesChanged.emit()

        self.completed = False
        self._t.songCompletedChanged.emit()

        self._t._set_stepped_scroll_beat(0.0)

        # User-driven pacing (no metronome)
        self._t._scroll_bpm = 0
        self._t.scrollBpmChanged.emit()

        # Target chord name gives context
        self._t._target_chord_name = f"Song: {self.title}"
        self._t.targetChordChanged.emit(self._t._target_chord_name)

        # ── Phase 4: pacing fork ────────────────────────────────────
        # Everything above this point is shared by both modes. Below, the two
        # paths are mutually exclusive: rhythm mode starts the engine and never
        # touches advance_step / the trainer's _check_chord, and self-paced mode runs
        # exactly as it always has with an empty songNoteStates array.
        self.wrong_notes = 0
        self.result = {}
        self._t.songResultChanged.emit()

        # Steps the student is responsible for playing, after the hand filter.
        # PlaybackService keeps the unfiltered list it was handed above, so the
        # app can still play the other hand for a duet.
        self.steps = self.filter_steps_for_practice_hands(self.steps)

        # The filter can empty the list outright — a hand that never plays, or a
        # section that is all rests. Say so instead of leaving the student in
        # front of a sheet that will never accept a note.
        if not self.steps:
            print(f"ChordTrainer: '{self.title}' has nothing to play for hands='{self.practice_hands}'")
            self._t.statusMessageRequested.emit(
                "info", "Nothing to play here — try the other hand or 'both'.")
            return

        if self.pacing_mode == "rhythm":
            self.start_rhythm_run()
        else:
            self.note_states = []
            self.sn_index = []
            self._t.songNoteStatesChanged.emit()
            # Set up the first step
            self.advance_step()

    def is_user_song(self, song_id: str) -> bool:
        return bool(song_id) and song_id.startswith("user::")

    def load_prefs(self, song_id: str):
        """
        Restores this song's pacing mode and practice hands.

        A song with no stored preference — i.e. one that has never been played —
        always comes back as self-paced. That is a product guarantee, not a
        fallback: rhythm mode is opt-in, per song, forever.
        """
        mode, hands = "self_paced", "both"
        try:
            if self.is_user_song(song_id) and self._t.music21:
                mode = self._t.music21.get_user_song_pref(song_id, "practice_mode", "self_paced")
                hands = self._t.music21.get_user_song_pref(song_id, "practice_hands", "both")
            elif song_id and self._t.db:
                mode = self._t.db.get_app_setting(f"practice_mode::{song_id}", "self_paced")
                hands = self._t.db.get_app_setting(f"practice_hands::{song_id}", "both")
        except Exception as e:
            print(f"ChordTrainer: Could not read practice prefs for '{song_id}': {e}")

        self.pacing_mode = mode if mode in ("self_paced", "rhythm") else "self_paced"
        self.practice_hands = hands if hands in ("both", "right", "left") else "both"
        self._t.pacingModeChanged.emit()
        self._t.practiceHandsChanged.emit()
        print(f"ChordTrainer: '{song_id}' practice mode='{self.pacing_mode}', hands='{self.practice_hands}'")

    def save_pref(self, key: str, value: str):
        if not self.song_id:
            return
        try:
            if self.is_user_song(self.song_id) and self._t.music21:
                self._t.music21.set_user_song_pref(self.song_id, key, value)
            elif self._t.db:
                self._t.db.set_app_setting(f"{key}::{self.song_id}", value)
        except Exception as e:
            print(f"ChordTrainer: Could not save practice pref '{key}': {e}")

    def filter_steps_for_practice_hands(self, steps):
        """
        Narrows each step to the hand the student is practising and drops every
        step that leaves the student nothing to play.

        Steps go empty two ways. A step whose notes all belong to the other hand
        is how "LH-only steps are auto-skipped" falls out for free. A step that
        never had pitches at all is a rest-only offset: both song loaders emit
        one wherever a rest starts with no note sounding under it, and the
        self-paced advance would otherwise park on it forever waiting for a
        chord the keyboard cannot produce.

        Dropping both here rather than in advance_step keeps `index`
        arithmetic — including end-of-song detection — over a list in which
        every entry is playable. PlaybackService and `end_beat` are
        computed upstream from the unfiltered steps, so the accompaniment and
        the notation still show the silence.
        """
        want = self.practice_hands if self.practice_hands in ("right", "left") else None

        out = []
        for step in steps or []:
            pitches = step.get("pitches") or []
            if not pitches:
                continue

            if want is None:
                out.append(step)
                continue

            hands = step.get("hands", [])
            keep = [i for i in range(len(pitches))
                    if (hands[i] if i < len(hands) else "right") == want]
            if not keep:
                continue

            new_step = dict(step)
            for key in self.PER_PITCH_STEP_KEYS:
                vals = step.get(key)
                if isinstance(vals, list) and len(vals) == len(pitches):
                    new_step[key] = [vals[i] for i in keep]
            out.append(new_step)
        return out

    def build_rhythm_notes(self, scrolling_notes):
        """
        Builds the engine's note list from the already-sorted `scrolling_notes`
        array, one entry per pitch, and records the index map back into it.

        Deriving both from the same sorted array is what keeps `songNoteStates`
        aligned index-for-index with `scrollingNotes`; Phase 2's `orig_i` then
        carries those indices correctly through the renderer's culling.
        """
        notes = []
        sn_index = []
        want = self.practice_hands
        hand_tag = {"right": "R", "left": "L"}.get(want)

        for i, entry in enumerate(scrolling_notes):
            if "pitch" not in entry or entry.get("is_rest"):
                continue
            # Notes of the hand the app is covering are shown but not scored.
            if hand_tag and entry.get("hand") != hand_tag:
                continue

            notes.append({
                "pitch": int(entry["pitch"]),
                "start_beat": float(entry.get("start_beat", 0.0)),
                "duration_beats": float(entry.get("duration_beats", 1.0)),
                "hand": "right" if entry.get("hand") == "R" else "left",
            })
            sn_index.append(i)

        self.sn_index = sn_index
        # Pseudo-items (barlines, rests, time sigs, dynamics) and unscored notes
        # keep "", which the renderer treats as a no-op.
        self.note_states = [""] * len(scrolling_notes)
        for idx in sn_index:
            self.note_states[idx] = "pending"
        self._t.songNoteStatesChanged.emit()

        return notes

    def rhythm_tempo(self) -> float:
        """The piece's starting tempo, scaled by the user's playback tempo slider."""
        from logic.services.playback_service import bpm_at
        bpm = bpm_at(self.tempo_map, 0.0)
        if self._t._playback_service:
            bpm *= float(self._t._playback_service.tempoScale)
        return max(20.0, bpm)

    def start_rhythm_run(self):
        """Loads the engine with the current song and starts the 4-beat count-in."""
        notes = self.build_rhythm_notes(self._t._scrolling_notes)

        self.engine.load(notes, self.rhythm_tempo(), count_in_beats=4)

        # Respect an A/B loop if one is set: the run scores only that region and
        # the mastery award is halved because it is not a full-piece play.
        self.loop_only = False
        if self._t._playback_service:
            a = float(self._t._playback_service.loopStartBeat)
            b = float(self._t._playback_service.loopEndBeat)
            if b > a >= 0:
                self.engine.set_loop(a, b)
                self.loop_only = True
            else:
                self.engine.clear_loop()
        else:
            self.engine.clear_loop()

        self._t._scroll_beat = self.engine.currentBeat
        self._t.scrollBeatChanged.emit(self._t._scroll_beat)
        # snap: the run begins at the count-in, which is a jump from wherever
        # the playhead was parked.
        self._t._emit_scroll_anchor(
            self._t._scroll_beat, self.rhythm_tempo() / 60.0, active=True, snap=True
        )

        self.engine.start()
        print(f"ChordTrainer: Rhythm run started — {len(notes)} notes at "
              f"{self.rhythm_tempo():.0f} BPM, loop_only={self.loop_only}")

    def on_rhythm_beat(self, beat: float):
        self._t._scroll_beat = beat
        self._t.scrollBeatChanged.emit(beat)
        self._t._emit_scroll_anchor(beat, self.rhythm_tempo() / 60.0, active=True)

    def on_rhythm_note_state(self, index: int, state: str):
        if 0 <= index < len(self.sn_index):
            sn_i = self.sn_index[index]
            if 0 <= sn_i < len(self.note_states):
                self.note_states[sn_i] = state
                self._t.songNoteStatesChanged.emit()

    def on_rhythm_metronome_tick(self, beat_num: int, accent: bool):
        # Routed straight to the hardware click by AppCoordinator. The generic
        # `metronomeTick` signal is deliberately not reused: its handler derives
        # a beat number from pentascale state that means nothing here.
        self._t.rhythmCountInTick.emit(beat_num, accent)

    def on_rhythm_finished(self, accuracy: float, hits: int, misses: int):
        """Scores the run, banks mastery and raises the completion overlay."""
        # The clock has stopped, so stop the view extrapolating along it —
        # otherwise the notation keeps scrolling past the end of the run.
        self._t._emit_scroll_anchor(self._t._scroll_beat, 0.0, active=False, snap=True)

        mastery = (accuracy ** 2) * 10.0
        if self.loop_only:
            mastery /= 2.0

        self.record_completion(
            mastery_gained=mastery,
            result={
                "mode": "rhythm",
                "accuracy": accuracy,
                "hits": hits,
                "misses": misses,
                "loopOnly": self.loop_only,
                "masteryGained": mastery,
            },
        )

        self.completed = True
        self._t.songCompletedChanged.emit()
        print(f"ChordTrainer: Rhythm run finished — {hits} hits / {misses} misses "
              f"({accuracy*100:.0f}%), mastery +{mastery:.2f}")

        # In a lesson the coach still gets its completion report. In free play
        # the scorecard stays up until the student dismisses it — auto-returning
        # would snatch away the "practice trouble spots" action.
        if self._t._is_lesson_mode:
            self._t._ignore_midi_until = time.time() + 99.0
            QTimer.singleShot(1500, self.on_finished)

    def record_completion(self, mastery_gained: float, result: dict):
        """Writes the play to the songs table and publishes the overlay summary."""
        result = dict(result)
        result["title"] = self.title
        result["songId"] = self.song_id
        self.result = result
        self._t.songResultChanged.emit()

        if not self.song_id:
            return
        try:
            self._t.db.record_song_play(
                filepath=self.song_id,
                title=self.title or self.song_id,
                mastery_gained=float(mastery_gained),
            )
            print(f"ChordTrainer: Recorded play of '{self.song_id}' (+{mastery_gained:.2f} mastery)")
        except Exception as e:
            print(f"ChordTrainer: Failed to record song play: {e}")

        # A loop-only run never plays the whole piece, so it is not a review of it.
        if not result.get("loopOnly"):
            quality = quality_for_song(str(result.get("mode", "self_paced")),
                                       int(result.get("wrongNotes", 0) or 0),
                                       float(result.get("accuracy", 0.0) or 0.0))
            try:
                self._t.db.record_review("song", self.review_song_id(self.song_id), quality)
            except Exception as e:
                print(f"ChordTrainer: Could not record review of '{self.song_id}': {e}")

    @staticmethod
    def review_song_id(song_id: str) -> str:
        """The song a play counts for: difficulty variants (`<id>::L2`) review the song itself."""
        return re.sub(r"::L\d+$", "", song_id)

    def set_pacing_mode(self, mode: str):
        """Switches between self-paced and rhythm practice for the current song."""
        if mode not in ("self_paced", "rhythm") or mode == self.pacing_mode:
            return

        self.pacing_mode = mode
        self._t.pacingModeChanged.emit()
        self.save_pref("practice_mode", mode)
        self.restart()

    def set_practice_hands(self, mode: str):
        """Selects which hand the student plays ("both", "right", "left")."""
        if mode not in ("both", "right", "left") or mode == self.practice_hands:
            return

        self.practice_hands = mode
        self._t.practiceHandsChanged.emit()
        self.save_pref("practice_hands", mode)
        self.restart()

    def restart(self):
        """
        Restarts the current piece under the new settings. Reloading through
        start_song is deliberate: it re-reads the preferences we just saved and
        resets every piece of derived state (engine, note states, index map,
        step list, wrong-note count) in one place.
        """
        self.engine.stop()
        self._t._active_pitches.clear()

        if self._t._exercise_type == "song_application" and self.song_id:
            self._t.start_song(self.song_id)

    def stop_rhythm_run(self):
        """Ends a rhythm run early — the only way a loop-only run ever finishes."""
        if self.engine.isRunning:
            self.engine.finish_now()

    def toggle_rhythm_pause(self):
        self.engine.toggle_pause()

    def practice_trouble_spots(self) -> int:
        """
        Clusters this run's misses by measure and loops the worst one.

        Returns the 1-based measure number, or 0 if there is nothing to drill.
        """
        if not self._t._playback_service:
            return 0

        bounds = self.measure_bounds()
        if len(bounds) < 2:
            return 0

        # Tally misses per measure from the states array.
        misses = [0] * (len(bounds) - 1)
        for sn_i in self.sn_index:
            if sn_i >= len(self.note_states):
                continue
            if self.note_states[sn_i] != "miss":
                continue
            beat = float(self._t._scrolling_notes[sn_i].get("start_beat", 0.0))
            m = self.measure_index_for_beat(bounds, beat)
            if 0 <= m < len(misses):
                misses[m] += 1

        worst = max(range(len(misses)), key=lambda m: misses[m]) if misses else -1
        if worst < 0 or misses[worst] == 0:
            return 0

        self._t._playback_service.setLoop(bounds[worst], bounds[worst + 1])
        print(f"ChordTrainer: Trouble spot = measure {worst + 1} "
              f"({misses[worst]} misses), loop {bounds[worst]}–{bounds[worst + 1]}")
        return worst + 1

    def measure_bounds(self) -> List[float]:
        """Measure boundaries in beats: [0, bar1, bar2, …, song_end]."""
        bounds = [0.0]
        for b in self.barlines:
            if b > bounds[-1] + 1e-6:
                bounds.append(float(b))
        if self.end_beat > bounds[-1] + 1e-6:
            bounds.append(float(self.end_beat))
        return bounds

    @staticmethod
    def measure_index_for_beat(bounds: List[float], beat: float) -> int:
        for m in range(len(bounds) - 1):
            if bounds[m] <= beat < bounds[m + 1]:
                return m
        return len(bounds) - 2

    def advance_step(self):
        """Sets up the current grouping of notes for a song."""
        if self.index >= len(self.steps):
            # Song complete
            return
            
        self._t._prev_target_pitches = self._t._target_pitches
        step = self.steps[self.index]
        self._t._target_pitches = step['pitches']
        self._t._target_hands = step['hands']
        
        # Pull fingers from the same source as scrolling notes to guarantee sync
        self._t._target_fingers = step.get('fingers', [1] * len(self._t._target_pitches))
        self._t.targetFingersChanged.emit()
        
        # Exact match required for songs, but intervals are meaningless here
        self._t._target_intervals = set()
        
        # Advance the playhead in the UI
        self._t._set_stepped_scroll_beat(float(step['offset']))
        
        # Reset tracking state
        self._t._hold_progress = 0.0
        self._t._is_holding = False
        self._t._waiting_for_release = False
        self._t._required_hold_ms = 0
        self._t._hold_tick_timer.stop()
        self._t._prompt_time = time.time()
        self._t._wrong_notes_count = 0
        self._t._first_note_time = 0.0
        self._t._is_simultaneous = False
        
        print(f"ChordTrainer: Song step {self.index + 1}/{len(self.steps)} at offset {self._t._scroll_beat}, pitches={self._t._target_pitches}")
        self._t.targetChordChanged.emit(self._t._target_chord_name)
        self._t.inputReady.emit()
