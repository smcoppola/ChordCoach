import os
import time
import random
import json
from typing import Set, List, Dict, Tuple, Optional
from datetime import datetime
from enum import Enum, auto
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt # type: ignore
from logic.services.rhythm_engine import RhythmEngine # type: ignore
from logic.services.lesson_sequencer import LessonSequencer, review_exercises # type: ignore
from logic.services import coach_prompts # type: ignore
from logic.utils.sm2 import quality_for_chord, quality_for_song # type: ignore
from logic.utils import chord_types # type: ignore
from logic.services.circle_tutorial import CircleTutorial, DominantMotionDrill # type: ignore
import music21
import re

class LessonState(Enum):
    IDLE = auto()               # Not in a lesson
    LOADING = auto()            # Initial lesson loading
    AI_SPEAKING = auto()        # Coach is speaking (or about to); input is paused
    USER_PLAYING = auto()       # Exercise active, accepting MIDI input
    WAITING_TO_BEGIN = auto()   # Waiting for user to click begin

class ChordTrainerService(QObject):
    # Signals for QML
    activeChanged = Signal(bool)
    targetChordChanged = Signal(str)
    chordSuccess = Signal(str, float) # chord_name, latency_ms
    pentascaleNoteHit = Signal(int, str) # index, feedback (Fast, Slow, Perfect!)
    chordFailed = Signal()
    lessonStateChanged = Signal()
    mistakeActiveChanged = Signal(bool)
    loadingStatusChanged = Signal()
    speakInstruction = Signal(str)
    speakBrief = Signal(str)              # Non-blocking brief coach commentary
    midiOutRequested = Signal(list)
    metronomeTick = Signal()
    inputReady = Signal()                 # Emitted exactly when a drill is ready for user input
    waitingForUserContinueChanged = Signal(bool)
    statusMessageRequested = Signal(str, str) # type, message (type: "info", "error", "success")

    conceptCardChanged = Signal()       # A theory card was shown or dismissed
    isCircleOfFifthsModeChanged = Signal(bool)  # Emitted when entering/leaving circle of fifths lesson
    theoryVisualDirect = Signal(dict)  # Directly push visual state from Python (bypass AI)
    targetFingersChanged = Signal()
    pentascaleNotesChanged = Signal()
    currentNoteIndexChanged = Signal()
    scrollBeatChanged = Signal(float)
    scrollAnchorChanged = Signal()
    # True when the current mode wants a live coach, False when it does not.
    # Free play does not: the coordinator releases the session on False so a
    # dropped socket cannot raise the reconnect overlay mid-piece.
    coachNeededChanged = Signal(bool)
    scrollingNotesChanged = Signal()
    scrollBpmChanged = Signal()
    songTitleChanged = Signal()
    songKeyChanged = Signal()
    songKeySharpsChanged = Signal()
    songComposerChanged = Signal()
    songCompletedChanged = Signal()

    # Phase 4 — dual pacing modes
    pacingModeChanged = Signal()
    practiceHandsChanged = Signal()
    songNoteStatesChanged = Signal()
    songResultChanged = Signal()
    rhythmCountInTick = Signal(int, bool)  # count-in beat number, is_accent

    # How long a lesson waits for the coach to start talking after a prompt.
    SPEECH_START_TIMEOUT_MS = 8000

    # For collaborators (circle_tutorial) that set the lesson state.
    State = LessonState

    # The chord vocabulary (see logic/utils/chord_types.py).
    CHORD_TYPES = chord_types.CHORD_TYPES
    CHORD_TYPE_ALIASES = chord_types.CHORD_TYPE_ALIASES
    PENTASCALE_PATTERNS = chord_types.PENTASCALE_PATTERNS
    ROOT_NOTES = chord_types.ROOT_NOTES

    def __init__(self, db_manager, curriculum_service=None, settings_manager=None, music21_service=None):
        super().__init__()
        self.db = db_manager
        self.curriculum = curriculum_service
        self.settings = settings_manager
        self.music21 = music21_service

        # State Machine
        self._state = LessonState.IDLE

        self._current_track = ""
        self._current_milestone_id = ""
        self._target_chord_name = ""
        self._target_chord_type = ""
        self._target_formula_text = ""
        self._target_intervals: Set[int] = set()
        self._current_inversion: int = 0
        self._target_pitches: List[int] = []
        self._target_hands: List[str] = []  # "left" or "right" for each target pitch
        self._target_fingers: List[int] = [] # 1-5 for each pitch
        self._pedal_type: str = "" # "direct", "legato", or ""
        self._pedal_satisfied = False
        self._is_pedal_down = False
        self._pedal_down_time = 0.0

        # Track currently depressed keys (MIDI pitches)
        self._active_pitches: Set[int] = set()
        self._waiting_for_release = False
        self._prompt_time: float = 0.0

        # Performance Tracking State
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False

        self._scroll_beat: float = 0.0

        # Whether the current mode wants a live coach. Starts True: everything
        # except free play does.
        self._coach_needed: bool = True

        # Scroll anchor for the continuously clocked exercises. See the
        # scrollAnchor property; self-paced play deliberately does not use it.
        self._scroll_anchor: dict = {
            "beat": 0.0, "bps": 0.0, "snap": True, "active": False, "seq": 0,
        }
        self._last_anchor_time: float = 0.0
        self._scrolling_notes: list = []
        self._scroll_bpm: int = 0
        self._song_title: str = ""
        self._song_key: str = ""
        self._song_key_sharps: int = 0
        self._song_composer: str = ""
        self._song_completed: bool = False
        self._song_end_beat: float = 0.0

        # ── Phase 4: dual pacing (self-paced ⟷ rhythm) ──
        # Self-paced is the permanent default: a song the user has never played
        # always starts here, and its code path is untouched by rhythm mode.
        self._song_id: str = ""
        self._pacing_mode: str = "self_paced"   # "self_paced" | "rhythm"
        self._practice_hands: str = "both"      # "both" | "right" | "left"
        self._song_note_states: List[str] = []  # aligned with _scrolling_notes
        self._song_tempo_map: List[Dict] = []
        self._song_barlines: List[float] = []
        self._song_wrong_notes: int = 0
        self._song_result: Dict = {}
        self._rhythm_sn_index: List[int] = []   # engine note index → scrollingNotes index
        self._rhythm_loop_only: bool = False

        self._rhythm_engine = RhythmEngine(self)
        self._rhythm_engine.beatChanged.connect(self._on_rhythm_beat)
        self._rhythm_engine.noteStateChanged.connect(self._on_rhythm_note_state)
        self._rhythm_engine.metronomeTick.connect(self._on_rhythm_metronome_tick)
        self._rhythm_engine.finished.connect(self._on_rhythm_finished)

        # Dashboard and Performance Review
        self._struggled_items: List[Dict] = []
        self._current_step_data: Dict = {}

        # Lesson State
        self._is_lesson_mode = False
        self._lesson_blocks = []  # Stable snapshot of exercise blocks for sidebar
        self._lesson_progress = 0
        self._lesson_total = 0
        self._exercise_name = "Free Practice"
        self._exercise_type = "chord"  # "chord", "pentascale", or "progression"
        self._current_hand = "right"  # "right", "left", or "both"
        self._is_lesson_complete = False
        self._loading_status_text = ""
        self._require_key_release_before_eval = False
        self._listen_preview_pending = False  # Deferred MIDI preview for listen exercises
        self._ignore_midi_until = 0.0   # Ignore MIDI input while previewing
        self._session_stats: Dict[str, List[float]] = {}
        self._estimated_gen_ms = 5000.0
        self._exercise_history: List[str] = []
        self._lesson_end_pending = False # Defer showing completion UI until AI finishes speaking

        # ── Sequenced lessons ──
        # The sequencer chooses every exercise; the coach only introduces and
        # comments. See lesson_sequencer and coach_prompts.
        self._sequencer: Optional[LessonSequencer] = None
        self._coach_available = False          # set by AppCoordinator from the live connection
        self._lesson_exercise_count = 0
        self._last_lesson_type: Optional[str] = None
        self._seen_types_at_start: Set[str] = set()
        self._lesson_student_context = ""
        self._pending_coach_note = ""          # e.g. "they just finished the song", folded into the next intro
        self._exercise_struggled = False       # anything went wrong during the current exercise
        self._struggle_tip_given = False
        self._concept_card: Dict[str, str] = {}
        self._song_steps: List[Dict] = []
        self._song_index = 0
        # The chord the current target is, for the review schedule — "C Major",
        # never a display name like "C Major (1st inv)" or "Listen to the chord".
        self._review_chord = ""

        # If the coach was asked to speak but no audio arrives, stop waiting.
        self._speech_start_timer = QTimer(self)
        self._speech_start_timer.setSingleShot(True)
        self._speech_start_timer.setInterval(self.SPEECH_START_TIMEOUT_MS)
        self._speech_start_timer.timeout.connect(self._on_speech_start_timeout)
        self._is_circle_of_fifths_mode = False  # True while a scripted circle lesson is running

        # The scripted lessons on the Circle of Fifths view (see circle_tutorial.py)
        self._circle = CircleTutorial(self)
        self._dominant = DominantMotionDrill(self)
        self._playback_service = None
        
        self._target_pitches: List[int] = []
        self._prev_target_pitches: List[int] = []
        
        # Metronome Service (provided by AppState)
        self.metronome = None

        # Inter-exercise commentary streak tracking
        self._consecutive_successes = 0
        self._consecutive_struggles = 0

        # Pentascale State
        self._pentascale_sequence: List[int] = []  # Exact MIDI pitches for the 5-note sequence
        self._scale_name = ""
        self._pentascale_index = 0
        self._pentascale_fingers: List[int] = []

        # Coach personality settings (set by AppState from SettingsService)
        self.coach_personality = "Encouraging"
        self.coach_brevity = "Normal"

        # Progression State
        self._progression_steps: List[Dict] = []  # Sub-steps within a progression
        self._progression_index = 0
        self._progression_numerals: List[str] = []

        # Hold Duration State
        self._required_hold_ms = 0
        self._hold_progress = 0.0
        self._is_holding = False
        self._hold_start_time = 0.0

        self._hold_tick_timer = QTimer(self)
        self._hold_tick_timer.setInterval(33) # ~30fps update for smooth progress bar
        self._hold_tick_timer.timeout.connect(self._on_hold_tick)

        # Tracking if the AI is actively speaking (based on start/finish signals)
        self._ai_is_currently_speaking = False

        # Forgiveness timers for human key slop
        self._wrong_chord_timer = QTimer(self)
        self._wrong_chord_timer.setSingleShot(True)
        self._wrong_chord_timer.timeout.connect(self._on_wrong_chord_timeout)

        self._sustain_grace_timer = QTimer(self)
        self._sustain_grace_timer.setSingleShot(True)
        self._sustain_grace_timer.timeout.connect(self._on_sustain_grace_timeout)

        # Steady Pulse State
        self._steady_pulse_beats: int = 16  # Default total beats for steady_pulse
        self._steady_pulse_hits: List[float] = []  # Timing offsets for each successful hit
        self._steady_pulse_current_beat: int = 0
        self._steady_pulse_missed_beats: int = 0

    def set_playback_service(self, playback_service):
        """Inject PlaybackService reference for song loading and input suppression."""
        self._playback_service = playback_service

    def set_metronome(self, service):
        """Inject the standalone MetronomeService."""
        self.metronome = service
        if self.metronome:
            self.metronome.tick.connect(self._on_metronome_tick)
            self.metronome.beatPositionChanged.connect(self._on_metronome_beat_position)
            self.metronome.runningChanged.connect(self._on_metronome_running_changed)

    def _on_metronome_running_changed(self, running: bool):
        """
        Drops the scroll anchor when the metronome stops.

        stop() halts the beat clock, so no further position arrives. Without
        this the view would keep extrapolating along the last known tempo and
        scroll away on its own.
        """
        if not running:
            self._emit_scroll_anchor(self._scroll_beat, 0.0, active=False, snap=True)

    def _on_metronome_tick(self, beat_count):
        # Forward to QML (keeping existing signal for compatibility)
        self.metronomeTick.emit()
        
        # If we are in steady_pulse mode, check if we need to advance on the beat
        if self._exercise_type == "steady_pulse" and self._state == LessonState.USER_PLAYING:
            if beat_count >= 1: # Start counting hits once real beats begin
                self._check_steady_pulse_beat(beat_count)

    def _emit_scroll_anchor(self, beat: float, bps: float, active: bool,
                            snap: bool = False, force: bool = False):
        """
        Publishes a scroll anchor, rate-limited to 4 Hz for drift corrections.

        Callers on a 100 Hz clock can call this every tick; only genuine changes
        (`snap`/`force`) and the periodic correction get through. The view is
        extrapolating between anchors, so this is a correction channel, not a
        position feed.
        """
        now = time.monotonic()
        speed_changed = abs(bps - float(self._scroll_anchor.get("bps", 0.0))) > 1e-6
        state_changed = active != bool(self._scroll_anchor.get("active", False))
        if not (snap or force or speed_changed or state_changed
                or (now - self._last_anchor_time) >= 0.25):
            return

        self._last_anchor_time = now
        self._scroll_anchor = {
            "beat": float(beat),
            "bps": float(bps),
            "snap": bool(snap),
            "active": bool(active),
            "seq": int(self._scroll_anchor["seq"]) + 1,
        }
        self.scrollAnchorChanged.emit()

    def _set_stepped_scroll_beat(self, beat: float):
        """
        Moves the playhead a discrete step, as self-paced play does.

        Deactivates the scroll anchor so the view stops extrapolating and eases
        into the new position instead. Self-paced play is driven by the user's
        keypresses, not a clock — there is no rate to extrapolate along, and the
        150 ms ease between steps is the intended feel.
        """
        self._scroll_beat = float(beat)
        self.scrollBeatChanged.emit(self._scroll_beat)
        self._emit_scroll_anchor(self._scroll_beat, 0.0, active=False)

    def _on_metronome_beat_position(self, pos: float):
        self._scroll_beat = pos
        self.scrollBeatChanged.emit(pos)
        bpm = float(self.metronome.bpm) if self.metronome else 0.0
        self._emit_scroll_anchor(pos, bpm / 60.0, active=bpm > 0)

    def _on_song_finished(self):
        """Called 1.5 s after the last song note is played."""
        # Self-paced completion: a small fixed gain, docked per wrong note.
        # (Rhythm mode records from _on_rhythm_finished instead — it never
        # reaches _complete_chord, which is what schedules this callback.)
        if self._pacing_mode == "self_paced":
            mastery = max(1.0, 3.0 - float(self._song_wrong_notes))
            self._record_song_completion(
                mastery_gained=mastery,
                result={
                    "mode": "self_paced",
                    "wrongNotes": self._song_wrong_notes,
                    "masteryGained": mastery,
                },
            )

        if not self._is_lesson_mode:
            # Free-play song — just return to the home screen
            print(f"ChordTrainer: Song '{self._song_title}' complete (free-play). Returning to home.")
            self.stop_session()
            return

        # Lesson song — the coach acknowledges it while introducing what comes next.
        self._pending_coach_note = coach_prompts.note_song_finished(self._song_title or "the piece")
        self._next_chord()

    def _set_state(self, new_state: LessonState):
        if self._state == new_state:
            return

        old_active = self.isActive
        old_loading = self.isLoading

        self._state = new_state
        print(f"ChordTrainer: Transitioned to {new_state}")

        if old_active != self.isActive:
            self.activeChanged.emit(self.isActive)

        self.lessonStateChanged.emit()

        if old_loading != self.isLoading:
            self.loadingStatusChanged.emit()

    @Property(bool, notify=activeChanged)
    def isActive(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._state != LessonState.IDLE

    @Property(str, notify=targetChordChanged)
    def targetChord(self) -> str:  # type: ignore[reportRedeclaration]
        return self._target_chord_name

    @Property(list, notify=targetChordChanged)
    def targetPitches(self) -> list:  # type: ignore[reportRedeclaration]
        # ALWAYS return sorted for UI/Fingering consistency (except sequential drills)
        if self._exercise_type == "pentascale":
            return self._target_pitches
        return sorted(self._target_pitches)

    @Property(list, notify=targetChordChanged)
    def targetHands(self) -> list:  # type: ignore[reportRedeclaration]
        return self._target_hands

    @Property(list, notify=pentascaleNotesChanged)
    def pentascaleNotes(self) -> list:  # type: ignore[reportRedeclaration]
        # Full 5-note sequence for UI guides/scrolling
        return self._pentascale_sequence or []

    @Property(int, notify=currentNoteIndexChanged)
    def currentNoteIndex(self) -> int:  # type: ignore[reportRedeclaration]
        return self._pentascale_index

    @Property(list, notify=targetFingersChanged)
    def targetFingers(self) -> list:  # type: ignore[reportRedeclaration]
        return self._target_fingers

    @Property(float, notify=scrollBeatChanged)
    def scrollBeat(self) -> float:  # type: ignore[reportRedeclaration]
        return self._scroll_beat

    @Property("QVariantMap", notify=scrollAnchorChanged)
    def scrollAnchor(self) -> dict:  # type: ignore[reportRedeclaration]
        """
        Where the playhead is and how fast it moves, for ScrollClock.qml.

        Only the continuously clocked exercises publish an active anchor: the
        metronome-driven ones and rhythm mode. Self-paced play advances the
        playhead a step at a time on the user's own input, which is not a clock
        and must keep being eased through scrollBeat instead — see the
        steppedBeat branch in EnhancedSheetMusic.qml.
        """
        return self._scroll_anchor

    @Property(list, notify=scrollingNotesChanged)
    def scrollingNotes(self) -> list:  # type: ignore[reportRedeclaration]
        return self._scrolling_notes

    @Property(int, notify=scrollBpmChanged)
    def scrollBpm(self) -> int:  # type: ignore[reportRedeclaration]
        return self._scroll_bpm

    @Property(str, notify=songTitleChanged)
    def songTitle(self) -> str:  # type: ignore[reportRedeclaration]
        return self._song_title

    @Property(str, notify=songKeyChanged)
    def songKey(self) -> str:  # type: ignore[reportRedeclaration]
        return self._song_key

    @Property(int, notify=songKeySharpsChanged)
    def songKeySharps(self) -> int:  # type: ignore[reportRedeclaration]
        return self._song_key_sharps

    @Property(str, notify=songComposerChanged)
    def songComposer(self) -> str:  # type: ignore[reportRedeclaration]
        return self._song_composer

    @Property(bool, notify=songCompletedChanged)
    def isSongCompleted(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._song_completed

    # ── Phase 4: dual pacing ────────────────────────────────────────

    @Property(str, notify=pacingModeChanged)
    def pacingMode(self) -> str:  # type: ignore[reportRedeclaration]
        """"self_paced" (the default for every unplayed song) or "rhythm"."""
        return self._pacing_mode

    @Property(bool, notify=pacingModeChanged)
    def isRhythmMode(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._pacing_mode == "rhythm"

    @Property(str, notify=practiceHandsChanged)
    def practiceHands(self) -> str:  # type: ignore[reportRedeclaration]
        """Which hand the student is playing: "both", "right" or "left"."""
        return self._practice_hands

    @Property(list, notify=songNoteStatesChanged)
    def songNoteStates(self) -> list:  # type: ignore[reportRedeclaration]
        """
        Per-note feedback aligned index-for-index with `scrollingNotes`:
        "hit" / "miss" / "pending" for scored notes, "" for everything the
        engine does not score (barlines, rests, time signatures, dynamics,
        and notes filtered out by the practice-hand setting).

        Empty in self-paced mode, which is what keeps the renderer's per-note
        colouring off on the protected path.
        """
        return self._song_note_states

    @Property(dict, notify=songResultChanged)
    def songResult(self) -> dict:  # type: ignore[reportRedeclaration]
        """Summary of the last completed run, for the completion overlay."""
        return self._song_result

    @Property(str, notify=songTitleChanged)
    def songId(self) -> str:  # type: ignore[reportRedeclaration]
        return self._song_id

    @Property(str, notify=targetChordChanged)
    def pedalType(self) -> str:  # type: ignore[reportRedeclaration]
        return self._pedal_type

    @Property(str, notify=lessonStateChanged)
    def exerciseName(self) -> str:  # type: ignore[reportRedeclaration]
        return self._exercise_name

    @Property(bool, notify=lessonStateChanged)
    def isPausedForSpeech(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._state == LessonState.AI_SPEAKING

    @Property(int, notify=lessonStateChanged)
    def lessonProgress(self) -> int:  # type: ignore[reportRedeclaration]
        return self._lesson_progress

    @Property(int, notify=lessonStateChanged)
    def lessonTotal(self) -> int:  # type: ignore[reportRedeclaration]
        return self._lesson_total

    @Property("QVariantMap", notify=conceptCardChanged)
    def conceptCard(self) -> dict:  # type: ignore[reportRedeclaration]
        """{title, body} of the theory card on screen, or {} when there is none."""
        return dict(self._concept_card)

    @Property(list, notify=lessonStateChanged)
    def lessonBlocks(self) -> list:  # type: ignore[reportRedeclaration]
        return self._lesson_blocks

    @Property(bool, notify=lessonStateChanged)
    def isLessonComplete(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._is_lesson_complete

    @Property(bool, notify=lessonStateChanged)
    def isWaitingToBegin(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._state == LessonState.WAITING_TO_BEGIN

    @Property(str, notify=lessonStateChanged)
    def currentHand(self):  # type: ignore[reportRedeclaration]
        return self._current_hand

    @Property(bool, notify=lessonStateChanged)
    def isLessonMode(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._is_lesson_mode

    @Property(bool, notify=coachNeededChanged)
    def coachNeeded(self) -> bool:  # type: ignore[reportRedeclaration]
        """
        Whether the current mode wants a live coach session.

        False during free play, which is self-paced and never consults the
        coach. The UI reads this to keep coach-connection chrome off the screen
        while a piece is being played.
        """
        return self._coach_needed

    @Property(str, notify=lessonStateChanged)
    def exerciseType(self) -> str:  # type: ignore[reportRedeclaration]
        return self._exercise_type

    @Property(float, notify=loadingStatusChanged)
    def estimatedGenerationMs(self) -> float:  # type: ignore[reportRedeclaration]
        return self._estimated_gen_ms

    @Property(bool, notify=isCircleOfFifthsModeChanged)
    def isCircleOfFifthsMode(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._is_circle_of_fifths_mode

    @Property(bool, notify=waitingForUserContinueChanged)
    def isWaitingForUserContinue(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._circle.waiting_for_continue

    @Property(float, notify=lessonStateChanged)
    def holdProgress(self) -> float:  # type: ignore[reportRedeclaration]
        return self._hold_progress

    @Property(int, notify=lessonStateChanged)
    def requiredHoldMs(self) -> int:  # type: ignore[reportRedeclaration]
        return self._required_hold_ms

    @Property(bool, notify=lessonStateChanged)
    def isLoading(self) -> bool:  # type: ignore[reportRedeclaration]
        return self._state == LessonState.LOADING

    @Property(str, notify=loadingStatusChanged)
    def loadingStatusText(self) -> str:  # type: ignore[reportRedeclaration]
        return self._loading_status_text

    @Property(str, notify=targetChordChanged)
    def targetChordType(self) -> str:  # type: ignore[reportRedeclaration]
        return self._target_chord_type

    @Property(str, notify=targetChordChanged)
    def targetFormulaText(self) -> str:  # type: ignore[reportRedeclaration]
        return self._target_formula_text

    @Property(list, notify=lessonStateChanged)
    def struggledItems(self):  # type: ignore[reportRedeclaration]
        """List of items where user performance was below threshold."""
        return self._struggled_items


    @Property(int, notify=metronomeTick)
    def pentascaleBeatCount(self) -> int:  # type: ignore[reportRedeclaration]
        return self.metronome.beatCount if self.metronome else 0

    @Property(list, notify=lessonStateChanged)
    def progressionNumerals(self) -> list:  # type: ignore[reportRedeclaration]
        return self._progression_numerals

    @Property(int, notify=targetChordChanged)
    def currentProgressionIndex(self) -> int:  # type: ignore[reportRedeclaration]
        return self._progression_index

    @Property(str, notify=targetChordChanged)
    def scaleName(self) -> str:  # type: ignore[reportRedeclaration]
        return self._scale_name

    @Property(bool, notify=lessonStateChanged)
    def mistakeActive(self) -> bool:  # type: ignore[reportRedeclaration]
        """Determines if the student is currently holding any notes that are NOT in the target set."""
        if not self.isActive or self._is_lesson_complete or len(self._active_pitches) == 0:
            return False
            
        # For evaluation/song mode, we check exact MIDI pitches
        if self._exercise_type == "song_application":
            target_set = set(self._target_pitches)
            prev_set = set(self._prev_target_pitches)
            for p in self._active_pitches:
                # Correct if it's the current target OR the previous target (legato support)
                if p not in target_set and p not in prev_set:
                    return True
        elif self._exercise_type == "pentascale":
             # For pentascale, only the current pitch is 'correct'.
             # However, we allow holding the PREVIOUS pitch (legato) if it's the right one.
             if self._pentascale_sequence and self._pentascale_index < len(self._pentascale_sequence):
                 target_pitch = self._pentascale_sequence[self._pentascale_index]
                 # Correct if it's the target OR the previous note (to allow legato overlap)
                 prev_pitch = self._pentascale_sequence[self._pentascale_index - 1] if self._pentascale_index > 0 else -1
                 for p in self._active_pitches:
                     if p != target_pitch and p != prev_pitch:
                         return True
        else:
            # For general chords, we are octave-agnostic by default
            target_intervals = self._target_intervals
            for p in self._active_pitches:
                if (p % 12) not in target_intervals:
                    return True
        return False

    def _set_coach_needed(self, needed: bool):
        """
        Declares whether the current mode wants a live coach.

        Only announces changes: start_song runs on every replay of a piece, and
        re-releasing an already-released session would churn the websocket.
        """
        if self._coach_needed == needed:
            return
        self._coach_needed = needed
        self.coachNeededChanged.emit(needed)

    @Slot()
    def start_session(self):
        # Free Practice Mode. Unlike free play this is coach-driven — it asks
        # for a chord and reacts to what is played — so the session stays up.
        self._set_coach_needed(True)
        self._leave_scripted_lessons()
        self._is_lesson_mode = False
        self._exercise_name = "Free Practice"
        self._lesson_progress = 0
        self._lesson_total = 0
        self._is_lesson_complete = False
        self.lessonStateChanged.emit()

        if not self.isActive:
            self._set_state(LessonState.USER_PLAYING)
            self.activeChanged.emit(self.isActive)

        self._active_pitches.clear()
        self._next_chord()

    @Slot()
    @Slot(int)
    def start_lesson_plan(self, available_minutes: int = 10):
        """
        Starts a lesson from the curriculum's session plan.

        Every exercise is chosen locally by a LessonSequencer, so a lesson runs
        the same with or without a coach connection. When the coach is there it
        introduces new kinds of exercise and comments; it no longer decides
        what comes next.
        """
        self._set_coach_needed(True)

        session_plan = (self.curriculum.plan_session(available_minutes=available_minutes)
                        if self.curriculum else {"blocks": []})
        blocks = session_plan.get("blocks") or []
        student_context = self._student_context()

        first = blocks[0] if blocks else {}
        if first.get("track") == "theory" and first.get("milestone_id") == "circle_of_fifths":
            self._start_circle_tutorial(student_context)
            return

        hints = {b["milestone_id"]: self._milestone_meta(b["track"], b["milestone_id"]) for b in blocks}
        sequencer = LessonSequencer(session_plan, hints=hints, library=self._song_library(),
                                    dev_mode=self._dev_mode())
        self._begin_lesson(sequencer, student_context)

    # Exercises in a lesson on a single milestone.
    SINGLE_DRILL_EXERCISES = 12

    @Slot(str, str)
    def start_single_drill(self, track_name: str, milestone_id: str):
        """Starts a short lesson on one milestone."""
        self._set_coach_needed(True)

        if track_name == "theory" and milestone_id == "circle_of_fifths":
            self._start_circle_tutorial("")
            return
        if track_name == "theory" and milestone_id == "dominant_motion":
            self._start_dominant_motion()
            return

        meta = self._milestone_meta(track_name, milestone_id)
        block = {
            "track": track_name,
            "milestone_id": milestone_id,
            "milestone_title": meta.get("title", milestone_id),
            "milestone_description": meta.get("description", ""),
            "exercise_types": meta.get("exercise_types", ["chord"]),
            "target_keys": meta.get("target_keys", []),
            "target_chords": meta.get("target_chords", []),
            "step_count": self.SINGLE_DRILL_EXERCISES,
        }
        sequencer = LessonSequencer({"blocks": [block]}, hints={milestone_id: meta},
                                    library=self._song_library(), dev_mode=self._dev_mode())
        self._begin_lesson(sequencer, self._student_context())

    # ── Lesson plumbing ──────────────────────────────────────────────────

    @staticmethod
    def _dev_mode() -> bool:
        return os.environ.get("DEV_MODE", "false").lower() in ("true", "1", "yes")

    def _milestone_meta(self, track: str, milestone_id: str) -> dict:
        if not self.curriculum:
            return {}
        return dict(self.curriculum.get_milestone_meta(track, milestone_id) or {})

    def _song_library(self) -> list:
        """The student's imported songs, for repertoire blocks."""
        if not self.music21 or not hasattr(self.music21, "get_user_song_summaries"):
            return []
        try:
            return list(self.music21.get_user_song_summaries() or [])
        except Exception as e:
            print(f"ChordTrainer: Could not read the song library: {e}")
            return []

    def _student_context(self) -> str:
        """What the coach is told about the student when a lesson starts."""
        context = ""
        try:
            context = (self.curriculum.get_curriculum_context() if self.curriculum
                       else self.db.get_coach_context())
            terms = self.db.get_learned_term_names()
            if terms:
                context += f"\nAlready explained terms (do not explain these again): {', '.join(terms)}\n"
        except Exception as e:
            print(f"ChordTrainer: Could not build the student context: {e}")
        return context

    def _reset_for_lesson(self):
        """The state every kind of lesson starts from."""
        self._is_lesson_mode = True
        self._is_lesson_complete = False
        self._lesson_end_pending = False
        self._lesson_progress = 0
        self._lesson_total = 0
        self._lesson_blocks = []
        self._active_pitches.clear()
        self._session_stats.clear()
        self._struggled_items.clear()
        self._consecutive_successes = 0
        self._consecutive_struggles = 0
        self._ignore_midi_until = 0.0
        self._sequencer = None
        self._set_concept_card({})
        self._circle.reset()
        self._dominant.reset()

    def _begin_lesson(self, sequencer: LessonSequencer, student_context: str = ""):
        """Starts a sequenced lesson and presents its first exercise."""
        self._reset_for_lesson()
        self._sequencer = sequencer
        self._lesson_exercise_count = 0
        self._last_lesson_type = None
        try:
            self._seen_types_at_start = set(self.db.get_seen_exercise_intros() or [])
        except Exception:
            self._seen_types_at_start = set()
        self._lesson_student_context = student_context
        self._pending_coach_note = ""
        self._exercise_struggled = False
        self._struggle_tip_given = False

        self._set_state(LessonState.USER_PLAYING)
        self.lessonStateChanged.emit()
        self._advance_lesson()

    def _start_circle_tutorial(self, student_context: str = ""):
        """The scripted Circle of Fifths introduction (see circle_tutorial.py)."""
        self._circle.start()

    def _start_dominant_motion(self):
        """The scripted V→I resolution drill (see circle_tutorial.py)."""
        self._dominant.start()

    def _set_circle_mode(self, active: bool):
        """Whether a scripted lesson owns the Circle of Fifths view."""
        if active != self._is_circle_of_fifths_mode:
            self._is_circle_of_fifths_mode = active
            self.isCircleOfFifthsModeChanged.emit(active)

    def _leave_scripted_lessons(self):
        """
        Ends any scripted circle lesson. A half-finished V→I drill left active
        would capture the next lesson's chords as resolutions.
        """
        self._set_circle_mode(False)
        self._circle.reset()
        self._dominant.reset()

    def circle_tutorial_prompt(self) -> str:
        """Re-pushes the tutorial's current visual and returns its narration (after a reconnect)."""
        return self._circle.prompt()

    @Slot(bool)
    def set_coach_available(self, available: bool):
        """Whether prompts to the coach will be heard. Set from the live connection."""
        self._coach_available = bool(available)

    def _coach_say(self, prompt: Optional[str], wait: bool = True) -> bool:
        """
        Sends `prompt` to the coach. With `wait`, input pauses until the coach
        has finished (resume_lesson) or, if no audio starts within
        SPEECH_START_TIMEOUT_MS, until the timeout.

        Returns True if the lesson is now waiting for the coach. Without a
        coach nothing is sent and nothing waits — callers carry straight on.
        """
        if not prompt or not self._coach_available:
            return False
        self.speakInstruction.emit(prompt)
        if not wait or not self.isActive:
            return False
        if self._state != LessonState.AI_SPEAKING:
            self._set_state(LessonState.AI_SPEAKING)
        self._speech_start_timer.start()
        return True

    @Slot()
    def _on_speech_start_timeout(self):
        if self.isPausedForSpeech and not self._ai_is_currently_speaking:
            print("ChordTrainer: Coach did not start speaking in time; carrying on.")
            self.resume_lesson()

    def _set_concept_card(self, card: Dict[str, str]):
        if card != self._concept_card:
            self._concept_card = dict(card)
            self.conceptCardChanged.emit()

    @Slot(str)
    def start_song(self, piece_name: str):
        """Starts a free-play song exercise, skipping the AI coach."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: start_song('{piece_name}') invoked")
        
        # Avoid full stop_session() if possible to prevent False->True toggle on isActive
        # instead just reset the song-specific state
        if self.metronome:
            self.metronome.stop()

        # A song change fully resets the rhythm engine before anything reloads.
        self._rhythm_engine.stop()

        self._song_id = piece_name
        self._load_song_practice_prefs(piece_name)


        self._target_chord_name = ""
        self._target_intervals.clear()
        # Rebind rather than clear in place: in song mode _advance_song_chord
        # aliases the current step's own pitches/hands lists, so mutating these
        # would empty the loaded (and cached) song data itself.
        self._target_pitches = []
        self._target_hands = []
        self._pedal_type = ""
        self._is_holding = False
        self._consecutive_successes = 0
        # Free play is not a lesson: nothing sequenced, nothing waiting on the coach.
        self._sequencer = None
        self._lesson_end_pending = False
        self._speech_start_timer.stop()
        self._set_concept_card({})
        self._leave_scripted_lessons()

        self._is_lesson_mode = False
        self._is_lesson_complete = False
        self._set_state(LessonState.LOADING)

        # Free play never talks to the coach, so release it for the duration.
        # Announced before the song loads rather than after, so a socket that is
        # already dropping cannot get a reconnect overlay up over the music.
        self._set_coach_needed(False)

        self._active_pitches.clear()
        self._session_stats.clear()
        # A new song never inherits an input block from the last one. Only the
        # AI-lesson path clears this otherwise, so without it a free-play
        # replay could start with a dead keyboard.
        self._ignore_midi_until = 0.0

        self._apply_step({
            "exercise_type": "song_application",
            "piece_name": piece_name
        })
        
        self._set_state(LessonState.USER_PLAYING)
        print(f"ChordTrainer: start_song('{piece_name}') successfully initialized.")

    def present_exercise(self, exercise: dict) -> bool:
        """
        Puts an exercise in front of the student straight away, replacing any
        current one. `exercise` has the shape LessonSequencer yields.

        Returns False if it was rejected (an unknown chord type, an empty
        progression) or could not be set up (a song that would not load).
        """
        exercise_data = self._normalise_exercise(dict(exercise))
        if exercise_data is None:
            return False
        if not self.isActive:
            self._set_state(LessonState.USER_PLAYING)
        return self._apply_exercise(exercise_data)

    def _normalise_exercise(self, exercise_data: dict) -> Optional[dict]:
        """
        Fills defaults, resolves chord-type aliases and inversions, and rejects
        what the trainer cannot play. Returns None for a rejected exercise.
        """
        ex_type = exercise_data.get("exercise_type", "chord")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Exercise: {exercise_data.get('exercise_name', 'Unknown')} (type={ex_type})")

        # Apply defaults based on exercise type
        exercise_data.setdefault("hand", "right")
        exercise_data.setdefault("track", "technique")
        exercise_data.setdefault("milestone_id", "")
        exercise_data.setdefault("hold_ms", 0)
        exercise_data.setdefault("octave", 4)
        exercise_data.setdefault("exercise_name", "Exercise")

        # Validate chord type if applicable
        if ex_type in ("chord", "hands_together", "sustain_pedal", "listen") and "chord_type_name" in exercise_data:
            c_type = exercise_data["chord_type_name"]
            # Normalize shorthand aliases to canonical names
            if c_type in self.CHORD_TYPE_ALIASES:
                c_type = self.CHORD_TYPE_ALIASES[c_type]
                exercise_data["chord_type_name"] = c_type
                print(f"ChordTrainer: Normalized chord type alias to '{c_type}'")
            if c_type in ("N/A", "None", "", "Single"):
                exercise_data["intervals"] = [0]
                exercise_data["chord_type_name"] = "" # Normalize empty/NA to single notes
            elif c_type not in self.CHORD_TYPES:
                print(f"ChordTrainer: Unknown chord type '{c_type}', rejecting exercise")
                return None
            else:
                exercise_data["intervals"] = self.CHORD_TYPES[c_type]

        # Apply inversion if specified
        inversion = exercise_data.get("inversion", 0)
        if inversion and "intervals" in exercise_data and len(exercise_data["intervals"]) >= 3:
            intervals_list = sorted(list(exercise_data["intervals"]))
            for _ in range(inversion):
                # Rotate: move the lowest interval up by 12 (one octave)
                lowest = intervals_list.pop(0)
                intervals_list.append(lowest + 12)
            exercise_data["intervals"] = set(intervals_list)
            print(f"ChordTrainer: Applied inversion {inversion} → intervals={exercise_data['intervals']}")

        # Validate progression steps
        if ex_type == "progression":
            prog_steps = exercise_data.get("progression_steps", [])
            if not prog_steps:
                return None
            for ps in prog_steps:
                ct = ps.get("chord_type_name", "Major")
                if ct in self.CHORD_TYPE_ALIASES:
                    ct = self.CHORD_TYPE_ALIASES[ct]
                    ps["chord_type_name"] = ct
                if ct not in self.CHORD_TYPES:
                    print(f"ChordTrainer: Unknown chord type '{ct}' in progression, rejecting")
                    return None
        return exercise_data

    def _apply_exercise(self, exercise_data: dict) -> bool:
        """Apply a validated exercise: set up the target, then update progress and blocks."""
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Applying exercise to UI: {exercise_data.get('exercise_name', 'Unknown')}")
        # Clear song-complete state so the overlay dismisses
        if self._song_completed:
            self._song_completed = False
            self._ignore_midi_until = 0.0
            self.songCompletedChanged.emit()

        # Update current milestone context
        self._current_track = str(exercise_data.get("track", ""))
        self._current_milestone_id = str(exercise_data.get("milestone_id", ""))
        self._exercise_name = str(exercise_data.get("exercise_name", self._exercise_name))

        # Store current step data for performance tracking
        self._current_step_data = exercise_data.copy()

        self._apply_step(exercise_data)
        if exercise_data.get("exercise_type") == "song_application" and not self._song_steps:
            return False  # the piece did not load

        self.db.record_exercise_intro(exercise_data.get("exercise_type", "chord"))
        self._lesson_progress += 1
        self._lesson_total = self._lesson_progress  # Grows as exercises arrive
        self._update_lesson_blocks(exercise_data)
        self.lessonStateChanged.emit()
        return True

    # ── The lesson loop ──────────────────────────────────────────────────

    # Exercises tried in a row before a lesson gives up looking for one that
    # can be presented (songs can fail to load).
    MAX_PRESENT_ATTEMPTS = 10

    def _advance_lesson(self):
        """Presents the sequencer's next exercise, or ends the lesson."""
        if self._sequencer is None:
            self._conclude_lesson()
            return

        result = {"struggled": self._exercise_struggled}
        for _ in range(self.MAX_PRESENT_ATTEMPTS):
            exercise = self._sequencer.next_exercise(result)
            if exercise is None:
                break
            if self._present_lesson_exercise(exercise):
                return
            result = {"failed": True}

        note, self._pending_coach_note = self._pending_coach_note, ""
        self._conclude_lesson(coach_prompts.lesson_summary(
            self._lesson_exercise_count, self._sequencer.struggled, self._sequencer.block_titles, note))

    def _present_lesson_exercise(self, exercise: dict) -> bool:
        """Has the coach introduce `exercise` if it is worth a word, then presents it."""
        spec = self._sequencer.current_block_spec() if self._sequencer else {}
        prompt = coach_prompts.choose_intro(
            exercise,
            first_in_lesson=self._lesson_exercise_count == 0,
            previous_type=self._last_lesson_type,
            seen_types=self._seen_types_at_start,
            struggle_streak=self._consecutive_struggles,
            tip_given=self._struggle_tip_given,
            block_titles=self._sequencer.block_titles if self._sequencer else [],
            student_context=self._lesson_student_context,
            milestone_description=spec.get("milestone_description", ""),
            note=self._pending_coach_note,
        )
        waiting = self._coach_say(prompt)
        if prompt and self._consecutive_struggles >= 2:
            self._struggle_tip_given = True

        if not self.present_exercise(exercise):
            return False

        ex_type = exercise.get("exercise_type", "chord")
        self._pending_coach_note = ""
        self._lesson_exercise_count += 1
        self._last_lesson_type = ex_type
        self._seen_types_at_start.add(ex_type)
        self._exercise_struggled = False

        # Nobody is about to speak, so whatever setup deferred until the coach
        # finished (a listen preview, a metronome start) happens now.
        if not waiting and not self.isPausedForSpeech:
            self._resume_after_speech()
        return True

    def _conclude_lesson(self, prompt: Optional[str] = None):
        """Ends the lesson, after the coach's closing words if there are any."""
        if self._coach_say(prompt):
            self._lesson_end_pending = True
            return
        if self._ai_is_currently_speaking:
            # Let whatever is being said finish; resume_lesson finalizes.
            self._lesson_end_pending = True
            return
        self._finalize_lesson_end()

    def _finalize_lesson_end(self):
        """Actually marks the lesson as complete and updates UI state."""
        print("ChordTrainer: Finalizing lesson completion.")
        self._is_lesson_complete = True
        self._lesson_end_pending = False
        self._sequencer = None
        self._speech_start_timer.stop()
        self._ignore_midi_until = 0.0
        self._set_concept_card({})
        self._set_state(LessonState.IDLE)
        self.activeChanged.emit(False)

        self._set_circle_mode(False)

        if self.curriculum:
            self.curriculum.finish_session()

        self._target_chord_name = ""
        self._target_intervals.clear()
        # Rebind rather than clear in place: in song mode _advance_song_chord
        # aliases the current step's own pitches/hands lists, so mutating these
        # would empty the loaded (and cached) song data itself.
        self._target_pitches = []
        self._target_hands = []
        self._pedal_type = ""
        self._hold_tick_timer.stop()
        if self.metronome:
            self.metronome.stop()
        self.lessonStateChanged.emit()
        self.targetChordChanged.emit(self._target_chord_name)

    @Slot()
    def notify_visual_received(self):
        """Unlocks the loading state when a theory visual arrives."""
        if self.isLoading:
            print("ChordTrainer: Visual received during loading. Clearing loading lock.")
            self._set_state(LessonState.USER_PLAYING)

    def _update_lesson_blocks(self, exercise_data: dict):
        """Incrementally add to the lesson blocks sidebar as exercises arrive."""
        track = exercise_data.get("track", "")
        milestone_id = exercise_data.get("milestone_id", "")
        ex_type = exercise_data.get("exercise_type", "chord")

        group_title = ""
        if track == "review":
            group_title = "Review"
        elif self.curriculum and track and milestone_id:
            group_title = self.curriculum.get_milestone_title(track, milestone_id)

        if not group_title:
            group_title = f"{ex_type.capitalize()} Drills"

        if self._lesson_blocks and self._lesson_blocks[-1]["name"] == group_title:
            # Extend existing block
            self._lesson_blocks[-1]["stepCount"] += 1
            self._lesson_blocks[-1]["endStep"] = self._lesson_progress
        else:
            # New block
            self._lesson_blocks.append({
                "track": track,
                "name": group_title,
                "type": ex_type,
                "stepCount": 1,
                "startStep": self._lesson_progress,
                "endStep": self._lesson_progress,
            })

    @Slot()
    def continueConcept(self):
        """The student has read the theory card on screen and pressed Continue."""
        if not self._concept_card:
            return
        self._set_concept_card({})
        if self.curriculum:
            self.curriculum.complete_exercise(self._exercise_name, True,
                                              self._current_track, self._current_milestone_id)
        if self._is_lesson_mode:
            self._next_chord()

    # Due spaced-repetition items one Quick Review takes on; the rest wait.
    QUICK_REVIEW_LIMIT = 10

    @Slot()
    def start_review_session(self):
        """
        Quick Review: everything the SM-2 schedule says is due (most overdue
        first, up to QUICK_REVIEW_LIMIT), then the exercises the student
        struggled with earlier in this app session.
        """
        try:
            due = self.db.get_due_reviews(limit=self.QUICK_REVIEW_LIMIT)
        except Exception as e:
            print(f"ChordTrainer: Could not read due reviews: {e}")
            due = []
        exercises = review_exercises(due, self._song_library())

        for item in self._struggled_items:
            step = dict(item.get("chord_data") or {})
            if not step:
                continue
            step["exercise_name"] = f"Review: {step.get('exercise_name', item.get('name', 'Previous Task'))}"
            exercises.append(step)
        if not exercises:
            return

        print(f"ChordTrainer: Starting review session with {len(exercises)} items")
        self._set_coach_needed(True)
        self._begin_lesson(LessonSequencer.from_exercises(exercises), "")

    @Slot()
    def stop_session(self):
        """Stops the current exercise or lesson and returns the trainer to IDLE state."""
        # Unconditional, and outside the isActive guard: leaving free play must
        # restore the coach even when the trainer is already idle, or the next
        # lesson starts with no session.
        self._set_coach_needed(True)

        if self.isActive or self.isWaitingToBegin:
            print("ChordTrainer: stop_session called. Returning to IDLE.")
            self._set_state(LessonState.IDLE)
            self._is_lesson_complete = False
            self._sequencer = None
            self._lesson_end_pending = False
            self._speech_start_timer.stop()
            self._set_concept_card({})

            self._require_key_release_before_eval = False
            self._ignore_midi_until = 0.0
            if self.metronome:
                self.metronome.stop()

            # Leaving a session must fully reset rhythm state.
            self._rhythm_engine.stop()
            self._song_note_states = []
            self._rhythm_sn_index = []
            self.songNoteStatesChanged.emit()


            self._target_chord_name = ""
            self._target_intervals.clear()
            self._target_pitches = []
            self._target_hands = []
            self._pedal_type = ""
            self._song_title = ""
            self._song_composer = ""
            self._song_key = ""
            self._song_completed = False
            self.songTitleChanged.emit()
            self.songComposerChanged.emit()
            self.songKeyChanged.emit()
            self.songCompletedChanged.emit()
            self.targetChordChanged.emit(self._target_chord_name)
            self._hold_tick_timer.stop()
            self._is_holding = False
            self._consecutive_successes = 0

            self._leave_scripted_lessons()

            self.activeChanged.emit(False)
            self.lessonStateChanged.emit()

    @Slot()
    def end_lesson(self):
        """Manual lesson end triggered from UI (e.g. Quit Lesson button)."""
        print("ChordTrainer: end_lesson triggered manually from UI.")
        self._consecutive_struggles = 0
        self.stop_session()

    def _next_chord(self):
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: _next_chord called")
        if self._is_lesson_mode:
            self._target_chord_name = ""
            self._target_intervals.clear()
            self._target_pitches = []
            self._target_hands = []
            self._advance_lesson()
        else:
            self._apply_random_step()

    def _apply_step(self, chord_data):
        self._song_completed = False
        self.songCompletedChanged.emit()
        self._required_hold_ms = int(chord_data.get("hold_ms", 0)) # type: ignore
        exercise_type = str(chord_data.get("exercise_type", "chord")) # type: ignore
        self._exercise_type = exercise_type
        self._current_hand = str(chord_data.get("hand", "right")) # type: ignore
        if exercise_type != "theory_concept":
            self._set_concept_card({})

        # Pause input evaluation until speech finishes in lesson mode: either
        # the coach is talking already, or it has just been asked to introduce
        # this exercise and the lesson is waiting for it.
        if self._is_lesson_mode and (self._ai_is_currently_speaking or self.isPausedForSpeech):
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Coach speaking, pausing input (isPausedForSpeech=True) for {self._exercise_name}")
            self._set_state(LessonState.AI_SPEAKING)

            # If the user is currently holding keys, force them to release before evaluating this new step
            if len(self._active_pitches) > 0:
                print("ChordTrainer: Setting key release lock because keys are still held from previous step")
                self._require_key_release_before_eval = True

        # Track inversion for chord name labeling
        self._current_inversion = chord_data.get("inversion", 0)

        if exercise_type == "pentascale":
            self._setup_pentascale_target(chord_data)
        elif exercise_type == "progression":
            self._setup_progression_target(chord_data)
        elif exercise_type == "listen":
            self._setup_listen_target(chord_data)
        elif exercise_type == "hands_together":
            self._setup_hands_together_target(chord_data)
        elif exercise_type == "sustain_pedal":
            self._setup_sustain_target(chord_data)
        elif exercise_type == "steady_pulse":
            self._setup_steady_pulse_target(chord_data)
        elif exercise_type == "song_application":
            self._setup_song_target(chord_data)
        elif exercise_type == "theory_concept":
            self._setup_concept_card(chord_data)
        else:
            # Original chord behavior
            root_idx = chord_data.get("root_idx", 0)
            chord_type_name = chord_data.get("chord_type_name", "Major")
            if chord_type_name in ("N/A", "None", "Single", ""):
                intervals = chord_data.get("intervals", [0])
                chord_type_name = ""
            else:
                intervals = chord_data.get("intervals", self.CHORD_TYPES.get("Major", [0, 4, 7]))
            octave = chord_data.get("octave", 4)
            preview = chord_data.get("preview_chord", False)
            self._setup_target(root_idx, chord_type_name, intervals, octave, preview_chord=preview)

    def _setup_concept_card(self, chord_data):
        """A theory card: title and explanation on screen, Continue to move on. Nothing to play."""
        name = str(chord_data.get("exercise_name", ""))
        self._target_chord_name = name
        self._target_chord_type = "Concept"
        self._target_formula_text = ""
        self._target_intervals = set()
        self._target_pitches = []
        self._target_hands = []
        self._target_fingers = []
        self._scrolling_notes = []
        self.scrollingNotesChanged.emit()
        self.targetFingersChanged.emit()
        self._set_concept_card({"title": name, "body": str(chord_data.get("concept_body", ""))})
        self.targetChordChanged.emit(self._target_chord_name)

    def _apply_random_step(self):
        root_idx = random.randint(0, 11)
        # Filter out non-playable types for random practice
        playable = {k: v for k, v in self.CHORD_TYPES.items() if k != "Single"}
        chord_type_name, intervals = random.choice(list(playable.items()))
        octave = random.randint(4, 5)  # Right-hand range only
        self._required_hold_ms = 0
        self._exercise_type = "chord"
        self._current_hand = "right"
        self._setup_target(root_idx, chord_type_name, intervals, octave)

    def _setup_pentascale_target(self, chord_data):
        """Sets up a pentascale exercise: 5 sequential single-note targets."""
        root_idx = int(chord_data.get("root_idx", 0)) # type: ignore
        scale_type = str(chord_data.get("scale_type", "Major")) # type: ignore
        direction = str(chord_data.get("direction", "ascending")) # type: ignore
        octave = int(chord_data.get("octave", 4)) # type: ignore

        pattern = self.PENTASCALE_PATTERNS.get(scale_type, self.PENTASCALE_PATTERNS["Major"])
        # Clamp octave based on current hand assignment
        if self._current_hand == "right":
            octave = max(4, min(5, octave))
        elif self._current_hand == "left":
            octave = max(2, min(3, octave))
        base_pitch = (octave + 1) * 12 + root_idx

        # Generate the 5-note sequence as exact MIDI pitches
        sequence = [base_pitch + interval for interval in pattern]
        if direction == "descending":
            sequence = list(reversed(sequence))

        # Set target to the first note in the sequence
        self._scale_name = f"{self.ROOT_NOTES[root_idx % 12]} {scale_type}"
        self._target_chord_name = self._scale_name
        self._target_chord_type = "Pentascale"
        self._target_pitches = [sequence[0]]
        self._target_hands = [self._current_hand]
        
        # Calculate full fingering sequence for the 5-note pentascale
        full_fingers = self._calculate_fingerings(sequence if direction == "ascending" else list(reversed(sequence)), self._current_hand)
        if direction == "descending":
            full_fingers = list(reversed(full_fingers))
        self._pentascale_fingers = full_fingers
        self._target_fingers = full_fingers  # Show all 5 fingers at start
        self.targetFingersChanged.emit()
        self._hold_progress = 0.0
        self._is_holding = False
        self._waiting_for_release = False
        self._hold_tick_timer.stop()
        self._prompt_time = time.time()
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False

        # Handle metronome via service
        bpm = int(chord_data.get("bpm", 0))
        if bpm > 0 and self.metronome:
            if self._ai_is_currently_speaking or self.isPausedForSpeech:
                self.metronome.defer_start(bpm)
            else:
                self.metronome.start(bpm)
        elif self.metronome:
            self.metronome.stop()
            print("ChordTrainer: Free-play pentascale mode (no metronome)")

        # Set target to the first note in the sequence
        self._target_chord_name = self._scale_name
        self._target_chord_type = "Pentascale"

        # Display the note names in the correct ascending/descending order
        note_names = [self.ROOT_NOTES[(root_idx + i) % 12] for i in pattern]
        if direction == "descending":
            note_names = list(reversed(note_names))

        self._target_formula_text = f"{direction.capitalize()}: {' → '.join(note_names)}"
        self._target_pitches = sequence  # Show full sequence for QML visualization
        self._target_hands = [self._current_hand] * len(sequence)
        # For validation: match the exact MIDI pitch (not octave-agnostic)
        current_pitch = sequence[0]
        self._target_intervals = {current_pitch % 12}

        self._pentascale_sequence = sequence
        self._pentascale_index = 0
        
        # Build scrolling notes
        sn = []
        for i, p in enumerate(sequence):
            sn.append({
                "pitch": p,
                "start_beat": i,
                "duration_beats": 1,
                "finger": self._pentascale_fingers[i],
                "hand": "R" if self._current_hand == "right" else "L"
            })
        self._scrolling_notes = sn
        self.scrollingNotesChanged.emit()
        self._scroll_bpm = bpm
        self.scrollBpmChanged.emit()
        self._scroll_beat = 0.0 if bpm == 0 else (self.metronome.currentBeatPosition if self.metronome else 0.0)
        self.scrollBeatChanged.emit(self._scroll_beat)
        self._emit_scroll_anchor(self._scroll_beat, bpm / 60.0, active=bpm > 0, snap=True)
        
        self.lessonStateChanged.emit()
        self.targetChordChanged.emit(self._target_chord_name)
        self.pentascaleNotesChanged.emit()
        self.currentNoteIndexChanged.emit()
        print(f"ChordTrainer: Pentascale target: {self._scale_name} ({direction}), notes: {sequence}")

    def _setup_progression_target(self, chord_data):
        """Sets up a chord progression exercise: multiple chords played in sequence."""
        prog_steps = chord_data.get("progression_steps", []) # type: ignore
        print(f"[PROG DEBUG] _setup_progression_target called. prog_steps count={len(prog_steps)}")
        if not prog_steps:
            # Fallback: treat as a regular chord step
            print(f"[PROG DEBUG] No progression_steps! Falling back to chord. chord_data keys={list(chord_data.keys())}")
            self._exercise_type = "chord"
            root_idx = chord_data.get("root_idx", 0)
            chord_type_name = chord_data.get("chord_type_name", "Major")
            intervals = chord_data.get("intervals", self.CHORD_TYPES.get(chord_type_name, {0, 4, 7}))
            self._setup_target(root_idx, chord_type_name, intervals, 4)
            return

        # Store the full progression
        self._progression_steps = []
        self._progression_numerals = []
        for step in prog_steps:
            c_type = str(step.get("chord_type_name", "Major")) # type: ignore
            intervals = self.CHORD_TYPES.get(c_type, {0, 4, 7})
            self._progression_steps.append({
                "root_idx": int(step.get("root_idx", 0)), # type: ignore
                "chord_type_name": c_type,
                "intervals": intervals,
                "numeral": str(step.get("numeral", "")), # type: ignore
                "octave": int(step.get("octave", 4)), # type: ignore
            })
            self._progression_numerals.append(str(step.get("numeral", ""))) # type: ignore

        self._progression_index = 0
        self._required_hold_ms = 0
        self.lessonStateChanged.emit()

        # Build scrolling notes for the progression
        sn = []
        for i, step in enumerate(self._progression_steps):
            root_idx = step["root_idx"]
            intervals = step["intervals"]
            octave = step["octave"]
            
            c_hand = self._current_hand
            if c_hand == "right":
                oct_clamped = max(4, min(5, octave))
            elif c_hand == "left":
                oct_clamped = max(2, min(3, octave))
            else:
                oct_clamped = octave
                
            base_pitch = (oct_clamped + 1) * 12 + root_idx
            pitches = sorted([(base_pitch + inv) for inv in intervals])
            fingers = self._calculate_fingerings(pitches, "right" if c_hand != "left" else "left")
            if not fingers or len(fingers) != len(pitches):
                fingers = [j + 1 for j in range(len(pitches))]
            
            for j, p in enumerate(pitches):
                sn.append({
                    "pitch": p,
                    "hand": "R" if c_hand in ("right", "both") else "L",
                    "finger": fingers[j],
                    "start_beat": float(i),
                    "duration_beats": 1.0
                })

        self._scrolling_notes = sn
        self.scrollingNotesChanged.emit()
        self._set_stepped_scroll_beat(0.0)
        
        # User-driven pacing (no metronome by default for progressions)
        self._scroll_bpm = 0
        self.scrollBpmChanged.emit()
        
        print(f"[PROG DEBUG] Built {len(self._progression_steps)} progression steps, {len(sn)} scrolling notes")

        # Set up the first chord in the progression
        self._advance_progression_chord()

    def _setup_song_target(self, chord_data):
        """Sets up a Music21 song playback exercise."""
        piece_name = chord_data.get("piece_name", "bach/bwv1.6.mxl")

        # Songs can also arrive from the AI coach, which never goes through
        # start_song. Re-read the practice preferences whenever the piece
        # changes so a previous song's rhythm mode is never inherited.
        if piece_name != self._song_id:
            self._song_id = piece_name
            self._load_song_practice_prefs(piece_name)


        # Load from the new service
        assert self.music21 is not None, "Music21Service is not initialized!"
        song_data = self.music21.load_song_as_steps(piece_name)
        self._song_steps = song_data.get("steps", [])
        
        if not self._song_steps:
            print(f"ChordTrainer: Failed to load {piece_name}")
            self.statusMessageRequested.emit("error", f"Failed to load piece: {piece_name}")
            
            # Reset to IDLE so the user can try another song
            self._exercise_type = "chord"
            self._song_title = ""
            self._song_key = ""
            self._song_key_sharps = 0
            self.songTitleChanged.emit()
            self.songKeyChanged.emit()
            self.songKeySharpsChanged.emit()
            # In a lesson the sequencer moves on to another exercise; dropping
            # to IDLE would flash the dashboard between the two.
            if not self._is_lesson_mode:
                self._set_state(LessonState.IDLE)
            return
            
        self._exercise_type = "song_application"
        self._song_title = song_data.get("title", "Unknown Piece")
        self._song_key = song_data.get("key", "Unknown Key")
        self._song_key_sharps = song_data.get("key_sharps", 0)
        self._song_composer = song_data.get("composer", "Unknown Composer")
        self.songTitleChanged.emit()
        self.songKeyChanged.emit()
        self.songKeySharpsChanged.emit()
        self.songComposerChanged.emit()

        self._song_tempo_map = song_data.get("tempo_map", []) or []

        if self._playback_service:
            self._playback_service.load(
                steps=self._song_steps,
                tempo_map=self._song_tempo_map,
                time_signatures=song_data.get("time_signatures", []),
                pedal_events=song_data.get("pedal_events", [])
            )

        self._song_index = 0
        self._required_hold_ms = 0
        self.lessonStateChanged.emit()

        # Build scrolling notes for the whole song
        sn = []
        for step in self._song_steps:
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

        # Compute song end beat for barlines fallback
        if self._song_steps:
            last = max(self._song_steps, key=lambda s: float(s['offset']) + float(s['duration']))
            self._song_end_beat = float(last['offset']) + float(last['duration'])
        else:
            self._song_end_beat = 0.0

        # 5. Barlines
        barlines = song_data.get("barlines", [])
        if not barlines and time_sigs:
            from logic.utils.step_schema import compute_barlines
            barlines = compute_barlines(time_sigs, self._song_end_beat)
        self._song_barlines = sorted(float(b) for b in barlines)
        for b in barlines:
            sn.append({
                "is_barline": True,
                "start_beat": float(b),
                "duration_beats": 0.0
            })

        # Ensure purely deterministic timeline ordering
        sn.sort(key=lambda x: (x.get("start_beat", 0.0), not bool(x.get("is_time_sig", False)), not bool(x.get("is_dynamic", False)), not bool(x.get("is_barline", False)), x.get("pitch", 0)))

        self._scrolling_notes = sn
        self.scrollingNotesChanged.emit()

        # Compute the beat position at which all notation has finished
        if self._song_steps:
            last = max(self._song_steps, key=lambda s: float(s['offset']) + float(s['duration']))
            self._song_end_beat = float(last['offset']) + float(last['duration'])
        else:
            self._song_end_beat = 0.0

        self._song_completed = False
        self.songCompletedChanged.emit()

        self._set_stepped_scroll_beat(0.0)

        # User-driven pacing (no metronome)
        self._scroll_bpm = 0
        self.scrollBpmChanged.emit()

        # Target chord name gives context
        self._target_chord_name = f"Song: {self._song_title}"
        self.targetChordChanged.emit(self._target_chord_name)

        # ── Phase 4: pacing fork ────────────────────────────────────
        # Everything above this point is shared by both modes. Below, the two
        # paths are mutually exclusive: rhythm mode starts the engine and never
        # touches _advance_song_chord / _check_chord, and self-paced mode runs
        # exactly as it always has with an empty songNoteStates array.
        self._song_wrong_notes = 0
        self._song_result = {}
        self.songResultChanged.emit()

        # Steps the student is responsible for playing, after the hand filter.
        # PlaybackService keeps the unfiltered list it was handed above, so the
        # app can still play the other hand for a duet.
        self._song_steps = self._filter_steps_for_practice_hands(self._song_steps)

        # The filter can empty the list outright — a hand that never plays, or a
        # section that is all rests. Say so instead of leaving the student in
        # front of a sheet that will never accept a note.
        if not self._song_steps:
            print(f"ChordTrainer: '{self._song_title}' has nothing to play for hands='{self._practice_hands}'")
            self.statusMessageRequested.emit(
                "info", "Nothing to play here — try the other hand or 'both'.")
            return

        if self._pacing_mode == "rhythm":
            self._start_rhythm_run()
        else:
            self._song_note_states = []
            self._rhythm_sn_index = []
            self.songNoteStatesChanged.emit()
            # Set up the first step
            self._advance_song_chord()

    # ══════════════════════════════════════════════════════════════════
    # Phase 4 — Dual pacing: self-paced (default) ⟷ rhythm
    # ══════════════════════════════════════════════════════════════════

    # ── Preference persistence ──────────────────────────────────────

    def _is_user_song(self, song_id: str) -> bool:
        return bool(song_id) and song_id.startswith("user::")

    def _load_song_practice_prefs(self, song_id: str):
        """
        Restores this song's pacing mode and practice hands.

        A song with no stored preference — i.e. one that has never been played —
        always comes back as self-paced. That is a product guarantee, not a
        fallback: rhythm mode is opt-in, per song, forever.
        """
        mode, hands = "self_paced", "both"
        try:
            if self._is_user_song(song_id) and self.music21:
                mode = self.music21.get_user_song_pref(song_id, "practice_mode", "self_paced")
                hands = self.music21.get_user_song_pref(song_id, "practice_hands", "both")
            elif song_id and self.db:
                mode = self.db.get_app_setting(f"practice_mode::{song_id}", "self_paced")
                hands = self.db.get_app_setting(f"practice_hands::{song_id}", "both")
        except Exception as e:
            print(f"ChordTrainer: Could not read practice prefs for '{song_id}': {e}")

        self._pacing_mode = mode if mode in ("self_paced", "rhythm") else "self_paced"
        self._practice_hands = hands if hands in ("both", "right", "left") else "both"
        self.pacingModeChanged.emit()
        self.practiceHandsChanged.emit()
        print(f"ChordTrainer: '{song_id}' practice mode='{self._pacing_mode}', hands='{self._practice_hands}'")

    def _save_song_practice_pref(self, key: str, value: str):
        if not self._song_id:
            return
        try:
            if self._is_user_song(self._song_id) and self.music21:
                self.music21.set_user_song_pref(self._song_id, key, value)
            elif self.db:
                self.db.set_app_setting(f"{key}::{self._song_id}", value)
        except Exception as e:
            print(f"ChordTrainer: Could not save practice pref '{key}': {e}")

    # ── Hand filtering ──────────────────────────────────────────────

    # Per-pitch parallel arrays carried on every v2 step; all must be sliced
    # together so indices stay aligned after a hand filter.
    _PER_PITCH_STEP_KEYS = ("pitches", "hands", "fingers", "spellings", "ties",
                            "beams", "durations", "tuplets", "velocities")

    def _filter_steps_for_practice_hands(self, steps):
        """
        Narrows each step to the hand the student is practising and drops every
        step that leaves the student nothing to play.

        Steps go empty two ways. A step whose notes all belong to the other hand
        is how "LH-only steps are auto-skipped" falls out for free. A step that
        never had pitches at all is a rest-only offset: both song loaders emit
        one wherever a rest starts with no note sounding under it, and the
        self-paced advance would otherwise park on it forever waiting for a
        chord the keyboard cannot produce.

        Dropping both here rather than in _advance_song_chord keeps _song_index
        arithmetic — including end-of-song detection — over a list in which
        every entry is playable. PlaybackService and _song_end_beat are
        computed upstream from the unfiltered steps, so the accompaniment and
        the notation still show the silence.
        """
        want = self._practice_hands if self._practice_hands in ("right", "left") else None

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
            for key in self._PER_PITCH_STEP_KEYS:
                vals = step.get(key)
                if isinstance(vals, list) and len(vals) == len(pitches):
                    new_step[key] = [vals[i] for i in keep]
            out.append(new_step)
        return out

    # ── Rhythm mode ─────────────────────────────────────────────────

    def _build_rhythm_notes(self, scrolling_notes):
        """
        Builds the engine's note list from the already-sorted `scrolling_notes`
        array, one entry per pitch, and records the index map back into it.

        Deriving both from the same sorted array is what keeps `songNoteStates`
        aligned index-for-index with `scrollingNotes`; Phase 2's `orig_i` then
        carries those indices correctly through the renderer's culling.
        """
        notes = []
        sn_index = []
        want = self._practice_hands
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

        self._rhythm_sn_index = sn_index
        # Pseudo-items (barlines, rests, time sigs, dynamics) and unscored notes
        # keep "", which the renderer treats as a no-op.
        self._song_note_states = [""] * len(scrolling_notes)
        for idx in sn_index:
            self._song_note_states[idx] = "pending"
        self.songNoteStatesChanged.emit()

        return notes

    def _rhythm_tempo(self) -> float:
        """The piece's starting tempo, scaled by the user's playback tempo slider."""
        from logic.services.playback_service import bpm_at
        bpm = bpm_at(self._song_tempo_map, 0.0)
        if self._playback_service:
            bpm *= float(self._playback_service.tempoScale)
        return max(20.0, bpm)

    def _start_rhythm_run(self):
        """Loads the engine with the current song and starts the 4-beat count-in."""
        notes = self._build_rhythm_notes(self._scrolling_notes)

        self._rhythm_engine.load(notes, self._rhythm_tempo(), count_in_beats=4)

        # Respect an A/B loop if one is set: the run scores only that region and
        # the mastery award is halved because it is not a full-piece play.
        self._rhythm_loop_only = False
        if self._playback_service:
            a = float(self._playback_service.loopStartBeat)
            b = float(self._playback_service.loopEndBeat)
            if b > a >= 0:
                self._rhythm_engine.set_loop(a, b)
                self._rhythm_loop_only = True
            else:
                self._rhythm_engine.clear_loop()
        else:
            self._rhythm_engine.clear_loop()

        self._scroll_beat = self._rhythm_engine.currentBeat
        self.scrollBeatChanged.emit(self._scroll_beat)
        # snap: the run begins at the count-in, which is a jump from wherever
        # the playhead was parked.
        self._emit_scroll_anchor(
            self._scroll_beat, self._rhythm_tempo() / 60.0, active=True, snap=True
        )

        self._rhythm_engine.start()
        print(f"ChordTrainer: Rhythm run started — {len(notes)} notes at "
              f"{self._rhythm_tempo():.0f} BPM, loop_only={self._rhythm_loop_only}")

    def _on_rhythm_beat(self, beat: float):
        self._scroll_beat = beat
        self.scrollBeatChanged.emit(beat)
        self._emit_scroll_anchor(beat, self._rhythm_tempo() / 60.0, active=True)

    def _on_rhythm_note_state(self, index: int, state: str):
        if 0 <= index < len(self._rhythm_sn_index):
            sn_i = self._rhythm_sn_index[index]
            if 0 <= sn_i < len(self._song_note_states):
                self._song_note_states[sn_i] = state
                self.songNoteStatesChanged.emit()

    def _on_rhythm_metronome_tick(self, beat_num: int, accent: bool):
        # Routed straight to the hardware click by AppCoordinator. The generic
        # `metronomeTick` signal is deliberately not reused: its handler derives
        # a beat number from pentascale state that means nothing here.
        self.rhythmCountInTick.emit(beat_num, accent)

    def _on_rhythm_finished(self, accuracy: float, hits: int, misses: int):
        """Scores the run, banks mastery and raises the completion overlay."""
        # The clock has stopped, so stop the view extrapolating along it —
        # otherwise the notation keeps scrolling past the end of the run.
        self._emit_scroll_anchor(self._scroll_beat, 0.0, active=False, snap=True)

        mastery = (accuracy ** 2) * 10.0
        if self._rhythm_loop_only:
            mastery /= 2.0

        self._record_song_completion(
            mastery_gained=mastery,
            result={
                "mode": "rhythm",
                "accuracy": accuracy,
                "hits": hits,
                "misses": misses,
                "loopOnly": self._rhythm_loop_only,
                "masteryGained": mastery,
            },
        )

        self._song_completed = True
        self.songCompletedChanged.emit()
        print(f"ChordTrainer: Rhythm run finished — {hits} hits / {misses} misses "
              f"({accuracy*100:.0f}%), mastery +{mastery:.2f}")

        # In a lesson the coach still gets its completion report. In free play
        # the scorecard stays up until the student dismisses it — auto-returning
        # would snatch away the "practice trouble spots" action.
        if self._is_lesson_mode:
            self._ignore_midi_until = time.time() + 99.0
            QTimer.singleShot(1500, self._on_song_finished)

    def _record_song_completion(self, mastery_gained: float, result: dict):
        """Writes the play to the songs table and publishes the overlay summary."""
        result = dict(result)
        result["title"] = self._song_title
        result["songId"] = self._song_id
        self._song_result = result
        self.songResultChanged.emit()

        if not self._song_id:
            return
        try:
            self.db.record_song_play(
                filepath=self._song_id,
                title=self._song_title or self._song_id,
                mastery_gained=float(mastery_gained),
            )
            print(f"ChordTrainer: Recorded play of '{self._song_id}' (+{mastery_gained:.2f} mastery)")
        except Exception as e:
            print(f"ChordTrainer: Failed to record song play: {e}")

        # A loop-only run never plays the whole piece, so it is not a review of it.
        if not result.get("loopOnly"):
            quality = quality_for_song(str(result.get("mode", "self_paced")),
                                       int(result.get("wrongNotes", 0) or 0),
                                       float(result.get("accuracy", 0.0) or 0.0))
            try:
                self.db.record_review("song", self._review_song_id(self._song_id), quality)
            except Exception as e:
                print(f"ChordTrainer: Could not record review of '{self._song_id}': {e}")

    @staticmethod
    def _review_song_id(song_id: str) -> str:
        """The song a play counts for: difficulty variants (`<id>::L2`) review the song itself."""
        return re.sub(r"::L\d+$", "", song_id)

    # ── QML control surface ─────────────────────────────────────────

    @Slot(str)
    def set_pacing_mode(self, mode: str):
        """Switches between self-paced and rhythm practice for the current song."""
        if mode not in ("self_paced", "rhythm") or mode == self._pacing_mode:
            return

        self._pacing_mode = mode
        self.pacingModeChanged.emit()
        self._save_song_practice_pref("practice_mode", mode)
        self._restart_song_section()

    @Slot(str)
    def set_practice_hands(self, mode: str):
        """Selects which hand the student plays ("both", "right", "left")."""
        if mode not in ("both", "right", "left") or mode == self._practice_hands:
            return

        self._practice_hands = mode
        self.practiceHandsChanged.emit()
        self._save_song_practice_pref("practice_hands", mode)
        self._restart_song_section()

    def _restart_song_section(self):
        """
        Restarts the current piece under the new settings. Reloading through
        start_song is deliberate: it re-reads the preferences we just saved and
        resets every piece of derived state (engine, note states, index map,
        step list, wrong-note count) in one place.
        """
        self._rhythm_engine.stop()
        self._active_pitches.clear()

        if self._exercise_type == "song_application" and self._song_id:
            self.start_song(self._song_id)

    @Slot()
    def restart_song(self):
        """Replays the current piece from the top, keeping mode and hand settings."""
        self._restart_song_section()

    @Slot()
    def stop_rhythm_run(self):
        """Ends a rhythm run early — the only way a loop-only run ever finishes."""
        if self._rhythm_engine.isRunning:
            self._rhythm_engine.finish_now()

    @Slot()
    def toggle_rhythm_pause(self):
        self._rhythm_engine.toggle_pause()

    @Slot(result=int)
    def practice_trouble_spots(self) -> int:
        """
        Clusters this run's misses by measure and loops the worst one.

        Returns the 1-based measure number, or 0 if there is nothing to drill.
        """
        if not self._playback_service:
            return 0

        bounds = self._measure_bounds()
        if len(bounds) < 2:
            return 0

        # Tally misses per measure from the states array.
        misses = [0] * (len(bounds) - 1)
        for sn_i in self._rhythm_sn_index:
            if sn_i >= len(self._song_note_states):
                continue
            if self._song_note_states[sn_i] != "miss":
                continue
            beat = float(self._scrolling_notes[sn_i].get("start_beat", 0.0))
            m = self._measure_index_for_beat(bounds, beat)
            if 0 <= m < len(misses):
                misses[m] += 1

        worst = max(range(len(misses)), key=lambda m: misses[m]) if misses else -1
        if worst < 0 or misses[worst] == 0:
            return 0

        self._playback_service.setLoop(bounds[worst], bounds[worst + 1])
        print(f"ChordTrainer: Trouble spot = measure {worst + 1} "
              f"({misses[worst]} misses), loop {bounds[worst]}–{bounds[worst + 1]}")
        return worst + 1

    def _measure_bounds(self) -> List[float]:
        """Measure boundaries in beats: [0, bar1, bar2, …, song_end]."""
        bounds = [0.0]
        for b in self._song_barlines:
            if b > bounds[-1] + 1e-6:
                bounds.append(float(b))
        if self._song_end_beat > bounds[-1] + 1e-6:
            bounds.append(float(self._song_end_beat))
        return bounds

    @staticmethod
    def _measure_index_for_beat(bounds: List[float], beat: float) -> int:
        for m in range(len(bounds) - 1):
            if bounds[m] <= beat < bounds[m + 1]:
                return m
        return len(bounds) - 2

    def _setup_listen_target(self, chord_data):
        """Sets up an ear training exercise: plays a chord, user identifies it."""
        root_idx = int(chord_data.get("root_idx", 0))

        target_quality = str(chord_data.get("target_quality", "")).strip()
        chord_type_name = str(chord_data.get("chord_type_name", "")).strip()

        # Reconcile missing parameters if the AI was sloppy
        if target_quality and not chord_type_name:
            chord_type_name = target_quality
        elif chord_type_name and not target_quality:
            target_quality = chord_type_name
        elif not target_quality and not chord_type_name:
            chord_type_name = "Major"
            target_quality = "Major"

        # Ensure proper casing since dictionary CHORD_TYPES expects Title Case (e.g. 'minor' -> 'Minor')
        if chord_type_name:
            chord_type_name = chord_type_name[0].upper() + chord_type_name[1:]
        if target_quality:
            target_quality = target_quality[0].upper() + target_quality[1:]

        intervals = self.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))

        # Standard chord setup but marked as listen
        self._setup_target(root_idx, chord_type_name, intervals, octave, preview_chord=True)
        self._target_chord_name = "Listen to the chord"
        self._target_chord_type = "Listen" # UI uses this to show quiz instead of notation
        self._target_formula_text = target_quality # Hidden till answered

        self.targetChordChanged.emit(self._target_chord_name)

        print(f"ChordTrainer: Listen target: {root_idx} {chord_type_name}, quality={target_quality}")

    def _setup_hands_together_target(self, chord_data):
        """Sets up a hands together exercise: right hand chord + left hand bass note."""
        root_idx = int(chord_data.get("root_idx", 0))
        chord_type_name = str(chord_data.get("chord_type_name", "Major"))
        intervals = self.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))

        self._current_hand = "both"
        self._setup_target(root_idx, chord_type_name, intervals, octave, suppress_signal=True)

        # Override formula and type for hands together UI differences
        self._target_chord_type = "Hands Together"
        self._target_formula_text = "Bass + Chord"

        # Inject bass note for UI rendering
        lh_octave = max(2, min(3, octave - 1))
        lh_base_pitch = (lh_octave + 1) * 12 + root_idx
        self._target_pitches.insert(0, lh_base_pitch)
        self._target_hands.insert(0, "left")
        
        # Add LH finger (usually thumb/1 but calculation will handle it)
        lh_fingers = self._calculate_fingerings([lh_base_pitch], "left")
        if lh_fingers:
            self._target_fingers.insert(0, lh_fingers[0])
            self.targetFingersChanged.emit()

        self.targetChordChanged.emit(self._target_chord_name)

    def _setup_sustain_target(self, chord_data):
        """Sets up a sustain pedal exercise."""
        root_idx = int(chord_data.get("root_idx", 0))
        chord_type_name = str(chord_data.get("chord_type_name", "Major"))
        if chord_type_name in ("N/A", "None", "Single", ""):
            intervals = chord_data.get("intervals", [0])
            chord_type_name = ""
        else:
            intervals = self.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))

        self._pedal_type = str(chord_data.get("pedal_type", "direct"))
        self._pedal_satisfied = False

        self._setup_target(root_idx, chord_type_name, intervals, octave, suppress_signal=True)
        self._target_chord_type = "Sustain Pedal"
        # We don't need UI text for pedal type since standard notation will be used,
        # but keep it in formula text for debugging or fallback if desired.
        self._target_formula_text = f"Pedal: {self._pedal_type.capitalize()}"

        # Override the target name if it was blanked out by the fallback to single note
        if not chord_type_name:
            root_name = self.ROOT_NOTES[root_idx]
            self._target_chord_name = f"{root_name} Note ({self._pedal_type.capitalize()} Pedal)"

        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged for Sustain ({self._target_chord_name})")
        self.targetChordChanged.emit(self._target_chord_name)

    @Slot(bool)
    def handle_pedal_event(self, is_down: bool):
        """Called by AppState when a CC64 sustain pedal event occurs."""
        self._is_pedal_down = is_down
        if is_down:
            self._pedal_down_time = time.time() * 1000.0

        if not self.isActive or self._is_lesson_complete:
            return

        if self._exercise_type == "sustain_pedal" and not self._pedal_satisfied:
            if self._pedal_type == "direct":
                # Pedal should be pressed around the same time as the chord
                if is_down and self._is_holding:
                    pedal_timing = self._pedal_down_time - self._hold_start_time
                    if pedal_timing <= 400: # generous 400ms window
                        self._pedal_satisfied = True
                        self._check_input()
                    else:
                        self.speakInstruction.emit("Try to press the pedal *exactly* when you strike the keys for a 'direct' pedal technique.")
            elif self._pedal_type == "legato":
                # Pedal should be pressed after the chord starts
                if is_down and self._is_holding:
                    self._pedal_satisfied = True
                    self._check_input()

    def _play_midi_preview(self, pitches):
        """Emits MIDI out request and ignores incoming MIDI to prevent loopback auto-completion."""
        # play_chord_preview lasts 1.5s, so we ignore input for 1.6s
        self._ignore_midi_until = time.time() + 1.6
        self.midiOutRequested.emit(pitches)

    @Slot()
    def replay_preview(self):
        """Re-sends the MIDI preview for the current target chord."""
        if self._target_pitches:
            print(f"ChordTrainer: Replaying MIDI preview for {self._target_pitches}")
            self._play_midi_preview(self._target_pitches)

    @Slot(str)
    def handle_ear_training_answer(self, quality: str):
        """Validates a user's ear training selection."""
        if self._exercise_type != "listen" or self.isPausedForSpeech:
            return

        is_correct = (quality.lower() == self._target_formula_text.lower())
        if is_correct:
            print(f"ChordTrainer: Ear Training CORRECT! {quality}")
            self._complete_chord()
        else:
            print(f"ChordTrainer: Ear Training WRONG. User picked {quality}, expected {self._target_formula_text}")
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting chordFailed (wrong answer)")
            self._exercise_struggled = True
            self.chordFailed.emit()
            # Optionally replay the sound as feedback
            self.replay_preview()

    def _calculate_fingerings(self, pitches: List[int], hand: str, inversion: int = 0, base_pitch: Optional[int] = None) -> List[int]:
        """Use music21 to represent the chord/note and assign pedagogical fingerings."""
        if not pitches:
            return []
            
        # ALWAYS sort pitches low-to-high before analysis!
        pitches = sorted(list(pitches))
        
        # Create a music21 Chord or Note
        if len(pitches) > 1:
            m21_obj = music21.chord.Chord(pitches)
        else:
            m21_obj = music21.note.Note(pitches[0])
            
        assigned_fingers = []
        
        # Standard piano pedagogical fingerings
        if len(pitches) == 3:
            # Triads
            if hand == "right":
                if inversion == 1: # 1st inversion (e.g. E-G-C)
                    assigned_fingers = [1, 2, 5]
                else: # Root or 2nd inversion (1-3-5)
                    assigned_fingers = [1, 3, 5]
            else: # left
                if inversion == 2: # 2nd inversion (e.g. G-C-E)
                    assigned_fingers = [5, 2, 1]
                else: # Root or 1st inversion (5-3-1)
                    assigned_fingers = [5, 3, 1]
        elif len(pitches) == 1:
            # Single notes: Use Adaptive Diatonic mapping
            is_right = (hand == "right")
            p = pitches[0]
            
            # If no base_pitch provided, default to Middle C or an octave below
            if base_pitch is None:
                base_pitch = 60 if is_right else 48
            
            # Simple diatonic mapping based on semitone offsets
            # This handles both black and white keys by mapping chromatic neighbors to the same finger
            offset = p - base_pitch
            
            if is_right:
                # RH: Base(0)=1, Base+2(2)=2, Base+4(4)=3, Base+5(5)=4, Base+7(7)=5
                mapping = {
                    -2: 1, -1: 1, 0: 1, 
                    1: 1, 2: 2, 3: 2, 
                    4: 3, 5: 4, 6: 4, 
                    7: 5, 8: 5
                }
                # Default case: if outside the 5-finger span, clamp to 1 or 5
                f = mapping.get(offset, 1 if offset < 0 else 5)
            else:
                # LH: Base(0)=1, Base-2(-2)=2, Base-3(-4)=3, Base-5(-5)=4, Base-7(-7)=5
                # Offset mapping for LH (relative to pinky usually, but here base is often the 'top' or 'thumb' note)
                # Actually, in EvaluationService, LH Base 48 (C3) -> finger 1. Offset 0=1, Offset -1=2...
                mapping = {
                    0: 1, 1: 1,
                    -1: 2, -2: 2,
                    -3: 3, -4: 3,
                    -5: 4, -6: 4,
                    -7: 5, -8: 5
                }
                f = mapping.get(offset, 1 if offset > 0 else 5)
            assigned_fingers = [int(f)]
        elif len(pitches) == 5:
            # Pentascales
            if hand == "right":
                assigned_fingers = [1, 2, 3, 4, 5]
            else:
                assigned_fingers = [5, 4, 3, 2, 1]
        else:
            # Fallback for complex chords (sequential from thumb/pinky)
            if hand == "right":
                assigned_fingers = [(i % 5) + 1 for i in range(len(pitches))]
            else:
                assigned_fingers = [max(1, 5 - (i % 5)) for i in range(len(pitches))]

        return assigned_fingers

    def _setup_target(self, root_idx, chord_type_name, intervals, octave, preview_chord=False, suppress_signal=False):
        self._hold_progress = 0.0
        self._is_holding = False
        self._waiting_for_release = False
        self._hold_tick_timer.stop()
        self.lessonStateChanged.emit()

        root_name = self.ROOT_NOTES[root_idx]
        # Clamp octave based on current hand assignment
        if self._current_hand == "right":
            octave = max(4, min(5, octave))
        elif self._current_hand == "left":
            octave = max(2, min(3, octave))
        base_pitch = (octave + 1) * 12 + root_idx

        self._target_chord_name = f"{root_name} {chord_type_name}".strip()
        self._review_chord = f"{root_name} {chord_type_name}" if chord_type_name else ""
        # Add inversion label if applicable
        inversion = self._current_inversion
        if inversion == 1:
            self._target_chord_name += " (1st inv)"
        elif inversion == 2:
            self._target_chord_name += " (2nd inv)"
        self._target_chord_type = chord_type_name

        # Calculate the text formula (e.g. "Root + 4 + 3")
        if len(intervals) <= 1:
             self._target_formula_text = "" # Single notes or empty have no formula
        else:
             sorted_intervals = sorted(list(intervals))
             steps = []
             for i in range(1, len(sorted_intervals)):
                 # Calculate half-steps between previous interval and current
                 diff = sorted_intervals[i] - sorted_intervals[i-1]
                 steps.append(str(diff))
             self._target_formula_text = "Root + " + " + ".join(steps)

        # Calculate the exact MIDI pitches (ALWAYS sorted for chord consistency)
        self._target_pitches = sorted([(base_pitch + interval) for interval in intervals])

        # Populate target hands: left if the exercise specifically calls for it,
        # otherwise default to right hand for normal chords (or the fallback).
        hand_tag = "left" if self._current_hand == "left" else "right"
        self._target_hands = [hand_tag] * len(self._target_pitches)

        # Calculate fingerings using music21 logic
        self._target_fingers = self._calculate_fingerings(self._target_pitches, hand_tag, inversion)
        self.targetFingersChanged.emit()

        # Calculate the absolute intervals (0-11) for the logic evaluator
        self._target_intervals = {(root_idx + interval) % 12 for interval in intervals}

        self._prompt_time = time.time()
        # Reset performance counters for the new target
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False

        if not suppress_signal:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._target_chord_name})")
            self.targetChordChanged.emit(self._target_chord_name)

        print(f"ChordTrainer: Next target is {self._target_chord_name} (intervals: {self._target_intervals}, pitches: {self._target_pitches}, hold={self._required_hold_ms}ms)")

        # If preview requested, emit signal for MIDI output
        # Defer if the AI is still speaking (coach intro) to avoid audio collision
        if preview_chord:
            if self._is_lesson_mode:
                print(f"ChordTrainer: Deferring MIDI preview until coach finishes speaking")
                self._listen_preview_pending = True
            else:
                print(f"ChordTrainer: Requesting MIDI preview for pitches: {self._target_pitches}")
                self._play_midi_preview(self._target_pitches)

        if not self.isPausedForSpeech:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting inputReady")
            self.inputReady.emit()
            # Evaluate immediately in case keys are already appropriately held
            self._check_input()

    @Slot()
    def pause_for_speech(self):
        """Called immediately when AI audio playback starts to instantly blur UI."""
        self._ai_is_currently_speaking = True
        self._speech_start_timer.stop()
        if self._is_lesson_mode and self.isActive:
            if not self.isPausedForSpeech:
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: AI Audio started, pausing for speech (isPausedForSpeech=True)")
                self._set_state(LessonState.AI_SPEAKING)
                self.lessonStateChanged.emit()

    @Slot()
    def resume_lesson(self):
        """Called when the coach finishes speaking (or, with no coach, in its
        place). Ends a lesson waiting on its closing words, or unpauses input
        and runs whatever setup was deferred until the coach was done."""
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Coach speech finished, resuming lesson. Pending end: {self._lesson_end_pending}")
        self._ai_is_currently_speaking = False
        self._speech_start_timer.stop()

        if self._lesson_end_pending:
            self._lesson_end_pending = False
            self._finalize_lesson_end()
            return

        # The scripted circle lessons handle their own narration.
        if self.isCircleOfFifthsMode:
            if self._dominant.active:
                self._dominant.on_speech_finished()
            else:
                self._circle.on_speech_finished()
            return

        # For normal (non-circle) lessons, run general post-speech resume logic
        self._resume_after_speech()

    @Slot()
    def continueCircleTutorial(self):
        """Called by QML when the user clicks Continue during the circle tutorial."""
        self._circle.advance()

    def _resume_after_speech(self):
        """
        Unpauses input and runs whatever was deferred until the coach finished:
        a listen preview, a metronome start, a check of keys already held.
        Also runs straight after presenting an exercise nobody is going to
        introduce, since then there is nothing to wait for.
        """
        should_check_immediately = False

        if self.isPausedForSpeech:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Unpausing speech (isPausedForSpeech=False)")
            self._set_state(LessonState.USER_PLAYING)
            self.lessonStateChanged.emit()
            self.inputReady.emit()
            # Defer _check_input until metronome and pending exercises are handled
            should_check_immediately = not self._require_key_release_before_eval

        # Play deferred listen preview now that the coach is done talking
        if self._listen_preview_pending:
            self._listen_preview_pending = False
            if self._target_pitches:
                print(f"ChordTrainer: Coach done, playing deferred MIDI preview: {self._target_pitches}")
                self._play_midi_preview(self._target_pitches)

        # Start deferred metronome now that the coach is done talking
        if self.metronome and self.metronome.has_deferred:
            self.metronome.flush_deferred()
            # If metronome is starting, skip immediate input evaluation to prevent "pre-hits"
            should_check_immediately = False

        if should_check_immediately:
            self._check_input()
        elif self._require_key_release_before_eval:
            print("ChordTrainer: Skipping immediate evaluation because key release lock is active.")

    def _advance_progression_chord(self):
        """Sets up the current chord within a progression sequence."""
        print(f"[PROG DEBUG] _advance_progression_chord called. index={self._progression_index}/{len(self._progression_steps) if self._progression_steps else 0}")
        if self._progression_index >= len(self._progression_steps):
            # Progression complete
            print(f"[PROG DEBUG] Progression complete (index >= len). Skipping.")
            return

        step = self._progression_steps[self._progression_index]
        root_idx = step["root_idx"]
        chord_type_name = step["chord_type_name"]
        intervals = step["intervals"]
        octave = step["octave"]
        numeral = step["numeral"]

        root_name = self.ROOT_NOTES[root_idx]
        self._target_chord_name = f"{root_name} {chord_type_name} ({numeral})" if numeral else f"{root_name} {chord_type_name}"
        self._review_chord = f"{root_name} {chord_type_name}"
        self._target_chord_type = chord_type_name

        # Clamp octave based on current hand assignment
        if self._current_hand == "right":
            octave = max(4, min(5, octave))
        elif self._current_hand == "left":
            octave = max(2, min(3, octave))
        base_pitch = (octave + 1) * 12 + root_idx
        self._target_pitches = sorted([(base_pitch + interval) for interval in intervals])

        hand_tag = "left" if self._current_hand == "left" else "right"
        self._target_hands = [hand_tag] * len(self._target_pitches)

        self._target_intervals = {(root_idx + interval) % 12 for interval in intervals}

        # Calculate formula text
        if len(intervals) <= 1:
            self._target_formula_text = ""
        else:
            sorted_intervals = sorted(list(intervals))
            steps = []
            for i in range(1, len(sorted_intervals)):
                diff = sorted_intervals[i] - sorted_intervals[i-1]
                steps.append(str(diff))
            self._target_formula_text = "Root + " + " + ".join(steps)

        # Reset per-chord state
        self._hold_progress = 0.0
        self._is_holding = False
        self._waiting_for_release = False
        self._required_hold_ms = 0
        self._hold_tick_timer.stop()
        self._prompt_time = time.time()
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False

        print(f"[PROG DEBUG] _advance_progression_chord set target: name={self._target_chord_name} pitches={self._target_pitches} intervals={self._target_intervals}")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._target_chord_name})")
        self.targetChordChanged.emit(self._target_chord_name)
        print(f"ChordTrainer: Progression chord {self._progression_index + 1}/{len(self._progression_steps)}: {self._target_chord_name}")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting inputReady")
        self.inputReady.emit()

    def _advance_song_chord(self):
        """Sets up the current grouping of notes for a song."""
        if self._song_index >= len(self._song_steps):
            # Song complete
            return
            
        self._prev_target_pitches = self._target_pitches
        step = self._song_steps[self._song_index]
        self._target_pitches = step['pitches']
        self._target_hands = step['hands']
        
        # Pull fingers from the same source as scrolling notes to guarantee sync
        self._target_fingers = step.get('fingers', [1] * len(self._target_pitches))
        self.targetFingersChanged.emit()
        
        # Exact match required for songs, but intervals are meaningless here
        self._target_intervals = set()
        
        # Advance the playhead in the UI
        self._set_stepped_scroll_beat(float(step['offset']))
        
        # Reset tracking state
        self._hold_progress = 0.0
        self._is_holding = False
        self._waiting_for_release = False
        self._required_hold_ms = 0
        self._hold_tick_timer.stop()
        self._prompt_time = time.time()
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False
        
        print(f"ChordTrainer: Song step {self._song_index + 1}/{len(self._song_steps)} at offset {self._scroll_beat}, pitches={self._target_pitches}")
        self.targetChordChanged.emit(self._target_chord_name)
        self.inputReady.emit()

    @Slot(int, bool)
    def handle_midi_note(self, pitch: int, is_on: bool):
        """Called by AppState when a MIDI note event occurs."""
        # Unconditionally process Note Off events so we never leak stuck keys.
        if not is_on:
            self._active_pitches.discard(pitch)

        if not self.isActive or self._is_lesson_complete:
            return

        # Evaluate Note On presses only when state == LessonState.USER_PLAYING
        if is_on and self._state != LessonState.USER_PLAYING:
            return

        # If it's a Note On, respect the ignore window (loopback prevention)
        if is_on and time.time() < self._ignore_midi_until:
            return

        # Playback Sequencer demo/duet input suppression
        if is_on and self._playback_service and self._playback_service.isPlaying:
            if self._playback_service.handFilter == "both":
                return
            elif self._playback_service.was_just_sent(pitch, 80.0):
                return

        # ── Phase 4 pacing gate ─────────────────────────────────────
        # In rhythm mode the RhythmEngine owns scoring outright. Returning here
        # guarantees the engine path and the self-paced path (_check_input →
        # _check_chord → _complete_chord → _advance_song_chord) can never both
        # run for the same note-on. _active_pitches is deliberately left alone:
        # it is the self-paced path's state, and leaving it empty also keeps
        # `mistakeActive` (and its whole-sheet dim) inert without modifying it.
        if self._exercise_type == "song_application" and self._pacing_mode == "rhythm":
            self._rhythm_engine.handle_midi_note(pitch, is_on)
            return

        if is_on:
            self._active_pitches.add(pitch)

            # Song mistakes are counted here rather than via _target_intervals,
            # which songs leave empty. Previous-step pitches are tolerated for
            # the same legato reason `mistakeActive` tolerates them.
            if self._exercise_type == "song_application":
                if pitch not in self._target_pitches and pitch not in self._prev_target_pitches:
                    self._song_wrong_notes += 1

            # Record first note time for simultaneity detection
            if self._first_note_time == 0.0:
                self._first_note_time = time.time() * 1000.0

            # Track wrong notes (notes not in target intervals).
            if self._exercise_type == "pentascale":
                # For pentascale, check against the exact current target pitch
                if self._pentascale_sequence and self._pentascale_index < len(self._pentascale_sequence):
                    if pitch != self._pentascale_sequence[self._pentascale_index]:
                        self._wrong_notes_count += 1
            elif self._target_intervals:
                if (pitch % 12) not in self._target_intervals:
                    self._wrong_notes_count += 1

        # Check key release lock
        if self._require_key_release_before_eval:
            if len(self._active_pitches) == 0:
                print("ChordTrainer: Key release lock disengaged. User lifted hands.")
                self._require_key_release_before_eval = False
                self._wrong_notes_count = 0
                self._first_note_time = 0.0
            else:
                return # Block evaluation while lock is active

        # We must never evaluate input or advance sequences while the AI coach is talking
        if self.isPausedForSpeech:
            return

        if self._waiting_for_release:
            if len(self._active_pitches) == 0:
                self._waiting_for_release = False
                if self._dominant.active:
                    self._dominant.on_keys_released()
                elif self._exercise_type == "pentascale":
                    if self._pentascale_index < len(self._pentascale_sequence):
                        # Still in the pentascale sequence — just continue, don't call _next_chord
                        pass
                    else:
                        QTimer.singleShot(700, self._next_chord)
                elif self._exercise_type == "song_application":
                    self._advance_song_chord()
                else:
                    QTimer.singleShot(700, self._next_chord)
            return

        self._check_input()
        self.lessonStateChanged.emit()

    def _check_input(self):
        """Routes input validation based on exercise type."""
        if self._exercise_type in ["progression", "song_application"]:
            print(f"[_check_input] type={self._exercise_type} "
                  f"active_pitches={sorted(self._active_pitches)} target_pitches={sorted(self._target_pitches) if self._target_pitches else []}")
        if self._exercise_type == "listen":
            # Listen exercises are answered via QML UI buttons, not MIDI keyboard
            return

        if self._exercise_type == "pentascale":
            self._check_pentascale()
        elif self._exercise_type == "steady_pulse":
            self._check_steady_pulse()
        else:
            self._check_chord()

    def _check_pentascale(self):
        """Validates single-note input for pentascale exercises."""
        # Wait until the lead-in is complete if we are running a metronome
        if self.isPausedForSpeech or (self.metronome and self.metronome.has_deferred):
            return

        if self.metronome and self.metronome.is_in_lead_in:
            # Strictly ignore input during lead-in
            return

        if not self._pentascale_sequence or self._pentascale_index >= len(self._pentascale_sequence):
            return

        target_pitch = self._pentascale_sequence[self._pentascale_index]

        # Check if the target note is among the currently held keys (legato-friendly)
        # This allows the player to hold the previous note while pressing the next
        if target_pitch in self._active_pitches:
            # Correct note! Advance to the next note in the sequence
            print(f"ChordTrainer: Pentascale note {self._pentascale_index + 1}/5 correct: {self.ROOT_NOTES[target_pitch % 12]}")

            # Calculate timing feedback if metronome is active
            feedback_text = ""
            timing_offset = 0.0
            if self.metronome and self.metronome.isRunning:
                timing_offset = self.metronome.get_timing_offset_ms(self._pentascale_index)
                
                if timing_offset < -150:
                    feedback_text = "Fast"
                elif timing_offset > 150:
                    feedback_text = "Slow"
                else:
                    feedback_text = "Perfect!"

                print(f"ChordTrainer: Timing for note {self._pentascale_index}: diff={timing_offset:.0f}ms -> {feedback_text}")

            self.pentascaleNoteHit.emit(self._pentascale_index, feedback_text)

            # Record success for this individual note
            note_name = f"{self.ROOT_NOTES[target_pitch % 12]} (Pentascale)"
            latency_ms = (time.time() - self._prompt_time) * 1000.0
            self.db.record_chord_attempt(note_name, True, latency_ms, 0, False, timing_offset)

            self._pentascale_index += 1
            self.currentNoteIndexChanged.emit()
            if self._scroll_bpm == 0:
                self._set_stepped_scroll_beat(float(self._pentascale_index))

            if self._pentascale_index >= len(self._pentascale_sequence):
                # All 5 notes played correctly — complete the step
                # Delay slightly so the final dot has time to turn green in the UI
                if self.metronome:
                    self.metronome.stop()
                QTimer.singleShot(600, self._complete_chord)
            else:
                # Update target intervals to next note (no release wait — allows legato)
                next_pitch = self._pentascale_sequence[self._pentascale_index]
                self._target_intervals = {next_pitch % 12}
                
                hand_tag = "left" if self._current_hand == "left" else "right"
                self._target_pitches = [next_pitch]
                self._target_fingers = [self._pentascale_fingers[self._pentascale_index]]
                self._current_hand = hand_tag # Standard hand from exercise
                self._target_hands = [hand_tag]
                self.targetFingersChanged.emit()
                self.targetChordChanged.emit("")
                self._prompt_time = time.time()  # Reset timing for next note
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._target_chord_name})")
        self.targetChordChanged.emit(self._target_chord_name)

    def _check_chord(self):
        if not self._target_pitches:
            return

        # Do not evaluate if we are explicitly waiting for a full key release
        if self._waiting_for_release:
            return

        active_set = set(self._active_pitches)
        target_set = set(self._target_pitches)

        # DEBUG: Log every chord check for progression exercises
        if self._exercise_type == "progression" and len(active_set) > 0:
            active_intervals = {p % 12 for p in active_set}
            target_intervals_check = {p % 12 for p in target_set}
            print(f"[PROG DEBUG] _check_chord: active_pitches={sorted(active_set)} target_pitches={sorted(target_set)} "
                  f"active_intervals={active_intervals} target_intervals={target_intervals_check} "
                  f"exact_match={active_set == target_set} interval_match={active_intervals == target_intervals_check} "
                  f"_is_holding={self._is_holding} _required_hold_ms={self._required_hold_ms}")

        # Check for exact pitch match (octave-strict)
        if active_set == target_set:
            self._wrong_chord_timer.stop()
            self._sustain_grace_timer.stop()

            if self._exercise_type == "hands_together":
                # redundant with exact set match but kept for clarity:
                # target_set already includes the low notes.
                pass

            if not self._is_holding:
                self._is_holding = True
                self._hold_start_time = time.time() * 1000.0

                # Calculate simultaneity: if all notes reached within 100ms of first note
                if self._first_note_time > 0:
                    delta = self._hold_start_time - self._first_note_time
                    self._is_simultaneous = (delta < 150) # 150ms is a generous 'block chord' threshold

                if self._exercise_type == "sustain_pedal" and not self._pedal_satisfied:
                    # Check if they pressed the pedal slightly *before* the keys (direct pedal only)
                    if self._pedal_type == "direct" and self._is_pedal_down:
                        pedal_timing = self._hold_start_time - self._pedal_down_time
                        if pedal_timing <= 400: # up to 400ms early
                            self._pedal_satisfied = True

                    if not self._pedal_satisfied:
                        return # Wait for the pedal to be engaged

                if self._required_hold_ms > 0:
                    self._hold_tick_timer.start()
                else:
                    self._complete_chord()
            else:
                # We are already holding. Re-evaluate if pedal satisfaction unlocked progression
                if self._exercise_type == "sustain_pedal" and self._pedal_satisfied:
                    if self._required_hold_ms > 0 and not self._hold_tick_timer.isActive():
                        self._hold_tick_timer.start()
                    elif self._required_hold_ms == 0:
                        self._complete_chord()
        else:
            # If they are holding keys but they are not right,
            # decide if we should flash red (wrong notes) or just wait (wrong octave).
            if len(self._active_pitches) > 0 and not self._is_holding:
                # Check if it's just an octave error
                active_intervals = {p % 12 for p in self._active_pitches}
                if active_intervals == self._target_intervals:
                    # Right notes, wrong octave. No red flash, just stay silent.
                    self._wrong_chord_timer.stop()
                else:
                    # Wrong notes entirely. Start the "You missed" timer for red flash.
                    # For Dominant Motion, trigger immediately to give reactive red flash
                    if self._dominant.active:
                        if not self._wrong_chord_timer.isActive():
                            self._wrong_chord_timer.start(self._dominant.WRONG_CHORD_MS)
                    elif len(self._active_pitches) == len(self._target_pitches):
                        # Standard lesson still requires right count for red flash
                        if not self._wrong_chord_timer.isActive():
                            self._wrong_chord_timer.start(300)
            else:
                self._wrong_chord_timer.stop()

            # If they let go or miss-pressed during a hold, cancel the hold
            # Use a 150ms grace period to handle acoustic key bounce where a human's finger
            # might hover slightly above the piano actuation point mid-sustain.
            if self._is_holding and self._required_hold_ms > 0:
                if not self._sustain_grace_timer.isActive():
                    self._sustain_grace_timer.start(150)

    @Slot()
    def _on_wrong_chord_timeout(self):
        if not self._is_holding and self._target_intervals:
            active_intervals = {pitch % 12 for pitch in self._active_pitches}
            is_valid_count = len(self._active_pitches) == len(self._target_pitches)
            
            # Dominant Motion triggers on ANY wrong note count to be reactive
            if self._dominant.active:
                is_valid_count = len(self._active_pitches) > 0

            if is_valid_count and active_intervals != self._target_intervals:
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting chordFailed (wrong notes)")
                self._exercise_struggled = True
                self.chordFailed.emit()
                latency_ms = (time.time() - self._prompt_time) * 1000.0
                self.db.record_chord_attempt(self._target_chord_name, False, latency_ms,
                                           self._wrong_notes_count, False)
                self._record_chord_review(False)
                if self.curriculum:
                    self.curriculum.complete_exercise(self._target_chord_name, False, 
                                                     self._current_track, self._current_milestone_id)

                # Dominant Motion: wrong chord → hint once the keys are up
                if self._dominant.active:
                    self._dominant.on_wrong_chord(list(self._active_pitches))

    # Exercise types whose target is a chord worth scheduling for review.
    REVIEWABLE_CHORD_EXERCISES = ("chord", "hands_together", "sustain_pedal", "progression")

    def _record_chord_review(self, success: bool, latency_ms: float = 0.0, wrong_notes: int = 0):
        """Grades this attempt for the SM-2 schedule (first attempt of the day counts)."""
        if self._exercise_type not in self.REVIEWABLE_CHORD_EXERCISES or not self._review_chord:
            return
        try:
            self.db.record_review("chord", self._review_chord,
                                  quality_for_chord(success, latency_ms, wrong_notes))
        except Exception as e:
            print(f"ChordTrainer: Could not record review of {self._review_chord}: {e}")

    @Slot()
    def _on_sustain_grace_timeout(self):
        if self._is_holding and self._required_hold_ms > 0:
            active_intervals = {pitch % 12 for pitch in self._active_pitches}
            if active_intervals != self._target_intervals:
                self._is_holding = False
                self._hold_progress = 0.0
                self._hold_tick_timer.stop()
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting lessonStateChanged")
                self.lessonStateChanged.emit() # update progress bar to 0

    def _on_hold_tick(self):
        """Timer callback to update the visual hold progress bar"""
        if not self._is_holding or not self.isActive:
            self._hold_tick_timer.stop()
            return

        elapsed = (time.time() * 1000.0) - self._hold_start_time

        if elapsed >= self._required_hold_ms:
            self._hold_progress = 1.0
            self._hold_tick_timer.stop()
            self._complete_chord()
        else:
            self._hold_progress = elapsed / self._required_hold_ms
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting lessonStateChanged (progress bar)")
        self.lessonStateChanged.emit() # update progress bar

    def _complete_chord(self):
        latency_ms = (time.time() - self._prompt_time) * 1000.0
        print(f"ChordTrainer: SUCCESS! {self._target_chord_name} matched in {latency_ms:.1f}ms")

        # Record success in DB and local session stats
        self.db.record_chord_attempt(self._target_chord_name, True, latency_ms,
                                   self._wrong_notes_count, self._is_simultaneous)
        self._record_chord_review(True, latency_ms, self._wrong_notes_count)
        if self.curriculum:
            self.curriculum.complete_exercise(self._target_chord_name, True, 
                                             self._current_track, self._current_milestone_id)

        # Record in session stats
        stat_key = self._target_chord_name
        if self._exercise_type == "pentascale":
            stat_key = self._scale_name
        if stat_key not in self._session_stats:
            self._session_stats[stat_key] = []
        self._session_stats[stat_key].append(latency_ms)

        # Track items for Dashboard "Quick Review" 
        # Threshold: Latency > 4s OR > 2 wrong notes
        is_struggle = latency_ms > 4000 or self._wrong_notes_count > 2
        if is_struggle:
            item = {
                "name": self._target_chord_name,
                "type": self._exercise_type,
                "latency": latency_ms,
                "wrong_notes": self._wrong_notes_count,
                "chord_data": self._current_step_data
            }
            # Avoid duplicates
            if not any(s["name"] == item["name"] for s in self._struggled_items):
                self._struggled_items.append(item)

        # --- Inter-exercise commentary streak tracking ---
        if is_struggle:
            self._exercise_struggled = True
            self._consecutive_successes = 0
            self._consecutive_struggles += 1
        else:
            self._consecutive_struggles = 0
            self._consecutive_successes += 1
            self._struggle_tip_given = False

        # Notify UI
        display_name = self._target_chord_name
        if self._exercise_type == "pentascale":
            # For pentascales, show a qualitative summary instead of raw ms
            # Calculate quality based on avg latency or wrong notes (simple version for now)
            if self._wrong_notes_count == 0:
                display_name = "Excellent Timing!"
            elif self._wrong_notes_count <= 2:
                display_name = "Good Pace"
            else:
                display_name = "Keep Practicing"

        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting chordSuccess ({display_name}, {latency_ms:.1f}ms)")
        self.chordSuccess.emit(display_name, latency_ms)

        # Reset hold state
        self._hold_progress = 0.0
        self._is_holding = False
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting lessonStateChanged")
        self.lessonStateChanged.emit()

        # Short pause before advancing to avoid double-triggers (non-blocking)
        # The _waiting_for_release pattern below handles the actual gating

        # The V→I drill moves on by itself (takes priority over the lesson flow)
        if self._dominant.active:
            self._dominant.on_chord_complete()
            return

        # Handle progression sub-step advancement
        if self._exercise_type == "progression":
            self._progression_index += 1
            if self._scroll_bpm == 0:
                self._set_stepped_scroll_beat(float(self._progression_index))
                
            if self._progression_index < len(self._progression_steps):
                print(f"ChordTrainer: Advancing to next progression chord immediately...")
                self._advance_progression_chord()
                return
            # else: progression complete, fall through to _next_chord

        if self._exercise_type == "song_application":
            self._song_index += 1
            if self._song_index < len(self._song_steps):
                print("ChordTrainer: Advancing song immediately (Legato-Friendly)")
                self._advance_song_chord()
                return
            else:
                # Last note played — advance beat past song end so all notes render gray
                self._set_stepped_scroll_beat(self._song_end_beat + 0.5)
                self._song_completed = True
                self.songCompletedChanged.emit()
                # Only a lesson has an AI turn worth blocking for, and only
                # _apply_exercise clears this window. In free play nothing ever
                # would, so the block outlived the song and deafened the next
                # one. Mirrors the same guard on the rhythm path.
                if self._is_lesson_mode:
                    self._ignore_midi_until = time.time() + 99.0  # until the AI responds
                print(f"ChordTrainer: Song complete — '{self._song_title}'")
                QTimer.singleShot(1500, self._on_song_finished)
                return

        if self._exercise_type == "listen":
            # For listening quizzes, the user answers via UI, not keys. Pause briefly then move on.
            QTimer.singleShot(700, self._next_chord)
        else:
            # Fluid advancement: don't wait for release, just short delay for the "SUCCESS" to register visually
            self._waiting_for_release = False
            QTimer.singleShot(300, self._next_chord)

    @Slot()
    def _on_metronome_tick_legacy(self):
        """Cleanup: MetronomeService now owns the timer."""
        pass

    def _setup_steady_pulse_target(self, chord_data):
        """Sets up a steady pulse exercise: user repeats a chord/note on every beat."""
        root_idx = int(chord_data.get("root_idx", 0))
        chord_type_name = str(chord_data.get("chord_type", "Major"))
        intervals = self.CHORD_TYPES.get(chord_type_name, self.CHORD_TYPES["Major"])
        octave = int(chord_data.get("octave", 4))
        self._setup_target(root_idx, chord_type_name, intervals, octave)
        self._exercise_type = "steady_pulse"
        self._steady_pulse_beats = int(chord_data.get("pulse_count", 16))
        self._steady_pulse_hits = []
        self._steady_pulse_current_beat = 0
        self._steady_pulse_missed_beats = 0
        
        # Build scrolling notes
        sn = []
        base_pitch = (octave + 1) * 12 + root_idx
        for i in range(self._steady_pulse_beats):
            sn.append({
                "pitch": base_pitch,
                "start_beat": i,
                "duration_beats": 1,
                "finger": 1,
                "hand": "R" if octave >= 4 else "L"
            })
        self._scrolling_notes = sn
        self.scrollingNotesChanged.emit()

        bpm = int(chord_data.get("bpm", 100))
        self._scroll_bpm = bpm
        self.scrollBpmChanged.emit()
        self._scroll_beat = 0.0 if bpm == 0 else (self.metronome.currentBeatPosition if self.metronome else 0.0)
        self.scrollBeatChanged.emit(self._scroll_beat)
        self._emit_scroll_anchor(self._scroll_beat, bpm / 60.0, active=bpm > 0, snap=True)
        if self.metronome:
            if self._ai_is_currently_speaking or self.isPausedForSpeech:
                self.metronome.defer_start(bpm)
            else:
                self.metronome.start(bpm)
        print(f"ChordTrainer: Steady Pulse started for {self._target_chord_name} at {bpm} BPM")

    def _check_steady_pulse_beat(self, beat_count):
        """Logic called every metronome tick during steady_pulse."""
        if beat_count > self._steady_pulse_beats:
            print(f"ChordTrainer: Steady Pulse complete ({len(self._steady_pulse_hits)}/{self._steady_pulse_beats} hits)")
            if self.metronome:
                self.metronome.stop()
            self._complete_chord()

    def _check_steady_pulse(self):
        """Validates timing of a hit in steady_pulse mode."""
        if not self.metronome or self.metronome.is_in_lead_in:
            return

        # Correct chord?
        if not self._is_chord_satisfied():
            return

        # Find the nearest beat
        # (Simplified: we track hits and timing offsets)
        timing_offset = self.metronome.get_timing_offset_ms(self._steady_pulse_current_beat)
        
        # Only record if we haven't hit this beat yet and it's within a window
        # For now, just record it and the evaluator can deal with details
        if abs(timing_offset) < 300: # 300ms window
            # Prevent double-recording same beat
            self._steady_pulse_hits.append(timing_offset)
            print(f"ChordTrainer: Steady Pulse Hit on beat {self._steady_pulse_current_beat}, offset {timing_offset:.1f}ms")
            
            # Emit success signal for visual feedback
            self.chordSuccess.emit(self._target_chord_name, timing_offset)
            
            # Record in DB
            self.db.record_chord_attempt(self._target_chord_name, True, timing_offset, 0, True, timing_offset)

    def _is_chord_satisfied(self) -> bool:
        """Helper to check if currently held keys match target pitches exactly."""
        active_set = set(self._active_pitches)
        target_set = set(self._target_pitches)
        return active_set == target_set

