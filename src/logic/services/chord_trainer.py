import os
import time
import random
import json
from typing import Set, List, Dict, Tuple
from datetime import datetime
from enum import Enum, auto
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt # type: ignore

class LessonState(Enum):
    IDLE = auto()               # Not in a lesson
    LOADING = auto()            # Initial lesson loading
    AWAITING_EXERCISE = auto()  # Requested next exercise, waiting for AI tool call
    AI_SPEAKING = auto()        # AI is introducing the exercise
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
    loadingStatusChanged = Signal()
    speakInstruction = Signal(str)
    speakBrief = Signal(str)              # Non-blocking brief coach commentary
    apiConnectivityChanged = Signal(bool)  # True = confirmed, False = lost
    midiOutRequested = Signal(list)
    metronomeTick = Signal()
    inputReady = Signal()                 # Emitted exactly when a drill is ready for user input
    waitingForUserContinueChanged = Signal(bool)

    # Single-model architecture signals
    requestLessonStart = Signal(str)    # Emitted with the full lesson prompt for the AI coach
    reportPerformance = Signal(str)     # Emitted after each exercise with performance data
    exerciseRequestUnlocked = Signal()  # Emitted when a dropped tool call failsafe triggers
    isCircleOfFifthsModeChanged = Signal(bool)  # Emitted when entering/leaving circle of fifths lesson
    theoryVisualDirect = Signal(dict)  # Directly push visual state from Python (bypass AI)

    def __init__(self, db_manager, curriculum_service=None, settings_manager=None):
        super().__init__()
        self.db = db_manager
        self.curriculum = curriculum_service
        self.settings = settings_manager

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

        # Dashboard and Performance Review
        self._struggled_items: List[Dict] = []
        self._current_step_data: Dict = {}

        # Lesson State
        self._is_lesson_mode = False
        self._lesson_playlist = []
        self._lesson_blocks = []  # Stable snapshot of exercise blocks for sidebar
        self._lesson_progress = 0
        self._lesson_total = 0
        self._exercise_name = "Free Practice"
        self._exercise_type = "chord"  # "chord", "pentascale", or "progression"
        self._current_hand = "right"  # "right", "left", or "both"
        self._is_lesson_complete = False
        self._loading_status_text = ""
        self._require_key_release_before_eval = False
        self._pending_exercise = None  # Single-slot queue to prevent rapid-fire overwrites
        self._listen_preview_pending = False  # Deferred MIDI preview for listen exercises
        self._ignore_midi_until = 0.0   # Ignore MIDI input while previewing
        self._session_stats: Dict[str, List[float]] = {}
        self._estimated_gen_ms = 5000.0
        self._exercise_history: List[str] = []
        self._lesson_roadmap = ""  # Persist the roadmap (blocks) to survive reco drops
        self._lesson_end_pending = False # Defer showing completion UI until AI finishes speaking
        self._is_circle_of_fifths_mode = False  # True while Circle of Fifths tutorial is the active lesson
        self._waiting_for_user_continue = False

        # Dominant Motion Trainer (V→I) State
        self._is_dominant_motion_mode = False
        self._dominant_motion_step = 0
        self._dominant_motion_hint_sent = False
        self._wrong_chord_needs_hint = False
        self._wrong_chord_pitches_snapshot = []
        self._dominant_motion_complete = False  # Prevent duplicate hints per step
        self._dominant_motion_hesitation_timer = QTimer(self)
        self._dominant_motion_hesitation_timer.setSingleShot(True)
        self._dominant_motion_hesitation_timer.setInterval(3000)  # 3 seconds
        self._dominant_motion_hesitation_timer.timeout.connect(self._dominant_motion_hint)

        # V→I pairs: (V_key, I_key, V_root_idx, I_root_idx, shared_note)
        # shared_note = the 5th of I chord = root of V chord
        self.DOMINANT_MOTION_PAIRS = [
            {"v_key": "G", "i_key": "C", "v_root": 7,  "i_root": 0,  "shared": "G"},
            {"v_key": "D", "i_key": "G", "v_root": 2,  "i_root": 7,  "shared": "D"},
            {"v_key": "A", "i_key": "D", "v_root": 9,  "i_root": 2,  "shared": "A"},
            {"v_key": "C", "i_key": "F", "v_root": 0,  "i_root": 5,  "shared": "C"},
            {"v_key": "E", "i_key": "A", "v_root": 4,  "i_root": 9,  "shared": "E"},
            {"v_key": "B", "i_key": "E", "v_root": 11, "i_root": 4,  "shared": "B"},
        ]
        
        # Metronome Service (provided by AppState)
        self.metronome = None

        # Inter-exercise commentary streak tracking
        self._consecutive_successes = 0
        self._consecutive_struggles = 0

        # Pentascale State
        self._pentascale_sequence: List[int] = []  # Exact MIDI pitches for the 5-note sequence
        self._scale_name = ""
        self._pentascale_index = 0

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

        # A simple library of chords defined by their intervals from a root note (0)
        # 0 = Root, 4 = Major 3rd, 7 = Perfect 5th, etc.
        self.CHORD_TYPES = {
            "Major": {0, 4, 7},
            "Minor": {0, 3, 7},
            "Diminished": {0, 3, 6},
            "Augmented": {0, 4, 8},
            "Dominant 7th": {0, 4, 7, 10},
            "Major 7th": {0, 4, 7, 11},
            "Minor 7th": {0, 3, 7, 10},
            "Single": {0},
        }
        # Common AI shorthand aliases → canonical CHORD_TYPES keys
        self.CHORD_TYPE_ALIASES = {
            "Major7": "Major 7th",
            "Minor7": "Minor 7th",
            "Dom7": "Dominant 7th",
            "Dominant7": "Dominant 7th",
            "Dim": "Diminished",
            "Aug": "Augmented",
            "Maj7": "Major 7th",
            "Min7": "Minor 7th",
            "major": "Major",
            "minor": "Minor",
        }

        # Pentascale patterns: intervals from root for each scale type
        self.PENTASCALE_PATTERNS = {
            "Major": [0, 2, 4, 5, 7],      # W-W-H-W (C-D-E-F-G)
            "Minor": [0, 2, 3, 5, 7],      # W-H-W-W (C-D-Eb-F-G)
        }

        self.ROOT_NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

    def set_metronome(self, service):
        """Inject the standalone MetronomeService."""
        self.metronome = service
        if self.metronome:
            self.metronome.tick.connect(self._on_metronome_tick)

    def _on_metronome_tick(self, beat_count):
        # Forward to QML (keeping existing signal for compatibility)
        self.metronomeTick.emit()
        
        # If we are in steady_pulse mode, check if we need to advance on the beat
        if self._exercise_type == "steady_pulse" and self._state == LessonState.USER_PLAYING:
            if beat_count >= 1: # Start counting hits once real beats begin
                self._check_steady_pulse_beat(beat_count)

    def _set_state(self, new_state: LessonState):
        if hasattr(self, '_state') and self._state == new_state:
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
    def isActive(self) -> bool:
        return self._state != LessonState.IDLE

    @Property(str, notify=targetChordChanged)
    def targetChord(self) -> str:
        return self._target_chord_name

    @Property(list, notify=targetChordChanged)
    def targetPitches(self) -> list:
        return self._target_pitches

    @Property(list, notify=targetChordChanged)
    def targetHands(self) -> list:
        return self._target_hands

    @Property(str, notify=targetChordChanged)
    def pedalType(self) -> str:
        return self._pedal_type

    @Property(str, notify=lessonStateChanged)
    def exerciseName(self) -> str:
        return self._exercise_name

    @Property(bool, notify=lessonStateChanged)
    def isPausedForSpeech(self) -> bool:
        return self._state == LessonState.AI_SPEAKING

    @Property(int, notify=lessonStateChanged)
    def lessonProgress(self) -> int:
        return self._lesson_progress

    @Property(int, notify=lessonStateChanged)
    def lessonTotal(self) -> int:
        return self._lesson_total

    @Property(bool, notify=lessonStateChanged)
    def isWaitingForAi(self) -> bool:
        return self._state == LessonState.AWAITING_EXERCISE

    @Property(list, notify=lessonStateChanged)
    def lessonBlocks(self) -> list:
        return self._lesson_blocks

    @Property(bool, notify=lessonStateChanged)
    def isLessonComplete(self) -> bool:
        return self._is_lesson_complete

    @Property(bool, notify=lessonStateChanged)
    def isWaitingToBegin(self) -> bool:
        return self._state == LessonState.WAITING_TO_BEGIN

    @Property(str, notify=lessonStateChanged)
    def currentHand(self):
        return self._current_hand

    @Property(bool, notify=lessonStateChanged)
    def isLessonMode(self) -> bool:
        return self._is_lesson_mode

    @Property(bool, notify=isCircleOfFifthsModeChanged)
    def isCircleOfFifthsMode(self) -> bool:
        return self._is_circle_of_fifths_mode

    @Property(bool, notify=waitingForUserContinueChanged)
    def isWaitingForUserContinue(self) -> bool:
        return getattr(self, '_waiting_for_user_continue', False)

    @Property(float, notify=lessonStateChanged)
    def holdProgress(self) -> float:
        return self._hold_progress

    @Property(int, notify=lessonStateChanged)
    def requiredHoldMs(self) -> int:
        return self._required_hold_ms

    @Property(bool, notify=lessonStateChanged)
    def isLoading(self) -> bool:
        return self._state == LessonState.LOADING

    @Property(str, notify=loadingStatusChanged)
    def loadingStatusText(self) -> str:
        return self._loading_status_text

    @Property(float, notify=loadingStatusChanged)
    def estimatedGenerationMs(self) -> float:
        return self._estimated_gen_ms

    @Property(str, notify=targetChordChanged)
    def targetChordType(self) -> str:
        return self._target_chord_type

    @Property(str, notify=targetChordChanged)
    def targetFormulaText(self) -> str:
        return self._target_formula_text

    @Property(str, notify=lessonStateChanged)
    def exerciseType(self) -> str:
        return self._exercise_type

    @Property(list, notify=targetChordChanged)
    def pentascaleNotes(self) -> list:
        return self._pentascale_sequence
    @Property(list, notify=lessonStateChanged)
    def struggledItems(self):
        """List of items where user performance was below threshold."""
        return self._struggled_items

    @Property(int, notify=targetChordChanged)
    def currentNoteIndex(self) -> int:
        return self._pentascale_index

    @Property(int, notify=metronomeTick)
    def pentascaleBeatCount(self) -> int:
        return self.metronome.beatCount if self.metronome else 0

    @Property(list, notify=lessonStateChanged)
    def progressionNumerals(self) -> list:
        return self._progression_numerals

    @Property(int, notify=targetChordChanged)
    def currentProgressionIndex(self) -> int:
        return self._progression_index

    @Property(str, notify=targetChordChanged)
    def scaleName(self) -> str:
        return self._scale_name

    @Slot()
    def start_session(self):
        # Free Practice Mode
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
        """Start a new lesson by sending context to the AI coach via WebSocket.

        Instead of generating the entire plan via REST API, we send the session
        context to the live voice model and let it generate exercises one at a
        time via tool calls while speaking instructions.
        """
        if self.isLoading:
            return

        self._is_lesson_mode = True
        self._is_lesson_complete = False
        self._lesson_progress = 0
        self._lesson_total = 0
        self._lesson_playlist = []
        self._lesson_blocks = []

        self._estimated_gen_ms = 3000.0  # Much faster now — single round-trip
        self._loading_status_text = "PREPARING LESSON PLAN..."
        self._set_state(LessonState.LOADING)

        self._active_pitches.clear()
        self._session_stats.clear()
        self._struggled_items.clear()
        self._pending_exercise = None
        self._consecutive_successes = 0
        self._consecutive_struggles = 0

        # Build the curriculum context
        user_context = ""
        session_plan = None
        if self.curriculum:
            session_plan = self.curriculum.plan_session(available_minutes=available_minutes)
            user_context = self.curriculum.get_curriculum_context()
        else:
            user_context = self.db.get_coach_context()

        learned_terms = self.db.get_learned_term_names()
        if learned_terms:
            user_context += f"\n\nALREADY EXPLAINED TERMS (DO NOT explain these again!):\n{', '.join(learned_terms)}\n"

        seen_exercises = self.db.get_seen_exercise_intros()
        if seen_exercises:
            user_context += f"\n\nSEEN EXERCISES (User already knows how to do these):\n{', '.join(seen_exercises)}\n"

        # Build the lesson prompt for the live model
        dev_mode = os.environ.get("DEV_MODE", "false").lower() in ("true", "1", "yes")

        blocks_text = ""
        if session_plan and "blocks" in session_plan:
            if dev_mode:
                blocks_text = "Here is the SESSION PLAN. You will assign 2-3 exercises per block ONE AT A TIME (DEV MODE — short session):\n"
            else:
                blocks_text = "Here is the SESSION PLAN. You will assign 20-40 exercises per block ONE AT A TIME:\n"

            for i, b in enumerate(session_plan["blocks"]):
                blocks_text += f"\nBlock {i+1}: {b['milestone_title']} (track: '{b['track']}', milestone_id: '{b['milestone_id']}')\n"
                blocks_text += f"- Goal: {b['milestone_description']}\n"
                blocks_text += f"- Target Keys: {b['target_keys']}\n"
                blocks_text += f"- Target Chords: {b['target_chords']}\n"
                blocks_text += f"- Target exercise count: {b['step_count']}\n"

            if session_plan.get("review_items"):
                if dev_mode:
                    blocks_text += "\nREVIEW ITEMS (SM-2): Include 1 drill for each:\n"
                else:
                    blocks_text += "\nREVIEW ITEMS (SM-2): Include 2-3 drills for each:\n"
                for r in session_plan["review_items"]:
                    blocks_text += f"- {r['item_type']}: {r['item_id']}\n"
        else:
            blocks_text = "The student is a complete beginner. Start with a C Major Pentascale (C-D-E-F-G)."

        self._lesson_roadmap = blocks_text

        # Check for Circle of Fifths Tutorial Milestone injection
        is_circle_tutorial = False
        if session_plan and "blocks" in session_plan and session_plan["blocks"]:
            first_block = session_plan["blocks"][0]
            if first_block.get("track") == "theory" and first_block.get("milestone_id") == "circle_of_fifths":
                is_circle_tutorial = True

        if is_circle_tutorial:
            if not self._is_circle_of_fifths_mode:
                self._is_circle_of_fifths_mode = True
                self.isCircleOfFifthsModeChanged.emit(True)
            self._circle_tutorial_step = 1
            prompt = self._get_circle_tutorial_prompt(self._circle_tutorial_step, user_context)
        else:
            prompt = f"""<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>
START A NEW LESSON. [INITIAL_LOAD]

{user_context}

{blocks_text}

INSTRUCTIONS:
1. You MUST call the `set_exercise` tool right now to assign the first exercise. Do NOT forget to call the tool.
2. Speak a brief welcome and session overview, AND explicitly explain how to perform the very first exercise you are assigning so the student knows what to do.
3. Wait for me to report the student's performance before calling the tool again.
4. When they finish an exercise, I will send you a report. Decide the next step (advance, repeat, or simplify) and call `set_exercise` again.
5. When the session is complete, call `end_lesson`.
6. You MUST REMAIN COMPLETELY SILENT between exercises of the SAME type. Do NOT provide any micro-affirmations or commentary. Just call `set_exercise` immediately.
7. Only speak longer sentences when introducing a NEW exercise type FOR THE FIRST TIME, giving feedback on significant struggles, or ending.

Available exercise_type values: chord, pentascale, progression, listen, hands_together, sustain_pedal
Available chord_type_name values: Major, Minor, Diminished, Augmented, Sus2, Sus4, Major7, Minor7, Dominant7

Start the lesson now by calling set_exercise and speaking.
</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"""

        self.requestLessonStart.emit(prompt)

        # Safety timeout: if AI doesn't send set_exercise within 60s, recover.
        # Long intros can easily exceed 30s.
        QTimer.singleShot(60000, self._lesson_loading_timeout)

    @Slot(str, str)
    def start_single_drill(self, track_name: str, milestone_id: str):
        """Starts a session strictly focused on a single milestone."""
        if self.isLoading:
            return

        self._is_lesson_mode = True
        self._is_lesson_complete = False
        self._lesson_progress = 0
        self._lesson_total = 0
        self._lesson_playlist = []
        self._lesson_blocks = []

        self._estimated_gen_ms = 3000.0  
        self._loading_status_text = "PREPARING DRILL..."
        self._set_state(LessonState.LOADING)

        self._active_pitches.clear()
        self._session_stats.clear()
        self._struggled_items.clear()
        self._pending_exercise = None
        self._consecutive_successes = 0
        self._consecutive_struggles = 0

        user_context = self.db.get_coach_context()
        
        target_keys = []
        target_chords = []
        milestone_title = milestone_id
        if self.curriculum:
            meta = self.curriculum._get_milestone_meta(track_name, milestone_id)
            if meta:
                milestone_title = meta.get("title", milestone_id)
                target_keys = meta.get("target_keys", [])
                target_chords = meta.get("target_chords", [])

        blocks_text = "The user has elected to run a SINGLE FOCUSED LESSON, bypassing the standard curriculum.\n"
        blocks_text += f"You will assign exactly ONE type of exercise over and over (approx 10-15 reps) until they master it, then call end_lesson.\n\n"
        blocks_text += f"Target Drill: {milestone_title} (track: '{track_name}', milestone_id: '{milestone_id}')\n"
        if target_keys:
            blocks_text += f"- Allowed Keys: {target_keys}\n"
        if target_chords:
            blocks_text += f"- Allowed Chords: {target_chords}\n"

        self._lesson_roadmap = blocks_text

        is_circle_tutorial = (track_name == "theory" and milestone_id == "circle_of_fifths")
        is_dominant_motion = (track_name == "theory" and milestone_id == "dominant_motion")

        if is_circle_tutorial or is_dominant_motion:
            if not self._is_circle_of_fifths_mode:
                self._is_circle_of_fifths_mode = True
                self.isCircleOfFifthsModeChanged.emit(True)

        if is_circle_tutorial:
            # Initialize the step-by-step tutorial at step 1.
            # _get_circle_tutorial_prompt() will DIRECTLY push the visual state from Python
            # and return a voice-only narration prompt for the AI.
            self._circle_tutorial_step = 1
            prompt = self._get_circle_tutorial_prompt(1)

        elif is_dominant_motion:
            self._is_dominant_motion_mode = True
            self._dominant_motion_step = 0
            self._dominant_motion_hint_sent = False
            prompt = self._advance_dominant_motion(intro=True)

        else:
            prompt = f"""<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>
START A NEW LESSON. [INITIAL_LOAD]

{user_context}

{blocks_text}

INSTRUCTIONS:
1. You MUST call the `set_exercise` tool right now to assign the first exercise. Do NOT forget to call the tool.
2. Speak a brief welcome, AND explicitly explain how to perform the very first exercise so the student knows what to do.
3. Wait for me to report the student's performance before calling the tool again.
4. When they finish an exercise, I will send you a report. Decide the next step (advance, repeat, or simplify) and call `set_exercise` again.
5. When the user has completed enough reps (about 10-15) and demonstrated mastery, call `end_lesson`.
6. You MUST REMAIN COMPLETELY SILENT between exercises of the SAME type. Do NOT provide any micro-affirmations or commentary. Just call `set_exercise` immediately.
7. Only speak longer sentences when giving feedback on significant struggles, or ending.

Available exercise_type values: chord, pentascale, progression, listen, hands_together, sustain_pedal
Available chord_type_name values: Major, Minor, Diminished, Augmented, Sus2, Sus4, Major7, Minor7, Dominant7

Start the lesson now by calling set_exercise and speaking.
</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"""

        self.requestLessonStart.emit(prompt)
        QTimer.singleShot(60000, self._lesson_loading_timeout)

    def _get_circle_tutorial_prompt(self, step: int, user_context: str = "") -> str:
        # ── Step visual data (deterministic, applied from Python) ───────────
        step_visuals = {
            1: {"show_base": True, "show_major": False, "show_minor": False, "highlight_key": "", "revealed_keys": []},
            2: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "C", "revealed_keys": ["C"]},
            3: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "G", "revealed_keys": ["C", "G"]},
            4: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "D", "revealed_keys": ["C", "G", "D"]},
            5: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "F", "revealed_keys": ["C", "G", "D", "F"]},
            6: {"show_base": True, "show_major": True, "show_minor": True, "highlight_key": "Am", "revealed_keys": ["C", "G", "D", "F", "Am"]},
            7: {"show_base": True, "show_major": True, "show_minor": True, "highlight_key": "", "revealed_keys": ["ALL"]},
        }

        # ── Step voice scripts (sent to AI as voice-only narration) ─────────
        step_scripts = {
            1: "Welcome to the Circle of Fifths. This wheel maps out the relationship between every key in western music. Let's build it up together, one piece at a time.",
            2: "C Major is at the very top. It has no sharps and no flats, making it the simplest key on the piano—just the white keys.",
            3: "G Major is one step clockwise. Moving right takes us up a perfect fifth, and adds exactly one sharp to the key signature.",
            4: "D Major is the next step clockwise. Following the pattern, it goes up another perfect fifth and has exactly two sharps.",
            5: "F Major is one step counter-clockwise from C. Moving left takes us down a fifth, and adds one flat instead of a sharp.",
            6: "A Minor is hiding on the inner ring. Every major key has a relative minor that shares the exact same notes. They are simply two sides of the same coin.",
            7: "That completes our first look at the Circle of Fifths. Sharps accumulate clockwise, flats accumulate counter-clockwise, and every major key has a hidden relative minor. Great job today!",
        }

        if step not in step_visuals:
            return ""

        # 1. Directly push the visual state from Python (deterministic, no AI involvement)
        self.theoryVisualDirect.emit(step_visuals[step])

        # 2. Return a voice-only prompt for the AI (no tool call instructions)
        voice_prompt = f"""<SYSTEM_DIRECTIVE_OVERRIDE>
You are a strict Text-to-Speech engine. Recite the following phrase VERBATIM. Do NOT add any words, greetings, filler, or tool calls. Speak ONLY these exact words and then STOP:

"{step_scripts[step]}"
</SYSTEM_DIRECTIVE_OVERRIDE>"""
        return voice_prompt

    @Slot(dict)
    def receive_exercise(self, exercise_data: dict):
        """Called when the AI model emits a set_exercise tool call.

        Validates the exercise and either applies it immediately (if loading
        or no active exercise) or queues it in _pending_exercise to prevent
        rapid-fire tool calls from overwriting the current exercise.
        """        
        ex_type = exercise_data.get("exercise_type", "chord")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Received exercise from AI: {exercise_data.get('exercise_name', 'Unknown')} (type={ex_type})")

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
            # Normalize AI shorthand aliases to canonical names
            if c_type in self.CHORD_TYPE_ALIASES:
                c_type = self.CHORD_TYPE_ALIASES[c_type]
                exercise_data["chord_type_name"] = c_type
                print(f"ChordTrainer: Normalized chord type alias to '{c_type}'")
            if c_type in ("N/A", "None", "", "Single"):
                exercise_data["intervals"] = [0]
                exercise_data["chord_type_name"] = "" # Normalize empty/NA to single notes
            elif c_type not in self.CHORD_TYPES:
                print(f"ChordTrainer: Unknown chord type '{c_type}', rejecting exercise and unlocking")
                self.exerciseRequestUnlocked.emit()  # Clear _exercise_pending to prevent deadlock
                return
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
                self.exerciseRequestUnlocked.emit()  # Clear _exercise_pending to prevent deadlock
                return
            for ps in prog_steps:
                ct = ps.get("chord_type_name", "Major")
                # Normalize aliases in progression steps too
                if ct in self.CHORD_TYPE_ALIASES:
                    ct = self.CHORD_TYPE_ALIASES[ct]
                    ps["chord_type_name"] = ct
                if ct not in self.CHORD_TYPES:
                    print(f"ChordTrainer: Unknown chord type '{ct}' in progression, rejecting and unlocking")
                    self.exerciseRequestUnlocked.emit()  # Clear _exercise_pending to prevent deadlock
                    return
          # If this is the first exercise (loading state), apply immediately
        if self.isLoading:
            self._set_state(LessonState.USER_PLAYING)
            self._apply_exercise(exercise_data)
            return

        # We received the response, the UI no longer needs to wait/blur
        if self.isWaitingForAi:
            self._set_state(LessonState.USER_PLAYING) # Ensure active if recovering from something
            self._apply_exercise(exercise_data)
            return

        # If we weren't waiting for the AI (e.g. timeout recovery), ensure we are active now
        if not self.isActive:
            print("ChordTrainer: Exercise arrived while inactive (recovery). Setting active=True.")
            self._set_state(LessonState.USER_PLAYING)

        # If we already have an active exercise (with a target) and aren't waiting for the AI, 
        # queue this one for later to avoid interrupting the current rep.
        if self.isActive and self._target_chord_name != "":
            print(f"ChordTrainer: Queuing exercise '{exercise_data.get('exercise_name')}' (current: '{self._exercise_name}')")
            self._pending_exercise = exercise_data
            return

        # Otherwise apply immediately
        self._apply_exercise(exercise_data)

    def _lesson_loading_timeout(self):
        """Safety valve: if the AI hasn't sent set_exercise within 15 seconds, recover."""
        if self.isLoading:
            print("ChordTrainer: Lesson loading timeout — AI did not send exercise in 15s")
            self._loading_status_text = ""
            self._set_state(LessonState.IDLE)
            self.apiConnectivityChanged.emit(False)

    def _apply_exercise(self, exercise_data: dict):
        """Apply a validated exercise: update progress, blocks, and set up the target."""
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Applying exercise to UI: {exercise_data.get('exercise_name', 'Unknown')}")
        # Record the exercise intro
        self.db.record_exercise_intro(exercise_data.get("exercise_type", "chord"))

        # Increment progress
        self._lesson_progress += 1
        self._lesson_total = self._lesson_progress  # Grows as exercises arrive

        # Update current milestone context
        self._current_track = str(exercise_data.get("track", ""))
        self._current_milestone_id = str(exercise_data.get("milestone_id", ""))

        # Update exercise name
        self._exercise_name = str(exercise_data.get("exercise_name", self._exercise_name))

        # Incrementally update lesson blocks for the sidebar
        self._update_lesson_blocks(exercise_data)

        # Store current step data for performance tracking
        self._current_step_data = exercise_data.copy()

        # Apply the exercise
        self.lessonStateChanged.emit()
        self._apply_step(exercise_data)

    @Slot(str)
    def receive_lesson_end(self, feedback: str):
        """Called when the AI model emits an end_lesson tool call."""
        print(f"ChordTrainer: Lesson end tool received. AI Speaking: {self._ai_is_currently_speaking}")

        # If AI is speaking, don't show the completion screen yet.
        # It will be triggered by resume_lesson when speech finishes.
        if self._ai_is_currently_speaking:
            self._lesson_end_pending = True
            print("ChordTrainer: AI is still speaking final feedback. Deferring lesson end display.")
            return

        self._finalize_lesson_end()

    def _finalize_lesson_end(self):
        """Actually marks the lesson as complete and updates UI state."""
        print("ChordTrainer: Finalizing lesson completion.")
        self._is_lesson_complete = True
        self._set_state(LessonState.IDLE)
        self.activeChanged.emit(False)

        # Clear circle of fifths mode flag
        if self._is_circle_of_fifths_mode:
            self._is_circle_of_fifths_mode = False
            self.isCircleOfFifthsModeChanged.emit(False)

        if self.curriculum:
            self.curriculum.finish_session()

        self._target_chord_name = ""
        self._target_intervals.clear()
        self._target_pitches.clear()
        self._target_hands.clear()
        self._pedal_type = ""
        self._hold_tick_timer.stop()
        if self.metronome:
            self.metronome.stop()
        self.lessonStateChanged.emit()
        self.targetChordChanged.emit(self._target_chord_name)

    @Slot()
    def notify_visual_received(self):
        """Unlocks loading/wait states when a non-exercise tool (e.g. theory visual) arrives."""
        if self.isLoading:
            print("ChordTrainer: Visual tool received during loading. Clearing loading lock.")
            self._set_state(LessonState.USER_PLAYING)
        elif self.isWaitingForAi:
            print("ChordTrainer: Visual tool received during AI wait. Clearing wait lock.")
            self._set_state(LessonState.USER_PLAYING)

    def _update_lesson_blocks(self, exercise_data: dict):
        """Incrementally add to the lesson blocks sidebar as exercises arrive."""
        track = exercise_data.get("track", "")
        milestone_id = exercise_data.get("milestone_id", "")
        ex_type = exercise_data.get("exercise_type", "chord")

        group_title = ""
        if hasattr(self, 'curriculum') and self.curriculum and track and milestone_id:
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

    def _request_next_exercise(self, context: str = ""):
        """Send performance data to the AI model and request the next exercise."""
        if self.isWaitingForAi:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: IGNORING _request_next_exercise because a request is already in flight")
            return

        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Requesting NEXT exercise from AI...")
        
        # Build performance report from session stats
        stats_lines = []
        for chord, latencies in self._session_stats.items():
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                stats_lines.append(f"- {chord}: {len(latencies)} attempts, avg {avg_lat:.0f}ms")

        report = f"<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>Student completed exercise #{self._lesson_progress}."

        if self._current_step_data:
            last_name = self._current_step_data.get("exercise_name", "")
            last_type = self._current_step_data.get("exercise_type", "")
            report += f" Last: '{last_name}' (type={last_type})."

        # Include specific last-chord performance for the model
        if self._target_chord_name:
            last_latencies = self._session_stats.get(self._target_chord_name, [])
            if last_latencies:
                report += f" Last chord latency: {last_latencies[-1]:.0f}ms."
            report += f" Wrong notes this step: {self._wrong_notes_count}."

            # Update history
            if self._exercise_name not in self._exercise_history:
                 self._exercise_history.append(self._exercise_name)
                 if len(self._exercise_history) > 8:
                     self._exercise_history.pop(0)

        history_text = ", ".join(self._exercise_history)
        report += f"\nRecent exercise history (DO NOT REPEAT THESE): {history_text}."

        if context:
            report += f" {context}"

        if stats_lines:
            report += f"\nRecent performance:\n" + "\n".join(stats_lines[-5:])  # Last 5 items

        report += f"\n\nCRITICAL INSTRUCTION: If you assign another '{last_type}' exercise, you MUST BE COMPLETELY SILENT. Do NOT speak - just call set_exercise."
        report += " Provide a 1-3 word micro-affirmation ONLY every 5 reps to keep up energy. "
        report += " Only speak longer sentences for a DIFFERENT exercise type or if the student significantly struggled."
        report += "</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"

        # Set waiting flag so the incoming exercise is applied immediately instead of queued
        self._set_state(LessonState.AWAITING_EXERCISE)

        self.reportPerformance.emit(report)

    def _compute_lesson_blocks(self):
        """Build a stable block summary from the current playlist for the sidebar.

        Groups consecutive steps by Milestone Title or Type.
        Each block tracks its cumulative step range so the QML sidebar can
        determine which block is active based on lessonProgress.
        """
        blocks = []
        cumulative = 0
        for step in self._lesson_playlist:
            track = step.get("track", "")
            milestone_id = step.get("milestone_id", "")
            ex_type = step.get("exercise_type", "chord")

            group_title = ""
            if hasattr(self, 'curriculum') and self.curriculum and track and milestone_id:
                group_title = self.curriculum.get_milestone_title(track, milestone_id)
            if not group_title:
                group_title = f"{ex_type.capitalize()} Drills"

            # Group consecutive steps with the same aggregated title
            if blocks and blocks[-1]["name"] == group_title:
                blocks[-1]["stepCount"] += 1
                blocks[-1]["endStep"] = cumulative + 1
            else:
                blocks.append({
                    "track": track,
                    "name": group_title,
                    "type": ex_type,
                    "stepCount": 1,
                    "startStep": cumulative + 1,  # 1-indexed to match lessonProgress
                    "endStep": cumulative + 1,
                })
            cumulative += 1

        self._lesson_blocks = blocks

    @Slot()
    def begin_lesson(self):
        """Called from UI when user clicks Begin."""
        if not self._lesson_playlist or not self.isWaitingToBegin:
            return

        
        self._set_state(LessonState.USER_PLAYING)
        self.activeChanged.emit(self.isActive)
        self.lessonStateChanged.emit()
        self._next_chord()

    @Slot()
    def start_review_session(self):
        """Starts a mini-lesson focusing only on struggled items."""
        if not self._struggled_items:
            return

        print(f"ChordTrainer: Starting review session with {len(self._struggled_items)} items")

        # Build a playlist from struggled items
        review_playlist = []
        for item in self._struggled_items:
            # item["chord_data"] is the original AI-generated step
            step = item["chord_data"].copy()
            # Clean up metadata if needed
            step["exercise_name"] = f"Review: {step.get('exercise_name', 'Previous Task')}"
            step["spoken_instruction"] = f"Let's try {item['name']} again. Focus on accuracy."
            review_playlist.append(step)

        # Swap playlist and start
        self._lesson_playlist = review_playlist
        # Clear struggled items for the new review run so we can track them again
        self._struggled_items = []

        self._lesson_progress = 0
        self._lesson_total = len(self._lesson_playlist)
        self._is_lesson_mode = True
        self._is_lesson_complete = False
        self._set_state(LessonState.USER_PLAYING)
        self._compute_lesson_blocks()
        self.activeChanged.emit(True)
        self.lessonStateChanged.emit()
        self._next_chord()

    @Slot()
    def stop_session(self):
        if self.isActive or self.isWaitingToBegin:
            self._set_state(LessonState.IDLE)
            
                        
            self._set_state(LessonState.USER_PLAYING)
            self._require_key_release_before_eval = False
            if self.metronome:
                self.metronome.stop()
            self.activeChanged.emit(self.isActive)
            self.lessonStateChanged.emit()
            self._target_chord_name = ""
            self._target_intervals.clear()
            self._target_pitches.clear()
            self._target_hands.clear()
            self._pedal_type = ""
            self.targetChordChanged.emit(self._target_chord_name)
            self._hold_tick_timer.stop()
            self._is_holding = False
            self._pending_exercise = None
            self._consecutive_successes = 0
            self._consecutive_struggles = 0
            # Clear circle of fifths mode on manual stop
            if self._is_circle_of_fifths_mode:
                self._is_circle_of_fifths_mode = False
                self.isCircleOfFifthsModeChanged.emit(False)

    def get_resume_context(self) -> str:
        """Build a prompt for the AI to resume a lesson after reconnection."""
        lines = ["<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>RESUME LESSON after connection drop."]
        if hasattr(self, '_lesson_roadmap') and self._lesson_roadmap:
            lines.append("STILL ACTIVE SESSION ROADMAP (Plan):")
            lines.append(self._lesson_roadmap)
            lines.append("\n" + "-"*20 + "\n")

        lines.append(f"Current overall lesson progress: step #{self._lesson_progress}")
        lines.append(f"Last exercise reached: '{self._exercise_name}' (type={self._exercise_type})")

        if self._current_step_data:
            lines.append(f"Most recent exercise state data: {self._current_step_data}")

        # Include recent performance
        stats_lines = []
        for chord, latencies in list(self._session_stats.items())[-5:]:
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                stats_lines.append(f"- {chord}: {len(latencies)} attempts, avg {avg_lat:.0f}ms")
        if stats_lines:
            lines.append("Recent performance summary:\n" + "\n".join(stats_lines))

        lines.append("\nCRITICAL: You MUST follow the VARIETY RULE. Do not assign the same exercise twice in a row. Call set_exercise immediately for the next step.")
        lines.append("</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>")
        return "\n".join(lines)

    def _next_chord(self):
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: _next_chord called")
        if self._is_lesson_mode:
            # In single-model mode: apply queued exercise if one arrived while we were busy,
            # otherwise send performance data and wait for the model's next tool call.
            self._target_chord_name = ""
            self._target_intervals.clear()
            self._target_pitches.clear()
            self._target_hands.clear()

            if self._pending_exercise:
                exercise = self._pending_exercise
                self._pending_exercise = None
                 # Clear lock if we had a pending exercise ready
                print(f"ChordTrainer: Applying queued exercise: {exercise.get('exercise_name', '?')}")
                self._apply_exercise(exercise)
            else:
                self._request_next_exercise()
            return
        else:
            self._apply_random_step()

    def _apply_step(self, chord_data):
        self._required_hold_ms = int(chord_data.get("hold_ms", 0)) # type: ignore
        exercise_type = str(chord_data.get("exercise_type", "chord")) # type: ignore
        self._exercise_type = exercise_type
        self._current_hand = str(chord_data.get("hand", "right")) # type: ignore

        # Pause input evaluation until speech finishes in lesson mode.
        # We only force the pause if the AI is ACTUALLY currently speaking 
        # (e.g. Turn 1 speaking concept intro, then Turn 2 calling set_exercise).
        # If the AI turn finished before the tool call arrived, we don't pause.
        if self._is_lesson_mode and self._ai_is_currently_speaking:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: AI is speaking, pausing input (isPausedForSpeech=True) for {self._exercise_name}")
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

        root_name = self.ROOT_NOTES[root_idx]
        self._scale_name = f"{root_name} {scale_type} Pentascale"
        self._pentascale_sequence = sequence
        self._pentascale_index = 0

        # Reset common state
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

        self.lessonStateChanged.emit()
        self.targetChordChanged.emit(self._target_chord_name)
        print(f"ChordTrainer: Pentascale target: {self._scale_name} ({direction}), notes: {sequence}")

    def _setup_progression_target(self, chord_data):
        """Sets up a chord progression exercise: multiple chords played in sequence."""
        prog_steps = chord_data.get("progression_steps", []) # type: ignore
        if not prog_steps:
            # Fallback: treat as a regular chord step
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
        self.lessonStateChanged.emit()

        # Set up the first chord in the progression
        self._advance_progression_chord()

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
        if self._exercise_type != "listen" or self.isWaitingForAi or self.isPausedForSpeech:
            return

        is_correct = (quality.lower() == self._target_formula_text.lower())
        if is_correct:
            print(f"ChordTrainer: Ear Training CORRECT! {quality}")
            self._complete_chord()
        else:
            print(f"ChordTrainer: Ear Training WRONG. User picked {quality}, expected {self._target_formula_text}")
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting chordFailed (wrong answer)")
            self.chordFailed.emit()
            # Optionally replay the sound as feedback
            self.replay_preview()

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
        # Add inversion label if applicable
        inversion = getattr(self, '_current_inversion', 0)
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

        # Calculate the exact MIDI pitches for the staff visualizer
        self._target_pitches = [(base_pitch + interval) for interval in intervals]

        # Populate target hands: left if the exercise specifically calls for it,
        # otherwise default to right hand for normal chords (or the fallback).
        hand_tag = "left" if self._current_hand == "left" else "right"
        self._target_hands = [hand_tag] * len(self._target_pitches)

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
        if self._is_lesson_mode and (self.isWaitingForAi or self.isActive):
            if not self.isPausedForSpeech:
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: AI Audio started, pausing for speech (isPausedForSpeech=True)")
                self._set_state(LessonState.AI_SPEAKING)
                self.lessonStateChanged.emit()

    @Slot()
    def resume_lesson(self):
        """Called when AI finishes speaking. Applies pending exercise if queued,
        plays deferred listen preview, or resets paused state."""
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Coach speech finished, resuming lesson. Pending end: {self._lesson_end_pending}")
        self._ai_is_currently_speaking = False
        should_check_immediately = False

        if self._lesson_end_pending:
            self._lesson_end_pending = False
            self._finalize_lesson_end()
            return

        # If we are in the sequenced Circle of Fifths tutorial or Dominant Motion
        if self.isCircleOfFifthsMode:
            if getattr(self, '_is_dominant_motion_mode', False):
                # For Dominant Motion, immediately transition to USER_PLAYING and start timer
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Dominant Motion speech finished, awaiting user input.")
                self._set_state(LessonState.USER_PLAYING)
                self.lessonStateChanged.emit()
            elif hasattr(self, '_circle_tutorial_step'):
                if self._circle_tutorial_step == 7:
                    # Final step just finished speaking — end the lesson directly (no Continue button)
                    print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Circle sequence complete (step 7 finished). Finalizing lesson directly.")
                    self._is_circle_of_fifths_mode = False
                    self.isCircleOfFifthsModeChanged.emit(False)
                    self.receive_lesson_end("Completed Circle of Fifths introduction.")
                    self._circle_tutorial_step = 8
                elif 0 < self._circle_tutorial_step < 7:
                    print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Circle sequence paused at step {self._circle_tutorial_step}. Waiting for user continue.")
                    self._waiting_for_user_continue = True
                    self.waitingForUserContinueChanged.emit(True)
            return

        # For normal (non-circle) lessons, run general post-speech resume logic
        self._resume_after_speech()

    @Slot()
    def continueCircleTutorial(self):
        """Called by QML when the user clicks the Continue button during the tutorial."""
        if not getattr(self, '_waiting_for_user_continue', False):
            return
            
        self._waiting_for_user_continue = False
        self.waitingForUserContinueChanged.emit(False)
        
        if hasattr(self, '_circle_tutorial_step') and 0 < self._circle_tutorial_step <= 7:
            if self._circle_tutorial_step == 7:
                # Step 7 is the conclusion — after user clicks Continue, end the lesson directly
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Circle sequence complete. Finalizing lesson directly.")
                self._is_circle_of_fifths_mode = False
                self.isCircleOfFifthsModeChanged.emit(False)
                self.receive_lesson_end("Completed Circle of Fifths introduction.")
                self._circle_tutorial_step = 8
            else:
                self._circle_tutorial_step += 1
                prompt = self._get_circle_tutorial_prompt(self._circle_tutorial_step)
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Circle sequence advancing to step {self._circle_tutorial_step}")
                self.speakBrief.emit(prompt)
                
                # We delay the native MIDI chord playback by 1000ms so it sounds right as the visual wheel finishes spinning
                QTimer.singleShot(1000, lambda: self._play_circle_step_midi(self._circle_tutorial_step))

    def _play_circle_step_midi(self, step: int):
        pitches = []
        if step == 2:
            pitches = [60, 64, 67] # C Major
        elif step == 3:
            pitches = [67, 71, 74] # G Major
        elif step == 4:
            pitches = [62, 66, 69] # D Major
        elif step == 5:
            pitches = [65, 69, 72] # F Major
        elif step == 6:
            pitches = [69, 72, 76] # A Minor (relative minor of C)
            
        if pitches:
            print(f"ChordTrainer: Playing native MIDI trace for step {step}: pitches {pitches}")
            self.midiOutRequested.emit(pitches)

    # ── Dominant Motion Trainer (V→I) ───────────────────────────────────────

    def _advance_dominant_motion(self, intro: bool = False) -> str:
        """Set up the next V→I pair: circle visual, target chord, AI narration.
        Returns the voice prompt for the AI."""
        pair = self.DOMINANT_MOTION_PAIRS[self._dominant_motion_step]
        v_key = pair["v_key"]
        i_key = pair["i_key"]
        i_root = pair["i_root"]
        shared = pair["shared"]

        print(f"ChordTrainer: Dominant Motion step {self._dominant_motion_step + 1}/{len(self.DOMINANT_MOTION_PAIRS)}: {v_key}→{i_key}")

        # Reset hint state for this step
        self._dominant_motion_hint_sent = False

        # 1. Push circle visual: show all keys, highlight V, arrow V→I
        visual_state = {
            "show_base": True,
            "show_major": True,
            "show_minor": False,
            "highlight_key": v_key,
            "revealed_keys": ["ALL"],
            "highlighted_chords": [v_key],
            "arrows": [{"from": v_key, "to": i_key, "color": "#4CAF50"}],
        }
        self.theoryVisualDirect.emit(visual_state)

        # 2. Update lesson progress
        self._lesson_progress = self._dominant_motion_step + 1
        self._lesson_total = len(self.DOMINANT_MOTION_PAIRS)

        # 3. Set the target chord to the I chord (Major triad)
        self._exercise_type = "chord"
        self._exercise_name = f"Resolve {v_key} → {i_key}"
        self._current_hand = "right"
        self._required_hold_ms = 0
        self._current_inversion = 0
        self._setup_target(i_root, "Major", {0, 4, 7}, 4)

        # 4. Play the V chord as a MIDI preview so the user hears the "tension"
        v_root_pitch = 60 + pair["v_root"]  # octave 4
        v_pitches = [v_root_pitch, v_root_pitch + 4, v_root_pitch + 7]
        self.midiOutRequested.emit(v_pitches)

        # Timer is started later in resume_lesson when AI speech finishes

        # 6. Build voice prompt
        if intro:
            self.db.record_dominant_motion_play()
            play_count = self.db.get_dominant_motion_play_count()
            
            attempts = 0
            successes = 0
            if self.curriculum:
                for ms in self.db.get_curriculum_state("theory"):
                    if ms["milestone_id"] == "dominant_motion":
                        attempts = ms.get("attempts", 0)
                        successes = ms.get("successes", 0)
                        break
            
            accuracy = (successes / attempts * 100) if attempts > 0 else 0.0

            voice_prompt = f"""<SYSTEM_DIRECTIVE_OVERRIDE>
Generate a brief, engaging voice introduction to the Dominant Motion (V→I) exercise.
Context:
- The user has played this specific drill {play_count} times before.
- Their historical success rate on this drill is {accuracy:.0f}% ({successes}/{attempts} attempts).

Instructions:
1. If this is their 1st or 2nd time playing, explicitly explain how to determine the answer: "Look at the Circle of Fifths. To find the resolution, move one step counter-clockwise." Mention that V→I is the strongest pull in Western music (tension and release).
2. If they've played it many times, skip the basic mechanical rules and just offer a quick encouraging word based on their accuracy (e.g. if accuracy is low, "Let's work on recognizing that resolution", if high, "You're mastering this, let's keep it going").
3. Keep it conversational and brief.
4. Always end your phrase with EXACTLY: "Let's start: resolve {v_key} Major to its tonic."
5. Do NOT use tool calls, do NOT output markdown, do NOT output emojis. Generate ONLY spoken text.
</SYSTEM_DIRECTIVE_OVERRIDE>"""
            return voice_prompt
        else:
            scripts = [
                f"Now resolve {v_key} Major.",
                f"{v_key} Major. Where does it want to go?",
                f"Here's {v_key}. Find the resolution.",
                f"{v_key} to... you tell me.",
                f"Resolve {v_key}.",
            ]
            import random as _rng
            script = _rng.choice(scripts)

            voice_prompt = f"""<SYSTEM_DIRECTIVE_OVERRIDE>
You are a strict Text-to-Speech engine. Recite the following phrase VERBATIM. Do NOT add any words, greetings, filler, or tool calls. Speak ONLY these exact words and then STOP:

"{script}"
</SYSTEM_DIRECTIVE_OVERRIDE>"""
            return voice_prompt

    def _advance_dominant_motion_next(self):
        """Called after key release to advance to the next V→I pair."""
        self._waiting_for_release = False
        prompt = self._advance_dominant_motion()
        self.speakBrief.emit(prompt)

    def _dominant_motion_hint(self, wrong_pitches: list | None = None):
        """Show a hint: highlight the shared note and send AI voice tip."""
        if self._dominant_motion_hint_sent:
            return
        self._dominant_motion_hint_sent = True

        pair = self.DOMINANT_MOTION_PAIRS[self._dominant_motion_step]
        v_key = pair["v_key"]
        i_key = pair["i_key"]
        shared = pair["shared"]

        print(f"ChordTrainer: Dominant Motion hint — shared note {shared} between {v_key} and {i_key}")

        # Update visual: add the I key as a second highlight + keep arrow
        visual_state = {
            "show_base": True,
            "show_major": True,
            "show_minor": False,
            "highlight_key": i_key,
            "revealed_keys": ["ALL"],
            "highlighted_chords": [v_key, i_key],
            "arrows": [{"from": v_key, "to": i_key, "color": "#4CAF50"}],
        }
        self.theoryVisualDirect.emit(visual_state)

        # Play the I chord as a hint
        i_root_pitch = 60 + pair["i_root"]
        i_pitches = [i_root_pitch, i_root_pitch + 4, i_root_pitch + 7]
        self.midiOutRequested.emit(i_pitches)

        if wrong_pitches:
            # Generate AI Analysis for the specific mistake
            played_names = [self.ROOT_NOTES[p % 12] for p in wrong_pitches]
            hint_prompt = f"""<SYSTEM_DIRECTIVE_OVERRIDE>
The user was asked to resolve {v_key} Major to {i_key} Major.
However, they played these notes instead: {', '.join(played_names)}.

Analyze their mistake gently in one conversational sentence (e.g., "You played a D minor instead of a C Major", or "That was close, but you played an F# instead of G").
Then, tell them the correct answer is {i_key} Major, and mention that '{shared}' is the shared note between them to help them find it.
Keep the entire response under 3 sentences. Generate ONLY spoken text. Do NOT use tool calls, markdown, or emojis.
</SYSTEM_DIRECTIVE_OVERRIDE>"""
        else:
            # Generic hesitation hint
            hint_script = f"The answer is {i_key} Major. {shared} is the note they share. Try playing {i_key} Major now."
            hint_prompt = f"""<SYSTEM_DIRECTIVE_OVERRIDE>
You are a strict Text-to-Speech engine. Recite the following phrase VERBATIM. Do NOT add any words, greetings, filler, or tool calls. Speak ONLY these exact words and then STOP:

"{hint_script}"
</SYSTEM_DIRECTIVE_OVERRIDE>"""
            
        self.speakBrief.emit(hint_prompt)

    def _resume_after_speech(self):
        """General post-speech resume logic for normal (non-circle) lessons."""
        should_check_immediately = False

        # Safety fallback: If the AI spoke its feedback but dropped the tool call, unlock the system so the user can continue
        if self.isWaitingForAi:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: AI finished turn but no exercise received. Unlocking request state and clearing blur.")
            
            self._set_state(LessonState.USER_PLAYING)  # Clear blur if turn is done by moving state away from AWAITING_EXERCISE
            self.exerciseRequestUnlocked.emit()
            # Actively nudge the AI to send the tool call it forgot
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Sending nudge prompt to request set_exercise.")
            self.speakBrief.emit(
                "<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"
                "You spoke but did not call a tool. "
                "Please call set_exercise for the next exercise, or end_lesson if the session is complete. "
                "Do NOT speak — just call the tool."
                "</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"
            )

        if self.isPausedForSpeech:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Unpausing speech (isPausedForSpeech=False)")
            self._set_state(LessonState.USER_PLAYING)
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting lessonStateChanged")
            self.lessonStateChanged.emit()
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Input unlocked.")
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting inputReady")
            self.inputReady.emit()
            # Defer _check_input until metronome and pending exercises are handled
            should_check_immediately = not self._require_key_release_before_eval

        # Play deferred listen preview now that the coach is done talking
        if self._listen_preview_pending:
            self._listen_preview_pending = False
            if self._target_pitches:
                print(f"ChordTrainer: Coach done, playing deferred MIDI preview: {self._target_pitches}")
                self._listen_preview_pending_midi = self._target_pitches # Temporarily store for play_midi_preview
                self._play_midi_preview(self._target_pitches)

        # Start deferred metronome now that the coach is done talking
        if self.metronome and self.metronome.has_deferred:
            self.metronome.flush_deferred()
            # If metronome is starting, skip immediate input evaluation to prevent "pre-hits"
            should_check_immediately = False

        # If an exercise arrived while the AI was speaking AND the student
        # isn't currently working on one, apply it now.
        if self._pending_exercise and self._is_lesson_mode and not self._target_chord_name:
            exercise = self._pending_exercise
            self._pending_exercise = None
            print(f"ChordTrainer: Applying queued exercise: {exercise.get('exercise_name', '?')}")
            self._apply_exercise(exercise)
            should_check_immediately = False # Apply exercise will handle its own input check

        # Finally, perform immediate evaluation if still appropriate
        if should_check_immediately:
            print("ChordTrainer: Performing deferred immediate input evaluation.")
            self._check_input()
        elif self._require_key_release_before_eval:
             print("ChordTrainer: Skipping immediate evaluation because key release lock is active.")

        # Failsafe: If the AI finished speaking but forgot to call set_exercise, 
        # or it hasn't arrived yet, nudge it.
        if self._is_lesson_mode and not self._is_lesson_complete and not self.isCircleOfFifthsMode and (self.isLoading or not self._target_chord_name):
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Coach finished speaking but no exercise is active. Arming 3s failsafe timer.")
            QTimer.singleShot(3000, self._check_failsafe)

    def _check_failsafe(self):
        """Called 3 seconds after audio completes. If no chord is active, the tool call never arrived or was rejected."""
        if self._is_lesson_mode and not self._is_lesson_complete and not self._target_chord_name:
            if self.isLoading:
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Failsafe timer popped (Initial Load)! Re-prompting AI for missing set_exercise.")
                self.requestLessonStart.emit("[System: You forgot to call the set_exercise tool. Please call it now to start the session.]")
            else:
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Failsafe timer popped (Mid-Lesson)! Nudging AI for missing tool call.")
                # Force the pause flag to False so the nudge can actually be "heard" by the Coordinator dispatch
                self._set_state(LessonState.USER_PLAYING)
                self.lessonStateChanged.emit()
                self.speakBrief.emit(
                    "<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"
                    "The student finished their turn but you did not call a tool for the next step. "
                    "Please call set_exercise now."
                    "</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"
                )

    def _advance_progression_chord(self):
        """Sets up the current chord within a progression sequence."""
        if self._progression_index >= len(self._progression_steps):
            # Progression complete
            return

        step = self._progression_steps[self._progression_index]
        root_idx = step["root_idx"]
        chord_type_name = step["chord_type_name"]
        intervals = step["intervals"]
        octave = step["octave"]
        numeral = step["numeral"]

        root_name = self.ROOT_NOTES[root_idx]
        self._target_chord_name = f"{root_name} {chord_type_name} ({numeral})" if numeral else f"{root_name} {chord_type_name}"
        self._target_chord_type = chord_type_name

        # Clamp octave based on current hand assignment
        if self._current_hand == "right":
            octave = max(4, min(5, octave))
        elif self._current_hand == "left":
            octave = max(2, min(3, octave))
        base_pitch = (octave + 1) * 12 + root_idx
        self._target_pitches = [(base_pitch + interval) for interval in intervals]

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
        self._hold_tick_timer.stop()
        self._prompt_time = time.time()
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False

        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._target_chord_name})")
        self.targetChordChanged.emit(self._target_chord_name)
        print(f"ChordTrainer: Progression chord {self._progression_index + 1}/{len(self._progression_steps)}: {self._target_chord_name}")
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting inputReady")
        self.inputReady.emit()
        self._check_input()

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

        if is_on:
            self._active_pitches.add(pitch)

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
                if self._is_dominant_motion_mode:
                    if getattr(self, '_dominant_motion_complete', False):
                        self._dominant_motion_complete = False
                        self._is_dominant_motion_mode = False
                        self._is_circle_of_fifths_mode = False
                        self.isCircleOfFifthsModeChanged.emit(False)
                        self.receive_lesson_end("Completed Dominant Motion (V→I) exercise.")
                    elif getattr(self, '_wrong_chord_needs_hint', False):
                        self._wrong_chord_needs_hint = False
                        self._dominant_motion_hint(wrong_pitches=self._wrong_chord_pitches_snapshot)
                    else:
                        QTimer.singleShot(700, lambda: self._advance_dominant_motion_next())
                elif self._exercise_type == "pentascale":
                    if self._pentascale_index < len(self._pentascale_sequence):
                        # Still in the pentascale sequence — just continue, don't call _next_chord
                        pass
                    else:
                        QTimer.singleShot(700, self._next_chord)
                elif self._exercise_type == "progression" and self._progression_index < len(self._progression_steps):
                    # Advance to next chord in progression, adding a short pause so user can reset hands
                    QTimer.singleShot(700, self._advance_progression_chord)
                else:
                    QTimer.singleShot(700, self._next_chord)
            return

        self._check_input()

    def _check_input(self):
        """Routes input validation based on exercise type."""
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
                self._prompt_time = time.time()  # Reset timing for next note
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._target_chord_name})")
        self.targetChordChanged.emit(self._target_chord_name)

    def _check_chord(self):
        if not self._target_pitches:
            return

        # Do not evaluate if we are explicitly waiting for a full key release
        if getattr(self, '_waiting_for_release', False):
            return

        active_set = set(self._active_pitches)
        target_set = set(self._target_pitches)

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
                    if self._is_dominant_motion_mode:
                        if not self._wrong_chord_timer.isActive():
                            self._wrong_chord_timer.start(100) # Fast trigger for DM
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
            if self._is_dominant_motion_mode:
                is_valid_count = len(self._active_pitches) > 0

            if is_valid_count and active_intervals != self._target_intervals:
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting chordFailed (wrong notes)")
                self.chordFailed.emit()
                latency_ms = (time.time() - self._prompt_time) * 1000.0
                self.db.record_chord_attempt(self._target_chord_name, False, latency_ms, 
                                           self._wrong_notes_count, False)
                if self.curriculum:
                    self.curriculum.complete_exercise(self._target_chord_name, False, 
                                                     self._current_track, self._current_milestone_id)

                # Dominant Motion: wrong chord → trigger hint
                if self._is_dominant_motion_mode and not getattr(self, '_dominant_motion_hint_sent', False):
                    self._dominant_motion_hesitation_timer.stop() # Stop hesitation timer
                    self._wrong_chord_needs_hint = True
                    self._wrong_chord_pitches_snapshot = list(self._active_pitches)
                    self._waiting_for_release = True

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
            self._consecutive_successes = 0
            self._consecutive_struggles += 1
        else:
            self._consecutive_struggles = 0
            self._consecutive_successes += 1

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

        # Handle dominant motion advancement (takes priority over normal lesson flow)
        if self._is_dominant_motion_mode:
            self._dominant_motion_hesitation_timer.stop()
            self._dominant_motion_step += 1
            if self._dominant_motion_step >= len(self.DOMINANT_MOTION_PAIRS):
                # All pairs complete
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Dominant Motion exercise complete. Waiting for release.")
                self._dominant_motion_complete = True
                self._waiting_for_release = True
            else:
                # Wait for release then advance to next pair
                self._waiting_for_release = True
            return

        # Handle progression sub-step advancement
        if self._exercise_type == "progression":
            self._progression_index += 1
            if self._progression_index < len(self._progression_steps):
                # More chords in this progression — wait for release then advance
                print(f"ChordTrainer: Waiting for release before next progression chord...")
                self._waiting_for_release = True
                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Emitting targetChordChanged ({self._target_chord_name})")
                self.targetChordChanged.emit(self._target_chord_name)
                return
            # else: progression complete, fall through to _next_chord

        if self._exercise_type == "listen":
            # For listening quizzes, the user answers via UI, not keys. Pause briefly then move on.
            QTimer.singleShot(700, self._next_chord)
        else:
            if len(self._active_pitches) == 0:
                print("ChordTrainer: All keys already released. Advancing.")
                self._waiting_for_release = False
                QTimer.singleShot(700, self._next_chord)
            else:
                print("ChordTrainer: Waiting for user to release all keys...")
                self._waiting_for_release = True

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
        
        bpm = int(chord_data.get("bpm", 100))
        if self.metronome:
            if self._ai_is_currently_speaking:
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

