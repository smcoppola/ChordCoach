import os
import time
import random
import urllib.request
import json
import threading
import re
from typing import Set, List, Dict, Tuple
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
    apiConnectivityChanged = Signal(bool)  # True = confirmed, False = lost
    lessonPlanGenerated = Signal()
    midiOutRequested = Signal(list)
    metronomeTick = Signal()
    
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
        self._session_stats: Dict[str, List[float]] = {}
        self._estimated_gen_ms = 5000.0
        
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
    def start_lesson_plan(self):
        # Tailored Lesson Plan Mode
        if self._is_loading:
            return
            
        self._is_lesson_mode = True
        self._is_lesson_complete = False
        self._lesson_progress = 0
        self._is_loading = True
        
        # Synchronously calculate the estimation so QML has it immediately
        self._estimated_gen_ms = self.db.get_median_generation_time(last_n=5)
        if self._estimated_gen_ms <= 0:
             self._estimated_gen_ms = 5000.0
             
        self._loading_status_text = "CONNECTING TO YOUR COACH..."
        self.loadingStatusChanged.emit()
        self.lessonStateChanged.emit()
        
        if self._is_active:
            self._is_active = False
            self.activeChanged.emit(self._is_active)
            
        self._active_pitches.clear()
        self._session_stats.clear()
        self._struggled_items.clear()
        
        # New Curriculum-Aware Planning
        user_context = ""
        session_plan = None
        if self.curriculum:
            session_plan = self.curriculum.plan_session(available_minutes=10)
            user_context = self.curriculum.get_curriculum_context()
        else:
            user_context = self.db.get_coach_context()
            
        learned_terms = self.db.get_learned_term_names()
        if learned_terms:
            user_context += f"\n\nALREADY EXPLAINED TERMS (DO NOT explain these again!):\n{', '.join(learned_terms)}\n"
        user_context += "\nIMPORTANT: For any NEW technical music terms you use in your spoken_instruction that are NOT in the list above, you MUST explain them simply before using them. Add these new terms to the 'new_terms' array in your JSON response."
        
        threading.Thread(target=self._query_gemini_for_lesson_plan, 
                         args=(user_context, session_plan), daemon=True).start()
        
    def _query_gemini_for_lesson_plan(self, user_context: str, session_plan: dict = {}):
        """Fetches a dynamic lesson plan from Gemini based on the curriculum session plan."""
        api_key = self.settings.apiKey if self.settings else os.environ.get("GOOGLE_API_KEY")
        
        fallback_plan = True
        if api_key:
            import urllib.request
            import re
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            
            # (Connectivity check removed for brevity, proceeding to generation)
            self._loading_status_text = "GENERATING YOUR LESSON..."
            self.loadingStatusChanged.emit()
            
            # Check for developer fast-testing mode
            dev_mode = os.environ.get("DEV_MODE", "false").lower() in ("true", "1", "yes")
            
            blocks_text = ""
            if session_plan and "blocks" in session_plan:
                if dev_mode:
                    blocks_text = "Here is the SESSION PLAN for today. You must generate exactly 2 or 3 exercises for EACH block (DEV MODE IS ON - KEEP LESSONS EXTREMELY SHORT!):\n"
                else:
                    blocks_text = "Here is the SESSION PLAN for today. You must generate 20-40 exercises for EACH block:\n"
                
                for i, b in enumerate(session_plan["blocks"]):
                    blocks_text += f"\nBlock {i+1}: {b['milestone_title']} (track: '{b['track']}', milestone_id: '{b['milestone_id']}')\n"
                    blocks_text += f"- Goal: {b['milestone_description']}\n"
                    blocks_text += f"- Target Keys: {b['target_keys']}\n"
                    blocks_text += f"- Target Chords: {b['target_chords']}\n"
                    blocks_text += f"- Target exercise count for this block: {b['step_count']}\n"
                
                if session_plan.get("review_items"):
                    if dev_mode:
                        blocks_text += "\nREVIEW ITEMS (SM-2): Include EXACTLY 1 drill for each of these items:\n"
                    else:
                        blocks_text += "\nREVIEW ITEMS (SM-2): Include 2-3 drills for each of these items:\n"
                    for r in session_plan["review_items"]:
                        blocks_text += f"- {r['item_type']}: {r['item_id']}\n"
            else:
                blocks_text = "Determine the best basic progression for a beginner (C Major I-IV-V-I)."

            prompt = f"""You are 'ChordCoach', a world-class expert piano instructor. 
            
{user_context}

{blocks_text}

Generate your response as a SINGLE JSON object with two keys:
1. "new_terms": an array of objects for any new technical music terms introduced in this lesson that haven't been explained yet, e.g. [{{"term": "Triad", "explanation": "A chord made of three notes..."}}]
2. "steps": an array of exercise objects.

YOU control the pacing — use repetition, variation, and progressive difficulty.
Do NOT pad with identical back-to-back steps. Instead, vary voicings, inversions, tempos (via hold_ms), or alternate between related chords.

Return ONLY a raw JSON object.

STEP SCHEMA - Each step object in the "steps" array MUST have "exercise_type" and "hand" plus type-specific fields:

EVERY step must include:
  "hand": "right" | "left" | "both"
  "track": string (e.g. "technique" or "theory") — IMPORTANT: Match the block track.
  "milestone_id": string — IMPORTANT: Match the block milestone_id.

For exercise_type "pentascale":
  "exercise_type": "pentascale"
  "root_idx": integer 0-11
  "scale_type": "Major" or "Minor"
  "direction": "ascending" or "descending"
  "octave": integer (usually 4)
  "exercise_name": string
  "spoken_instruction": string
  "bpm": integer (OPTIONAL - Provide if you want a timed exercise with a metronome, e.g. 80. Omit for free-play)
  "hold_ms": 0

For exercise_type "chord":
  "exercise_type": "chord"
  "root_idx": integer 0-11
  "chord_type_name": string (Major, Minor, etc.)
  "exercise_name": string
  "spoken_instruction": string
  "hold_ms": integer (0 for strike, 2000+ for locking)
  "preview_chord": boolean (OPTIONAL - if true, the coach plays it first for the user)

For exercise_type "progression":
  "exercise_type": "progression"
  "exercise_name": string
  "spoken_instruction": string
  "hold_ms": integer (1000-2000)
  "progression_steps": array of objects: {{"root_idx": int, "chord_type_name": str, "numeral": str}}

For exercise_type "listen":
  "exercise_type": "listen"
  "root_idx": integer 0-11
  "chord_type_name": string (e.g. "Major")
  "target_quality": string (e.g. "Major" or "Minor")
  "exercise_name": string
  "spoken_instruction": string

For exercise_type "hands_together":
  "exercise_type": "hands_together"
  "root_idx": integer 0-11
  "chord_type_name": string
  "exercise_name": string
  "spoken_instruction": string
  "hold_ms": integer

For exercise_type "sustain_pedal":
  "exercise_type": "sustain_pedal"
  "root_idx": integer 0-11
  "chord_type_name": string
  "pedal_type": string ("direct" or "legato")
  "exercise_name": string
  "spoken_instruction": string
  "hold_ms": integer

RULES for spoken_instruction:
- ONLY the first step of each new exercise_name or block gets spoken.
- The VERY FIRST step MUST have a 3-4 sentence overview of the session goals.

BEGINNER SAFETY RULES:
- If 'Global Session Progress' indicates the user is a BEGINNER (low total attempts):
  - DO NOT use 7th, 9ths, or other extended chords unless explicitly in target_chords.
  - DO NOT use complex rhythms.
  - FOCUS on individual notes (pentascale) and basic Triads (Major/Minor).
  - For 'listen' exercises, ONLY use "Major" and "Minor" as target_quality.
- ALWAYS prioritize 'target_chords' list over the general 'milestone_description'.
"""
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2} # Low temp for structured output
            }
            
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            
            import urllib.error
            model_name = "gemini-2.5-flash"
            generation_start = time.time()
            
            # Adaptive slow timer: use historical avg if available, otherwise 5s
            avg_gen_ms = self.db.get_avg_generation_time(last_n=5)
            slow_threshold_s = max(5.0, (avg_gen_ms / 1000.0) * 0.5) if avg_gen_ms > 0 else 5.0
            
            max_retries = 12
            for attempt in range(max_retries):
                try:
                    # Start a timer to update status if request takes longer than expected
                    def _update_slow_status():
                        self._loading_status_text = "GENERATING LESSON — PLEASE WAIT..."
                        self.loadingStatusChanged.emit()
                        print(f"ChordTrainer: Gemini generation is taking longer than {slow_threshold_s:.1f}s...")
                    slow_timer = threading.Timer(slow_threshold_s, _update_slow_status)
                    slow_timer.start()
                    
                    print(f"ChordTrainer: Making Gemini request (attempt {attempt + 1}/{max_retries})...")
                    with urllib.request.urlopen(req, timeout=60) as response:
                        result = json.loads(response.read().decode('utf-8'))
                        text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '[]')
                        
                        # First try to match a JSON object, fallback to array if model disobeyed
                        json_match = re.search(r'\{.*\}', text, re.DOTALL)
                        if not json_match:
                            json_match = re.search(r'\[.*\]', text, re.DOTALL)
                            
                        clean_text = json_match.group(0) if json_match else text
                        
                        try:
                            data = json.loads(clean_text)
                            steps_data = []
                            
                            if isinstance(data, dict):
                                new_terms = data.get("new_terms", [])
                                for nt in new_terms:
                                    term = nt.get("term", "")
                                    expl = nt.get("explanation", "")
                                    if term and expl:
                                        self.db.record_learned_term(term, expl)
                                steps_data = data.get("steps", [])
                            elif isinstance(data, list):
                                steps_data = data
                                
                            if len(steps_data) > 0:
                                self._lesson_playlist = []
                                for step in steps_data:
                                    ex_type = step.get("exercise_type", "chord")
                                    
                                    if ex_type == "pentascale":
                                        # Pentascale steps need root_idx and scale_type
                                        if "root_idx" in step:
                                            step.setdefault("track", step.get("track", "technique"))
                                            step.setdefault("milestone_id", step.get("milestone_id", ""))
                                            step.setdefault("hand", "right")
                                            step.setdefault("scale_type", "Major")
                                            step.setdefault("direction", "ascending")
                                            step.setdefault("octave", 4)
                                            step.setdefault("exercise_name", "Pentascale Warmup")
                                            step.setdefault("hold_ms", 0)
                                            self._lesson_playlist.append(step)
                                    
                                    elif ex_type == "progression":
                                        # Progression steps need progression_steps array
                                        prog_steps = step.get("progression_steps", [])
                                        if prog_steps and len(prog_steps) > 0:
                                            # Validate each sub-step has valid chord types
                                            valid = True
                                            for ps in prog_steps:
                                                if ps.get("chord_type_name", "") not in self.CHORD_TYPES:
                                                    valid = False
                                                    break
                                            if valid:
                                                step.setdefault("track", step.get("track", "theory"))
                                                step.setdefault("milestone_id", step.get("milestone_id", ""))
                                                step.setdefault("hand", "right")
                                                step.setdefault("exercise_name", "Chord Progression")
                                                step.setdefault("hold_ms", 1000)
                                                self._lesson_playlist.append(step)

                                    elif ex_type == "listen":
                                        # Parse ear training steps
                                        if "root_idx" in step and "target_quality" in step:
                                            step.setdefault("track", step.get("track", "ear"))
                                            step.setdefault("milestone_id", step.get("milestone_id", ""))
                                            step.setdefault("hand", "right")
                                            step.setdefault("exercise_name", "Ear Training")
                                            step.setdefault("chord_type_name", step["target_quality"])
                                            step.setdefault("octave", 4)
                                            self._lesson_playlist.append(step)

                                    elif ex_type == "hands_together":
                                        if all(k in step for k in ("root_idx", "chord_type_name")):
                                            c_type = step["chord_type_name"]
                                            if c_type in self.CHORD_TYPES:
                                                step.setdefault("track", step.get("track", "technique"))
                                                step.setdefault("milestone_id", step.get("milestone_id", ""))
                                                step.setdefault("hand", "both")
                                                step.setdefault("exercise_name", "Hands Together")
                                                step.setdefault("hold_ms", 1000)
                                                step["octave"] = 4
                                                step["intervals"] = self.CHORD_TYPES[c_type]
                                                self._lesson_playlist.append(step)

                                    elif ex_type == "sustain_pedal":
                                        if all(k in step for k in ("root_idx", "chord_type_name")):
                                            c_type = step["chord_type_name"]
                                            if c_type in self.CHORD_TYPES:
                                                step.setdefault("track", step.get("track", "technique"))
                                                step.setdefault("milestone_id", step.get("milestone_id", ""))
                                                step.setdefault("hand", "right")
                                                step.setdefault("pedal_type", "direct")
                                                step.setdefault("exercise_name", "Pedal Technique")
                                                step.setdefault("hold_ms", 3000)
                                                step["octave"] = 4
                                                step["intervals"] = self.CHORD_TYPES[c_type]
                                                self._lesson_playlist.append(step)

                                    else:
                                        # Standard chord steps (backward compatible)
                                        if all(k in step for k in ("root_idx", "chord_type_name")):
                                            c_type = step["chord_type_name"]
                                            if c_type in self.CHORD_TYPES:
                                                step.setdefault("track", step.get("track", "technique"))
                                                step.setdefault("milestone_id", step.get("milestone_id", ""))
                                                # Allow 'hand' to be passed from the prompt, default to right
                                                step["hand"] = step.get("hand", "right")
                                                step["intervals"] = self.CHORD_TYPES[c_type]
                                                step["octave"] = step.get("octave", 4)
                                                step["exercise_type"] = "chord"
                                                # Capture the preview flag if provided
                                                if "preview_chord" in step:
                                                    step["preview_chord"] = bool(step["preview_chord"])
                                                self._lesson_playlist.append(step)
                                print(f"ChordTrainer: Added step to playlist. Current length: {len(self._lesson_playlist)}")
                                
                                if len(self._lesson_playlist) > 0:
                                    fallback_plan = False
                                    gen_time_ms = (time.time() - generation_start) * 1000.0
                                    print(f"ChordTrainer: Successfully generated AI lesson plan with {len(self._lesson_playlist)} steps in {gen_time_ms:.0f}ms.")
                                    self.db.record_generation_stat(model_name, gen_time_ms, len(self._lesson_playlist), success=True)
                                    slow_timer.cancel()
                                    break
                                else:
                                    print("ChordTrainer: Generated JSON was valid but resulting playlist was empty.")
                        except json.JSONDecodeError as e:
                            print(f"ChordTrainer: Could not parse AI lesson JSON: {e}")
                            print(f"Raw Text: {clean_text}")
                            slow_timer.cancel()
                            break
                
                except urllib.error.HTTPError as e:
                    slow_timer.cancel()
                    if e.code in (503, 429) and attempt < max_retries - 1:
                        print(f"ChordTrainer: AI API error: {e}. Retrying {attempt + 1}/{max_retries}...")
                        self._loading_status_text = f"COACH UNAVAILABLE — RETRYING ({attempt + 1}/{max_retries})..."
                        self.loadingStatusChanged.emit()
                        time.sleep(5)
                        continue
                    else:
                        print(f"ChordTrainer: AI API error (non-retryable): {e}")
                        break
                            
                except (TimeoutError, OSError) as e:
                    slow_timer.cancel()
                    if attempt < max_retries - 1:
                        print(f"ChordTrainer: Connection slow/timed out: {e}. Retrying {attempt + 1}/{max_retries}...")
                        self._loading_status_text = f"CONNECTION SLOW — RETRYING ({attempt + 1}/{max_retries})..."
                        self.loadingStatusChanged.emit()
                        time.sleep(5)
                        continue
                    else:
                        print(f"ChordTrainer: AI API error: {e}")
                        break
                except Exception as e:
                    print(f"ChordTrainer: AI API error: {e}")
                    break
                    
        # If we failed to generate an AI plan, gracefully abort the session.
        if fallback_plan:
            print("ChordTrainer: Failed to generate lesson plan.")
            self._is_loading = False
            self._is_lesson_mode = False
            self.lessonStateChanged.emit()
            self.speakInstruction.emit("[System Note]: I'm sorry, your coach is currently unavailable. Please try again later, or enjoy some free practice.")
            return
            
        self._lesson_total = len(self._lesson_playlist)
        self._is_loading = False
        
        self.lessonStateChanged.emit()
        self.lessonPlanGenerated.emit()

    @Slot()
    def activate_lesson_plan(self):
        """Called by AppState when it's safe to start the generated lesson."""
        if not self._lesson_playlist:
            return
            
        self._is_waiting_to_begin = True
        self.lessonStateChanged.emit()

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
        self.activeChanged.emit(True)
        self.lessonStateChanged.emit()
        self._next_chord()

    @Slot()
    def stop_session(self):
        if self._is_active or self._is_waiting_to_begin:
            self._is_active = False
            self._is_waiting_to_begin = False
            self._is_paused_for_speech = False
            self._metronome_timer.stop()
            self.activeChanged.emit(self._is_active)
            self.lessonStateChanged.emit()
            self._target_chord_name = ""
            self._target_intervals.clear()
            self._target_pitches.clear()
            self.targetChordChanged.emit(self._target_chord_name)
            self._hold_tick_timer.stop()
            self._is_holding = False

    def _next_chord(self):
        if self._is_lesson_mode:
            if not self._lesson_playlist:
                # Lesson over! Generate tailored feedback based on session stats
                self._is_lesson_complete = True
                
                # Format session stats for the AI
                stats_lines: List[str] = []
                for chord, latencies in self._session_stats.items():
                    if latencies:
                        avg_lat = sum(latencies) / len(latencies)
                        stats_lines.append(f"- {chord}: {len(latencies)} attempts, Average Latency {avg_lat:.0f}ms\n")
                        
                if not stats_lines:
                    stats_str = "No successful chords recorded."
                else:
                    stats_str = "".join(stats_lines)
                    
                    
                if self.coach_personality == "Old-School":
                    feedback_style = "Be direct and honest. Point out weaknesses bluntly but acknowledge genuine improvement."
                else:
                    feedback_style = "Point out what they played quickly/well, and gently note what chord they struggled with (if any) so they know what to focus on next time."
                
                prompt = f"""[System Note]: The user just completed their lesson! 
Here are their performance statistics for this specific session:
{stats_str}

Analyze this data and provide a constructive 2-3 sentence verbal feedback message.
DO NOT just say 'Great job!'. {feedback_style}"""
                self.speakInstruction.emit(prompt)
                
                if self.curriculum:
                    self.curriculum.finish_session()

                self._target_chord_name = ""
                self._target_intervals.clear()
                self._target_pitches.clear()
                self._hold_tick_timer.stop()
                self.lessonStateChanged.emit()
                self.targetChordChanged.emit(self._target_chord_name)
                return
                
            chord_data = self._lesson_playlist.pop(0)
            self._lesson_progress += 1
            
            # Update current milestone context
            self._current_track = str(chord_data.get("track", ""))
            self._current_milestone_id = str(chord_data.get("milestone_id", ""))
            
            new_exercise_name = str(chord_data.get("exercise_name", self._exercise_name)) # type: ignore
            
            # If we transitioned to a new exercise section, ask the AI to naturally speak the instruction
            if new_exercise_name != self._exercise_name and "spoken_instruction" in chord_data:
                spoken_inst: str = str(chord_data["spoken_instruction"]) # type: ignore
                # Do not speak if the instruction is empty
                if spoken_inst.strip():
                    if self.coach_personality == "Old-School":
                        style_guidance = "Give a brief, no-nonsense instruction. Be direct and authoritative, like a strict piano professor."
                    else:
                        style_guidance = "Please give a highly conversational, detailed introduction explaining the music theory behind this exercise and why it will make them a better player."
                    
                    if self.coach_brevity == "Detailed":
                        length_guidance = "Use 3-4 sentences."
                    elif self.coach_brevity == "Terse":
                        length_guidance = "Use 1 short sentence maximum."
                    else:
                        length_guidance = "Use 1-2 sentences."
                    
                    prompt = f"[System Note]: We are now starting the exercise '{new_exercise_name}'. The objective is: '{spoken_inst}'. {style_guidance} {length_guidance}"
                    self._exercise_name = new_exercise_name
                    self._is_paused_for_speech = True
                    self._pending_step = chord_data
                    self.speakInstruction.emit(prompt)
                    
                    self._target_chord_name = ""
                    self._target_intervals.clear()
                    self._target_pitches.clear()
                    self._hold_tick_timer.stop()
                    self.lessonStateChanged.emit()
                    self.targetChordChanged.emit(self._target_chord_name)
                    return
                
            self._exercise_name = new_exercise_name
            self._current_step_data = chord_data.copy()
            self._apply_step(chord_data)
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
            # The beat starts immediately on tick 0
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
        target_quality = str(chord_data.get("target_quality", "Major"))
        
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

    @Slot()
    def replay_preview(self):
        """Re-sends the MIDI preview for the current target chord."""
        if self._target_pitches:
            print(f"ChordTrainer: Replaying MIDI preview for {self._target_pitches}")
            self.midiOutRequested.emit(self._target_pitches)

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
        
        # Calculate the absolute intervals (0-11) for the logic evaluator
        self._target_intervals = {(root_idx + interval) % 12 for interval in intervals}
        
        self._prompt_time = time.time()
        # Reset performance counters for the new target
        self._wrong_notes_count = 0
        self._first_note_time = 0.0
        self._is_simultaneous = False
        
        self.targetChordChanged.emit(self._target_chord_name)
        print(f"ChordTrainer: Next target is {self._target_chord_name} (intervals: {self._target_intervals}, pitches: {self._target_pitches}, hold={self._required_hold_ms}ms)")
        
        # If preview requested, emit signal for MIDI output
        if preview_chord:
            print(f"ChordTrainer: Requesting MIDI preview for pitches: {self._target_pitches}")
            self.midiOutRequested.emit(self._target_pitches)

        # Evaluate immediately in case keys are already appropriately held
        self._check_input()

    @Slot()
    def resume_lesson(self):
        if not self._is_paused_for_speech or not hasattr(self, '_pending_step'):
            return
        self._is_paused_for_speech = False
        self.lessonStateChanged.emit()
        self._apply_step(self._pending_step)

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

    @Slot(int, bool)
    def handle_midi_note(self, pitch: int, is_on: bool):
        """Called by AppState when a MIDI note event occurs."""
        if not self._is_active or self._is_lesson_complete:
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
        if latency_ms > 4000 or self._wrong_notes_count > 2:
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
