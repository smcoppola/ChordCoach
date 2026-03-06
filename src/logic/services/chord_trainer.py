import os
import time
import random
import json
from typing import Set, List, Dict, Tuple
from datetime import datetime
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt # type: ignore

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
    
    # Single-model architecture signals
    requestLessonStart = Signal(str)    # Emitted with the full lesson prompt for the AI coach
    reportPerformance = Signal(str)     # Emitted after each exercise with performance data
    
    def __init__(self, db_manager, curriculum_service=None, settings_manager=None):
        super().__init__()
        self.db = db_manager
        self.curriculum = curriculum_service
        self.settings = settings_manager
        self._is_active = False
        self._current_track = ""
        self._current_milestone_id = ""
        self._target_chord_name = ""
        self._target_chord_type = ""
        self._target_formula_text = ""
        self._target_intervals: Set[int] = set()
        self._target_pitches: List[int] = []
        self._target_hands: List[str] = []  # "left" or "right" for each target pitch
        self._pedal_type: str = "" # "direct", "legato", or ""
        
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
        self._is_waiting_to_begin = False
        self._is_loading = False
        self._loading_status_text = ""
        self._is_paused_for_speech = False
        self._waiting_for_ai = False
        self._pending_exercise = None  # Single-slot queue to prevent rapid-fire overwrites
        self._listen_preview_pending = False  # Deferred MIDI preview for listen exercises
        self._metronome_pending = None  # Deferred metronome start {bpm, interval_ms}
        self._ignore_midi_until = 0.0   # Ignore MIDI input while previewing
        self._session_stats: Dict[str, List[float]] = {}
        self._estimated_gen_ms = 5000.0
        
        # Inter-exercise commentary streak tracking
        self._consecutive_successes = 0
        self._consecutive_struggles = 0
        
        # Pentascale State
        self._pentascale_sequence: List[int] = []  # Exact MIDI pitches for the 5-note sequence
        self._pentascale_index = 0
        self._pentascale_beat_count = 0
        self._metronome_timer = QTimer()
        self._metronome_timer.setTimerType(Qt.PreciseTimer)
        self._metronome_timer.timeout.connect(self._play_metronome_click)
        self._scale_name = ""
        
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
        
        # Pentascale patterns: intervals from root for each scale type
        self.PENTASCALE_PATTERNS = {
            "Major": [0, 2, 4, 5, 7],      # W-W-H-W (C-D-E-F-G)
            "Minor": [0, 2, 3, 5, 7],      # W-H-W-W (C-D-Eb-F-G)
        }
        
        self.ROOT_NOTES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

    @Property(bool, notify=activeChanged)
    def isActive(self) -> bool:
        return self._is_active

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
        return self._is_paused_for_speech
        
    @Property(int, notify=lessonStateChanged)
    def lessonProgress(self) -> int:
        return self._lesson_progress
        
    @Property(int, notify=lessonStateChanged)
    def lessonTotal(self) -> int:
        return self._lesson_total

    @Property(bool, notify=lessonStateChanged)
    def isWaitingForAi(self) -> bool:
        return self._waiting_for_ai

    @Property("QVariantList", notify=lessonStateChanged)
    def lessonBlocks(self) -> list:
        return self._lesson_blocks
        
    @Property(bool, notify=lessonStateChanged)
    def isLessonComplete(self) -> bool:
        return self._is_lesson_complete
        
    @Property(bool, notify=lessonStateChanged)
    def isWaitingToBegin(self) -> bool:
        return self._is_waiting_to_begin
        
    @Property(str, notify=lessonStateChanged)
    def currentHand(self):
        return self._current_hand

    @Property(bool, notify=lessonStateChanged)
    def isLessonMode(self) -> bool:
        return self._is_lesson_mode
        
    @Property(float, notify=lessonStateChanged)
    def holdProgress(self) -> float:
        return self._hold_progress

    @Property(int, notify=lessonStateChanged)
    def requiredHoldMs(self) -> int:
        return self._required_hold_ms
        
    @Property(bool, notify=lessonStateChanged)
    def isLoading(self) -> bool:
        return self._is_loading

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
    @Property("QVariantList", notify=lessonStateChanged)
    def struggledItems(self):
        """List of items where user performance was below threshold."""
        return self._struggled_items

    @Property(int, notify=targetChordChanged)
    def currentNoteIndex(self) -> int:
        return self._pentascale_index
        
    @Property(int, notify=metronomeTick)
    def pentascaleBeatCount(self) -> int:
        return self._pentascale_beat_count

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
        
        if not self._is_active:
            self._is_active = True
            self.activeChanged.emit(self._is_active)
            
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
        if self._is_loading:
            return
            
        self._is_lesson_mode = True
        self._is_lesson_complete = False
        self._lesson_progress = 0
        self._lesson_total = 0
        self._is_loading = True
        self._waiting_for_ai = False
        self._lesson_playlist = []
        self._lesson_blocks = []
        
        self._estimated_gen_ms = 3000.0  # Much faster now — single round-trip
        self._loading_status_text = "PREPARING LESSON PLAN..."
        self.loadingStatusChanged.emit()
        self.lessonStateChanged.emit()
        
        if self._is_active:
            self._is_active = False
            self.activeChanged.emit(self._is_active)
            
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

        prompt = f"""[System Note]: START A NEW LESSON.

{user_context}

{blocks_text}

INSTRUCTIONS:
1. You MUST call the `set_exercise` tool right now to assign the first exercise. Do NOT forget to call the tool.
2. Speak a brief welcome and session overview, AND explicitly explain how to perform the very first exercise you are assigning so the student knows what to do.
3. Wait for me to report the student's performance before calling the tool again.
4. When they finish an exercise, I will send you a report. Decide the next step (advance, repeat, or simplify) and call `set_exercise` again.
5. When the session is complete, call `end_lesson`.
6. Between exercises of the SAME type, provide ONLY a 1-3 word micro-affirmation (e.g. "Good", "Keep going", "Nice") and immediately call `set_exercise`. Do NOT give long explanations between reps.
7. Only speak longer sentences when introducing a NEW exercise type, giving feedback on struggles, or ending.

VOICE GUIDANCE RULES:
- NEVER reference raw numbers like BPM, milliseconds, or technical parameters.
- Instead of "play at 60 BPM", say "play slowly and steadily" or "keep a relaxed pace".
- Focus on WHAT the student should do, not technical specifications.
- Briefly explain the "why" or context when introducing a new exercise type (e.g., "This pentascale shape is the foundation for pop songs").
- The student sees the chord/notes on screen — don't describe which keys to press.
- Keep exercise transitions fast. Call set_exercise immediately, don't narrate between steps.

CRITICAL RULES FOR EXERCISE GENERATION:
- You are the conductor. Assign exercises STRICTLY ONE AT A TIME.
- DO NOT use parallel function calling to dispense the entire block at once.
- Always wait for me to report the student's performance before giving the next step.
- For 'exercise_name', provide a descriptive name for the specific drill you are giving (e.g., "C Major Root Position"), NOT the name of the entire lesson block.

BEGINNER SAFETY RULES:
- DO NOT use 7th, 9th, or extended chords unless in target_chords.
- DO NOT use complex rhythms for beginners.
- For 'listen' exercises, ONLY use Major and Minor.
- ALWAYS prioritize the 'target_chords' list.

Available exercise_type values: chord, pentascale, progression, listen, hands_together, sustain_pedal
Available chord_type_name values: Major, Minor, Diminished, Augmented, Sus2, Sus4, Major7, Minor7, Dominant7

Start the lesson now by calling set_exercise and speaking."""
        
        self.requestLessonStart.emit(prompt)

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
            if c_type not in self.CHORD_TYPES:
                print(f"ChordTrainer: Unknown chord type '{c_type}', skipping")
                return
            exercise_data["intervals"] = self.CHORD_TYPES[c_type]
        
        # Validate progression steps
        if ex_type == "progression":
            prog_steps = exercise_data.get("progression_steps", [])
            if not prog_steps:
                return
            for ps in prog_steps:
                ct = ps.get("chord_type_name", "Major")
                if ct not in self.CHORD_TYPES:
                    return
        
        # If this is the first exercise (loading state), apply immediately
        if self._is_loading:
            self._is_loading = False
            self._is_active = True
            self._waiting_for_ai = False
            self.activeChanged.emit(True)
            self._apply_exercise(exercise_data)
            return
        
        # We received the response, the UI no longer needs to wait/blur
        if self._waiting_for_ai:
            self._waiting_for_ai = False
            self.lessonStateChanged.emit()

        # If we already have an active exercise and aren't waiting for the AI, queue this one for later
        if self._is_active:
            print(f"ChordTrainer: Queuing exercise '{exercise_data.get('exercise_name')}' (current: '{self._exercise_name}')")
            self._pending_exercise = exercise_data
            return
        
        # Otherwise apply immediately
        self._apply_exercise(exercise_data)
    
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
        print(f"ChordTrainer: Lesson ended by AI. Feedback: {feedback[:100]}")
        
        self._is_lesson_complete = True
        self._is_active = False
        self.activeChanged.emit(False)
        
        if self.curriculum:
            self.curriculum.finish_session()
        
        self._target_chord_name = ""
        self._target_intervals.clear()
        self._target_pitches.clear()
        self._target_hands.clear()
        self._pedal_type = ""
        self._hold_tick_timer.stop()
        self._metronome_timer.stop()
        self.lessonStateChanged.emit()
        self.targetChordChanged.emit(self._target_chord_name)
    
    def _update_lesson_blocks(self, exercise_data: dict):
        """Incrementally add to the lesson blocks sidebar as exercises arrive."""
        name = exercise_data.get("exercise_name", "Exercise")
        track = exercise_data.get("track", "")
        ex_type = exercise_data.get("exercise_type", "chord")
        
        if self._lesson_blocks and self._lesson_blocks[-1]["name"] == name:
            # Extend existing block
            self._lesson_blocks[-1]["stepCount"] += 1
            self._lesson_blocks[-1]["endStep"] = self._lesson_progress
        else:
            # New block
            self._lesson_blocks.append({
                "track": track,
                "name": name,
                "type": ex_type,
                "stepCount": 1,
                "startStep": self._lesson_progress,
                "endStep": self._lesson_progress,
            })
    
    def _request_next_exercise(self, context: str = ""):
        """Send performance data to the AI model and request the next exercise."""
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Requesting NEXT exercise from AI...")
        # Build performance report from session stats
        stats_lines = []
        for chord, latencies in self._session_stats.items():
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                stats_lines.append(f"- {chord}: {len(latencies)} attempts, avg {avg_lat:.0f}ms")
        
        report = f"[System Note]: Student completed exercise #{self._lesson_progress}."
        
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
        
        if context:
            report += f" {context}"
        
        if stats_lines:
            report += f"\nRecent performance:\n" + "\n".join(stats_lines[-5:])  # Last 5 items
        
        report += "\n\nCRITICAL INSTRUCTION: Call set_exercise EXACTLY ONCE for the next step, or end_lesson if complete."
        report += " NEVER call set_exercise multiple times in the same response. Just give me one exercise and WAIT."
        report += " If the exercise type is the same as previous, you may provide a 1-3 word micro-affirmation, but do NOT give long explanations. Only speak longer sentences for a NEW exercise type or if the student struggled."
        
        # Set waiting flag so the incoming exercise is applied immediately instead of queued
        self._waiting_for_ai = True
        
        self.reportPerformance.emit(report)

    @Slot()
    def activate_lesson_plan(self):
        """Legacy method — no longer needed in single-model flow.
        Kept as a no-op for backward compatibility."""
        pass

    def _compute_lesson_blocks(self):
        """Build a stable block summary from the current playlist for the sidebar.
        
        Groups consecutive steps with the same exercise_name into blocks.
        Each block tracks its cumulative step range so the QML sidebar can
        determine which block is active based on lessonProgress.
        """
        blocks = []
        cumulative = 0
        for step in self._lesson_playlist:
            name = step.get("exercise_name", "Exercise")
            track = step.get("track", "")
            ex_type = step.get("exercise_type", "chord")
            
            # Group consecutive steps with the same exercise_name
            if blocks and blocks[-1]["name"] == name:
                blocks[-1]["stepCount"] += 1
                blocks[-1]["endStep"] = cumulative + 1
            else:
                blocks.append({
                    "track": track,
                    "name": name,
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
        if not self._lesson_playlist or not self._is_waiting_to_begin:
            return
            
        self._is_waiting_to_begin = False
        self._is_active = True
        self.activeChanged.emit(self._is_active)
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
        self._is_active = True
        self._compute_lesson_blocks()
        self.activeChanged.emit(True)
        self.lessonStateChanged.emit()
        self._next_chord()

    @Slot()
    def stop_session(self):
        if self._is_active or self._is_waiting_to_begin:
            self._is_active = False
            self._is_waiting_to_begin = False
            self._waiting_for_ai = False
            self._is_paused_for_speech = False
            self._metronome_timer.stop()
            self.activeChanged.emit(self._is_active)
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

    def get_resume_context(self) -> str:
        """Build a prompt for the AI to resume a lesson after reconnection."""
        lines = ["[System Note]: RESUME LESSON after connection drop."]
        lines.append(f"Current exercise #{self._lesson_progress}: '{self._exercise_name}' (type={self._exercise_type})")
        
        if self._current_step_data:
            lines.append(f"Last exercise data: {self._current_step_data}")
        
        # Include recent performance
        stats_lines = []
        for chord, latencies in list(self._session_stats.items())[-5:]:
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                stats_lines.append(f"- {chord}: {len(latencies)} attempts, avg {avg_lat:.0f}ms")
        if stats_lines:
            lines.append("Recent performance:\n" + "\n".join(stats_lines))
        
        lines.append("\nCall set_exercise immediately for the next step. You may provide a 1-3 word micro-affirmation (e.g. 'Good', 'Again'), but do NOT give long explanations.")
        return "\n".join(lines)

    def _next_chord(self):
        if self._is_lesson_mode:
            # In single-model mode: apply queued exercise if one arrived while we were busy,
            # otherwise send performance data and wait for the model's next tool call.
            if self._pending_exercise:
                exercise = self._pending_exercise
                self._pending_exercise = None
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
        else:
            # Original chord behavior
            root_idx = chord_data.get("root_idx", 0)
            chord_type_name = chord_data.get("chord_type_name", "Major")
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
        self._metronome_start_time = 0.0 # Track precise start for timing feedback
        self._pentascale_bpm = 0
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False
        
        # Determine if we should optionally use the metronome
        bpm = chord_data.get("bpm", 0)  # Defaults to 0 (free-play)
        if bpm > 0:
            interval_ms = int(60000 / bpm)
            self._pentascale_bpm = bpm
            self._pentascale_beat_count = -4  # 4-beat lead in (-4, -3, -2, -1)
            # Defer metronome if coach is still speaking (first exercise)
            if self._is_lesson_mode and self._lesson_progress <= 1:
                print(f"ChordTrainer: Deferring metronome start ({bpm} BPM) until coach finishes")
                self._metronome_pending = {"bpm": bpm, "interval_ms": interval_ms}
            else:
                self._metronome_start_time = time.time() + (interval_ms / 1000.0 * 4) # Time when beat 0 will hit
                self._metronome_timer.start(interval_ms)
                print(f"ChordTrainer: Started pentascale metronome at {bpm} BPM")
        else:
            self._metronome_timer.stop()
            self._pentascale_bpm = 0
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
        chord_type_name = str(chord_data.get("chord_type_name", "Major"))
        target_quality = str(chord_data.get("target_quality", chord_type_name))
        
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
        self._setup_target(root_idx, chord_type_name, intervals, octave)
        
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
        intervals = self.CHORD_TYPES.get(chord_type_name, {0, 4, 7})
        octave = int(chord_data.get("octave", 4))
        
        self._pedal_type = str(chord_data.get("pedal_type", "direct"))
        self._pedal_satisfied = False
        
        self._setup_target(root_idx, chord_type_name, intervals, octave)
        self._target_chord_type = "Sustain Pedal"
        # We don't need UI text for pedal type since standard notation will be used,
        # but keep it in formula text for debugging or fallback if desired.
        self._target_formula_text = f"Pedal: {self._pedal_type.capitalize()}"
        self.targetChordChanged.emit(self._target_chord_name)

    @Slot(bool)
    def handle_pedal_event(self, is_down: bool):
        """Called by AppState when a CC64 sustain pedal event occurs."""
        if not self._is_active or self._is_lesson_complete:
            return
            
        if self._exercise_type == "sustain_pedal" and not self._pedal_satisfied:
            if self._pedal_type == "direct":
                # Pedal should be pressed around the same time as the chord
                if is_down and self._is_holding:
                    pedal_timing = (time.time() * 1000.0) - self._hold_start_time
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
        if self._exercise_type != "listen":
            return
            
        is_correct = (quality.lower() == self._target_formula_text.lower())
        if is_correct:
            print(f"ChordTrainer: Ear Training CORRECT! {quality}")
            self._complete_chord()
        else:
            print(f"ChordTrainer: Ear Training WRONG. User picked {quality}, expected {self._target_formula_text}")
            self.chordFailed.emit()
            # Optionally replay the sound as feedback
            self.replay_preview()

    def _setup_target(self, root_idx, chord_type_name, intervals, octave, preview_chord=False):
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
        
        self._target_chord_name = f"{root_name} {chord_type_name}"
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
        
        self.targetChordChanged.emit(self._target_chord_name)
        print(f"ChordTrainer: Next target is {self._target_chord_name} (intervals: {self._target_intervals}, pitches: {self._target_pitches}, hold={self._required_hold_ms}ms)")
        
        # Pause input evaluation until speech finishes in lesson mode
        if self._is_lesson_mode:
            self._is_paused_for_speech = True
            self.lessonStateChanged.emit()
            
        # If preview requested, emit signal for MIDI output
        # Defer if the AI is still speaking (coach intro) to avoid audio collision
        if preview_chord:
            if self._is_lesson_mode:
                print(f"ChordTrainer: Deferring MIDI preview until coach finishes speaking")
                self._listen_preview_pending = True
            else:
                print(f"ChordTrainer: Requesting MIDI preview for pitches: {self._target_pitches}")
                self._play_midi_preview(self._target_pitches)

        if not self._is_paused_for_speech:
            self.inputReady.emit()
            # Evaluate immediately in case keys are already appropriately held
            self._check_input()

    @Slot()
    def resume_lesson(self):
        """Called when AI finishes speaking. Applies pending exercise if queued,
        plays deferred listen preview, or resets paused state."""
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Coach speech finished, resuming lesson.")
        if self._is_paused_for_speech:
            self._is_paused_for_speech = False
            self.lessonStateChanged.emit()
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Input unlocked.")
            self.inputReady.emit()
            self._check_input() # Evaluate immediately now that speech is done
        # Play deferred listen preview now that the coach is done talking
        if self._listen_preview_pending:
            self._listen_preview_pending = False
            if self._target_pitches:
                print(f"ChordTrainer: Coach done, playing deferred MIDI preview: {self._target_pitches}")
                self._play_midi_preview(self._target_pitches)
        # Start deferred metronome now that the coach is done talking
        if self._metronome_pending:
            pending = self._metronome_pending
            self._metronome_pending = None
            interval_ms = pending["interval_ms"]
            self._metronome_start_time = time.time() + (interval_ms / 1000.0 * 4)
            self._metronome_timer.start(interval_ms)
            print(f"ChordTrainer: Coach done, starting deferred metronome at {pending['bpm']} BPM")
        # If an exercise arrived while the AI was speaking AND the student
        # isn't currently working on one, apply it now. If they ARE mid-exercise,
        if self._pending_exercise and self._is_lesson_mode and not self._target_chord_name:
            exercise = self._pending_exercise
            self._pending_exercise = None
            print(f"ChordTrainer: Applying queued exercise: {exercise.get('exercise_name', '?')}")
            self._apply_exercise(exercise)
            
        # Failsafe: If the AI spoke its intro but forgot to call set_exercise, give it 4 seconds to arrive over the network before re-prompting.
        if self._is_loading and self._is_lesson_mode:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Coach finished speaking but no exercise was set. Arming 4s failsafe timer.")
            QTimer.singleShot(4000, self._check_failsafe)

    def _check_failsafe(self):
        """Called 4 seconds after audio completes. If loading is STILL true, the tool call never arrived."""
        if self._is_loading and self._is_lesson_mode:
            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] ChordTrainer: Failsafe timer popped! Re-prompting AI for missing set_exercise tool.")
            self.requestLessonStart.emit("[System: You forgot to call the set_exercise tool. Please call it now to start the session.]")

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
        
        self.targetChordChanged.emit(self._target_chord_name)
        print(f"ChordTrainer: Progression chord {self._progression_index + 1}/{len(self._progression_steps)}: {self._target_chord_name}")
        self.inputReady.emit()
        self._check_input()

    @Slot(int, bool)
    def handle_midi_note(self, pitch: int, is_on: bool):
        """Called by AppState when a MIDI note event occurs."""
        if not self._is_active or self._is_lesson_complete:
            return

        if self._is_paused_for_speech:
            return

        if time.time() < self._ignore_midi_until:
            return

        if is_on:
            self._active_pitches.add(pitch)
            
            # Record first note time for simultaneity detection
            if self._first_note_time == 0.0:
                self._first_note_time = time.time() * 1000.0
                
            # Track wrong notes (notes not in target intervals)
            if self._exercise_type == "pentascale":
                # For pentascale, check against the exact current target pitch
                if self._pentascale_sequence and self._pentascale_index < len(self._pentascale_sequence):
                    if pitch != self._pentascale_sequence[self._pentascale_index]:
                        self._wrong_notes_count += 1
            elif self._target_intervals:
                if (pitch % 12) not in self._target_intervals:
                    self._wrong_notes_count += 1
        else:
            self._active_pitches.discard(pitch)
            
        if self._waiting_for_release:
            if len(self._active_pitches) == 0:
                self._waiting_for_release = False
                if self._exercise_type == "pentascale":
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
        else:
            self._check_chord()

    def _check_pentascale(self):
        """Validates single-note input for pentascale exercises."""
        # Wait until the lead-in is complete if we are running a metronome
        if self._metronome_timer.isActive() and self._pentascale_beat_count < 0:
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
            if self._pentascale_bpm > 0 and self._metronome_start_time > 0:
                interval_ms = 60000 / self._pentascale_bpm
                expected_time_sec = self._metronome_start_time + (self._pentascale_index * (interval_ms / 1000.0))
                actual_time_sec = time.time()
                diff_ms = (actual_time_sec - expected_time_sec) * 1000.0
                
                if diff_ms < -150:
                    feedback_text = "Fast"
                elif diff_ms > 150:
                    feedback_text = "Slow"
                else:
                    feedback_text = "Perfect!"
                    
                print(f"ChordTrainer: Timing for note {self._pentascale_index}: expected={expected_time_sec:.2f}, actual={actual_time_sec:.2f}, diff={diff_ms:.0f}ms -> {feedback_text}")
                
            self.pentascaleNoteHit.emit(self._pentascale_index, feedback_text)
            
            # Record success for this individual note
            note_name = f"{self.ROOT_NOTES[target_pitch % 12]} (Pentascale)"
            latency_ms = (time.time() - self._prompt_time) * 1000.0
            self.db.record_chord_attempt(note_name, True, latency_ms, 0, False)
            
            self._pentascale_index += 1
            
            if self._pentascale_index >= len(self._pentascale_sequence):
                # All 5 notes played correctly — complete the step
                self._metronome_timer.stop()
                self._complete_chord()
            else:
                # Update target intervals to next note (no release wait — allows legato)
                next_pitch = self._pentascale_sequence[self._pentascale_index]
                self._target_intervals = {next_pitch % 12}
                self._prompt_time = time.time()  # Reset timing for next note
                self.targetChordChanged.emit(self._target_chord_name)

    def _check_chord(self):
        if not self._target_intervals:
            return

        # Convert active pitches to their normalized intervals (0-11)
        active_intervals = {pitch % 12 for pitch in self._active_pitches}
        
        # Check if the currently held keys exactly match the target intervals
        # (Must contain all required notes, and no extra notes)
        if active_intervals == self._target_intervals:
            if self._exercise_type == "hands_together":
                # Must be playing at least one note in the bass range (octave 2-3 -> pitches 36-59)
                has_bass = any(p < 60 for p in self._active_pitches)
                if not has_bass:
                    return # Keep waiting for them to add the left hand

            if not self._is_holding:
                self._is_holding = True
                self._hold_start_time = time.time() * 1000.0
                
                # Calculate simultaneity: if all notes reached within 100ms of first note
                if self._first_note_time > 0:
                    delta = self._hold_start_time - self._first_note_time
                    self._is_simultaneous = (delta < 150) # 150ms is a generous 'block chord' threshold
                
                if self._required_hold_ms > 0:
                    if self._exercise_type == "sustain_pedal" and not self._pedal_satisfied:
                        return # Wait for the pedal to be engaged
                    self._hold_tick_timer.start()
                else:
                    if self._exercise_type == "sustain_pedal" and not self._pedal_satisfied:
                        return # Wait for the pedal to be engaged
                    self._complete_chord()
            else:
                # We are already holding. Re-evaluate if pedal satisfaction unlocked progression
                if self._exercise_type == "sustain_pedal" and self._pedal_satisfied:
                    if self._required_hold_ms > 0 and not self._hold_tick_timer.isActive():
                        self._hold_tick_timer.start()
                    elif self._required_hold_ms == 0:
                        self._complete_chord()
        else:
            # If they are holding the correct NUMBER of keys but they are not the right intervals,
            # we consider this a "failed attempt" and emit a subtle feedback signal.
            if len(active_intervals) == len(self._target_intervals) and not self._is_holding:
                self.chordFailed.emit()
                # Record a failure in the DB (pass false for success)
                latency_ms = (time.time() - self._prompt_time) * 1000.0
                self.db.record_chord_attempt(self._target_chord_name, False, latency_ms, 
                                           self._wrong_notes_count, False)
                if self.curriculum:
                    self.curriculum.complete_exercise(self._target_chord_name, False, 
                                                     self._current_track, self._current_milestone_id)
                
            # If they let go or miss-pressed during a hold, cancel the hold
            if self._is_holding and self._required_hold_ms > 0:
                self._is_holding = False
                self._hold_progress = 0.0
                self._hold_tick_timer.stop()
                self.lessonStateChanged.emit() # update progress bar to 0

    def _on_hold_tick(self):
        """Timer callback to update the visual hold progress bar"""
        if not self._is_holding or not self._is_active:
            self._hold_tick_timer.stop()
            return
            
        elapsed = (time.time() * 1000.0) - self._hold_start_time
        
        if elapsed >= self._required_hold_ms:
            self._hold_progress = 1.0
            self._hold_tick_timer.stop()
            self._complete_chord()
        else:
            self._hold_progress = elapsed / self._required_hold_ms
            
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
            if self._consecutive_struggles >= 2 and self._is_lesson_mode:
                self.speakBrief.emit(
                    f"[Brief]: Student has struggled {self._consecutive_struggles} times in a row "
                    f"(last: {self._target_chord_name}, {latency_ms:.0f}ms, {self._wrong_notes_count} wrong notes). "
                    "Give a 1-sentence encouraging tip. Do NOT call set_exercise or end_lesson. Do NOT pause the lesson."
                )
                self._consecutive_struggles = 0
        else:
            self._consecutive_struggles = 0
            self._consecutive_successes += 1
            if self._consecutive_successes >= 3 and self._is_lesson_mode:
                self.speakBrief.emit(
                    f"[Brief]: Student nailed {self._consecutive_successes} exercises in a row! "
                    "Give a quick 3-5 word encouragement. Do NOT call set_exercise or end_lesson. Do NOT pause the lesson."
                )
                self._consecutive_successes = 0
        
        # Notify UI
        self.chordSuccess.emit(self._target_chord_name, latency_ms)
        
        # Reset hold state
        self._hold_progress = 0.0
        self._is_holding = False
        self.lessonStateChanged.emit()
        
        # Pause briefly before advancing if in lesson mode to avoid double-triggers
        if self._is_lesson_mode:
            time.sleep(0.1)
        
        # Handle progression sub-step advancement
        if self._exercise_type == "progression":
            self._progression_index += 1
            if self._progression_index < len(self._progression_steps):
                # More chords in this progression — wait for release then advance
                print(f"ChordTrainer: Waiting for release before next progression chord...")
                self._waiting_for_release = True
                self.targetChordChanged.emit(self._target_chord_name)
                return
            # else: progression complete, fall through to _next_chord
            
        if self._exercise_type == "listen":
            # For listening quizzes, the user answers via UI, not keys. Pause briefly then move on.
            QTimer.singleShot(700, self._next_chord)
        else:
            print("ChordTrainer: Waiting for user to release all keys...")
            self._waiting_for_release = True

    @Slot()
    def _play_metronome_click(self):
        """Called periodically by QTimer for timed exercises."""
        self._pentascale_beat_count += 1
        self.metronomeTick.emit()
