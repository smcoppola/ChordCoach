import os
import sys
import ssl
import threading
import asyncio
import json
import base64
import struct
import time
from datetime import datetime
import websockets  # type: ignore

# websockets v15+ moved ConnectionClosed; fall back gracefully
try:
    from websockets.exceptions import ConnectionClosed
except ImportError:
    from websockets import ConnectionClosed  # type: ignore

from PySide6.QtCore import QObject, Signal, Slot, QTimer  # type: ignore
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QAudio # type: ignore

def _build_ssl_context() -> ssl.SSLContext:
    """
    Build an SSL context that works on all platforms.
    On macOS, Python from python.org does NOT use the system keychain,
    which causes wss:// connections to fail with CERTIFICATE_VERIFY_FAILED.
    We use certifi's CA bundle as the authoritative trust store.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        # certifi not installed — fall back to the default system behaviour.
        # On Linux this usually works fine; on macOS it may still fail.
        pass
    return ctx

class GeminiService(QObject):
    responseReceived = Signal(str)
    connectionStatusChanged = Signal(bool)
    audioDataReceived = Signal(bytes)
    aiStartedSpeaking = Signal()
    aiFinishedSpeaking = Signal()
    reconnecting = Signal(int, int)  # (attempt, max_attempts)
    exerciseReceived = Signal(dict)   # Fired when model calls set_exercise tool
    lessonEndReceived = Signal(str)   # Fired when model calls end_lesson tool
    theoryVisualReceived = Signal(dict) # Fired when model calls update_theory_visual
    apiKeyInvalid = Signal()    # Fired when the API key is missing or rejected

    def __init__(self, settings_manager=None, api_key=None):
        super().__init__()
        self.settings = settings_manager
        self.api_key = self.settings.apiKey if self.settings else (api_key or os.environ.get("GOOGLE_API_KEY"))
        self.ws_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={self.api_key}"
        
        self.loop = asyncio.new_event_loop()
        self.ws = None
        self.connected = False
        self._intentional_disconnect = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        
        self._audio_buffer = b""
        self._last_audio_write_time = 0.0
        self._audio_timer = QTimer(self)
        self._audio_timer.timeout.connect(self._pump_audio)
        self._audio_timer.start(10)
        
        self._is_speaking_state = False
        self._turn_complete = True # Start as complete
        self._exercise_pending = False  # Track if an exercise is awaiting completion
        self._tools_disabled = False  # When True, omit tools from session setup (voice-only mode)
        
        # Start the asyncio loop in a background thread so we don't block the Qt UI
        self._loop_thread = threading.Thread(target=self._start_loop, daemon=True)
        self._loop_thread.start()

        if not self.api_key:
            print("Warning: GOOGLE_API_KEY not found in environment.")

        # Setup audio playback for Gemini responses
        self._setup_playback()
        self.audioDataReceived.connect(self._play_audio_chunk)

    def _setup_playback(self):
        fmt = QAudioFormat()
        fmt.setSampleRate(24000) # Match Gemini's native output rate of 24kHz
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        
        # We start the sink immediately so it is ready to receive bytes
        try:
            self.audio_sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
            self.audio_sink.setBufferSize(32768)
            self.audio_io = self.audio_sink.start()
        except Exception as e:
            print(f"Gemini Service: Audio playback setup failed: {e}")
            self.audio_sink = None
            self.audio_io = None

    @Slot(bytes)
    def _play_audio_chunk(self, data: bytes):
        self._audio_buffer += data

    @Slot()
    def _pump_audio(self):
        if not self.audio_sink:
            return

        # We only consider finishing speech if the server turn is definitively over AND the local buffer has drained.
        if self._is_speaking_state and not self._audio_buffer and self._turn_complete:
            time_since_last = time.time() - self._last_audio_write_time
            if time_since_last > 0.2:
                is_empty = self.audio_sink.bytesFree() >= self.audio_sink.bufferSize() * 0.95
                if is_empty or time_since_last > 1.0:
                    print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Audio playback FINISHED (Turn Complete)")
                    self._is_speaking_state = False
                    self.aiFinishedSpeaking.emit()

        if not self._audio_buffer:
            return
            
        # Restart the active IO device if the QAudioSink has stopped or been suspended (common on underrun)
        if not self.audio_io or not self.audio_io.isOpen() or self.audio_sink.state() == QAudio.State.StoppedState:
            try:
                self.audio_io = self.audio_sink.start()
            except Exception as e:
                print(f"Gemini Service: Audio sink restart failed: {e}")
                return

        if not self.audio_io:
            return
            
        free_bytes = self.audio_sink.bytesFree()
        if free_bytes > 0:
            chunk = self._audio_buffer[:free_bytes] # type: ignore
            written = self.audio_io.write(chunk)
            if written > 0:
                self._audio_buffer = self._audio_buffer[written:] # type: ignore
                self._last_audio_write_time = time.time()
                if not self._is_speaking_state:
                    print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Audio playback STARTED")
                    self._is_speaking_state = True
                    self.aiStartedSpeaking.emit()

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    @Slot(str, str, str, str)
    def connect_service(self, coach_context: str = "", voice: str = "Kore",
                        brevity: str = "Normal", personality: str = "Encouraging"):
        """Called by AppState or UI to initiate the WebSocket connection."""
        # Refresh API key right before connecting in case it changed
        self.api_key = self.settings.apiKey if self.settings else os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            print("Cannot connect: No API Key")
            self.apiKeyInvalid.emit()
            return
            
        self.ws_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={self.api_key}"
        self.coach_context = coach_context
        self._voice = voice
        self._brevity = brevity
        self._personality = personality
        asyncio.run_coroutine_threadsafe(self._connect_ws(), self.loop)

    @Slot()
    def disconnect_service(self):
        self._intentional_disconnect = True
        asyncio.run_coroutine_threadsafe(self._disconnect_ws(), self.loop)

    @Slot()
    def stop_current_audio(self):
        """Immediately stop any AI audio currently playing and clear buffers."""
        print("Gemini Service: Force-stopping current audio playback.")
        self._audio_buffer = b""
        
        if self.audio_sink:
            # Stop playback immediately
            self.audio_sink.stop()
            # Reset internal speak state
            if self._is_speaking_state:
                self._is_speaking_state = False
                self.aiFinishedSpeaking.emit()
            
            # Restart the sink's IO device so it's fresh for the next turn
            # (QAudioSink.start() clears its internal buffer)
            try:
                self.audio_io = self.audio_sink.start()
            except Exception as e:
                print(f"Gemini Service: Failed to restart audio sink after stop: {e}")

    @Slot(bool)
    def set_tools_disabled(self, disabled: bool):
        """Enable or disable tool declarations for the next session setup.
        Must be called BEFORE connect_service to take effect."""
        self._tools_disabled = disabled
        print(f"Gemini Service: Tools {'DISABLED' if disabled else 'ENABLED'} for next session.")

    async def _connect_ws(self):
        if self.connected:
            return
            
        try:
            ssl_ctx = _build_ssl_context()
            self.ws = await websockets.connect(self.ws_url, ssl=ssl_ctx)
            self.connected = True
            self._intentional_disconnect = False
            self._reconnect_attempts = 0
            self.connectionStatusChanged.emit(True)
            print("Gemini Service: WebSocket Connected.")
            
            # Build personality-based system instruction
            personality = getattr(self, '_personality', 'Encouraging')
            brevity = getattr(self, '_brevity', 'Normal')
            voice = getattr(self, '_voice', 'Kore')
            
            if personality == "Old-School":
                base_instruction = (
                    "You are 'ChordCoach', a no-nonsense, old-school piano teacher with decades of experience. "
                    "You do NOT sugarcoat anything. You are direct, matter-of-fact, and occasionally intimidating — "
                    "like a strict conservatory professor who demands excellence. You give praise ONLY when it is "
                    "truly earned, and even then it's understated. You NEVER say 'great job!' for basic exercises. "
                    "You push the student to be better with firm, authoritative guidance. "
                    "CRITICAL RULES: 1. NEVER narrate what you are doing. NEVER output internal monologue. "
                    "Just speak directly to the student. 2. DO NOT provide verbal feedback after every single chord. "
                    "3. If a student plays correctly, stay silent and let them continue. "
                    "4. When introducing exercises, be matter-of-fact about what they need to do and why."
                )
            elif personality == "Balanced":
                base_instruction = (
                    "You are 'ChordCoach', an expert AI piano teacher. You strike a balanced, realistic tone. "
                    "You are encouraging but not overly patronizing, and you are gently critical when the student "
                    "is struggling or makes repeated mistakes. You focus on practical, actionable advice rather than "
                    "constant cheerleading. "
                    "CRITICAL RULES: 1. When a new exercise starts, introduce what to do clearly and practically. "
                    "2. NEVER narrate what you are doing. NEVER output internal monologue. Just speak directly to the user. "
                    "3. DO NOT provide verbal feedback after every single chord. "
                    "4. If a user plays correctly, stay silent and let them continue. "
                    "5. If a user is struggling, step in with a helpful tip or gentle correction, rather than just telling them to try again."
                )
            else:  # Encouraging (default)
                base_instruction = (
                    "You are 'ChordCoach', an expert and encouraging AI piano teacher. "
                    "Your job is to make learning the piano an engaging experience for your student. "
                    "CRITICAL RULES: 1. When a new exercise starts, introduce it clearly and briefly. "
                    "Avoid long theoretical lectures. Focus on the core objective. "
                    "2. NEVER narrate what you are doing. NEVER output any internal "
                    "monologue like 'I will now give feedback'. Just speak the script directly to the user. "
                    "3. DO NOT provide verbal feedback after every single chord—the user gets visual feedback on-screen. "
                    "4. If a user plays a chord correctly, stay silent and let them continue unless they ask a question "
                    "or need to move to a new exercise. 5. Be encouraging and act like a real, helpful music teacher. "
                    "6. SILENCE IS GOLDEN: During drills of the same type, you should be completely silent 80% of the time."
                )
            
            # Apply brevity modifier
            if brevity == "Detailed":
                base_instruction += " For transitions to a NEW exercise type, use 2 concise sentences. When introducing a genuinely NEW CONCEPT or exercise type for the first time, give a thorough 8-12 sentence explanation covering WHAT it is, WHY it matters musically, and HOW to do it."
            elif brevity == "Terse":
                base_instruction += " Keep all speech to a minimum. For new concepts, use 3-5 sentences maximum."
            else:  # Normal
                base_instruction += " For transitions to a NEW exercise type, use 1 concise sentence. When introducing a genuinely NEW CONCEPT or exercise type for the first time, give a clear 8-12 sentence explanation covering WHAT it is, WHY it matters musically, and HOW to do it."

            # Global Pronunciation Rules
            base_instruction += " PRONUNCIATION RULE: Whenever you see a Roman Numeral chord progression (like I-V-vi-IV), pronounce it as numbers (e.g. 'one, five, six, four'), NOT as letters (e.g. 'eye, vee')."
            
            base_instruction += (
                " VOICE RULES: 1. NEVER say raw numbers like BPM, milliseconds, or technical parameters. "
                "Say 'play slowly and steadily' instead of 'play at 60 BPM'. "
                "2. The student sees the chord/notes on screen — focus on WHY they're doing this, not WHAT keys to press. "
                "3. Between exercises of the SAME type, provide a 1-3 word micro-affirmation ONLY every 3 to 5 reps. Otherwise, remain COMPLETELY SILENT and just call set_exercise. "
                "4. Only speak longer sentences when: introducing a NEW exercise type for the first time, giving feedback on significant struggles, or ending the lesson. "
                "5. Keep transitions fast. Call set_exercise immediately after receiving performance data. "
                "If the next exercise is the same type as the last, do NOT speak - just call the tool."
                "6. When a [System Note] says 'Do NOT call any tools', obey unconditionally — do NOT call set_exercise or end_lesson. "
                "7. THOUGHT BUCKET RULE (CRITICAL): You are a native audio model. EVERY WORD of your main response is immediately synthesized into speech and spoken aloud. Put all your internal reasoning, step-by-step planning, performance evaluation, and state tracking into the 'internal_monologue' parameter of your tool calls. BUT CRITICALLY: DO NOT put musical explanations or theory teaching into the thought bucket! If you are introducing a new concept (like 'What is an Inversion?'), you MUST speak the explanation ALOUD so the student hears it.\n"
                "CRITICAL RULES FOR EXERCISE GENERATION:\n"
                "- You are the conductor. Assign exercises STRICTLY ONE AT A TIME. (Note: A 'progression' exercise containing multiple chords counts as a single exercise. Use 'progression' for ANY chord transition drills).\n"
                "- If the curriculum requires 'song_application', you MUST use the `song_application` exercise_type and provide a `piece_name` (e.g. 'bach/bwv1.6.mxl').\n"
                "- DO NOT use parallel function calling to dispense the entire block at once.\n"
                "- Always wait for me to report the student's performance before giving the next step.\n"
                "- For 'exercise_name', provide a descriptive name for the specific drill you are giving (e.g., \"C Major Root Position\"), NOT the name of the entire lesson block.\n"
                "- VARIETY RULE: Within a block, you MUST vary the exercises. If the goal is 'Major Triads', do not just ask for C Major 10 times. Vary the keys (C, F, G), vary the inversion (Root, 1st, 2nd), or vary the exercise type (chord, then listen, then pentascale). DO NOT REPEAT THE EXACT SAME EXERCISE MORE THAN TWICE.\n"
                "- ADVANCEMENT RULE: You must move to the next block after you have assigned approximately the 'Target exercise count' for the current block. Do not linger on one block forever.\n"
                "BEGINNER SAFETY RULES:\n"
                "- DO NOT use 7th, 9th, or extended chords unless in target_chords.\n"
                "- DO NOT use complex rhythms for beginners.\n"
                "- For 'listen' exercises, ONLY use Major and Minor.\n"
                "- ALWAYS prioritize the 'target_chords' list."
            )
            if hasattr(self, 'coach_context') and self.coach_context:
                base_instruction += "\n\n" + self.coach_context
                
            setup_msg = {
                "setup": {
                    "model": "models/gemini-2.5-flash-native-audio-latest",
                    "generationConfig": {
                         "responseModalities": ["AUDIO"],
                         "speechConfig": {
                             "voiceConfig": {
                                 "prebuiltVoiceConfig": {
                                     "voiceName": voice 
                                 }
                             }
                         }
                    },
                    "systemInstruction": {
                        "parts": [{
                            "text": base_instruction
                        }]
                    }
                }
            }

            # Only include tools if they are not disabled (e.g., during circle tutorial voice-only mode)
            if not self._tools_disabled:
                setup_msg["setup"]["tools"] = [{
                    "functionDeclarations": [
                        {
                            "name": "set_exercise",
                            "description": (
                                "Set the next piano exercise for the student. "
                                "CRITICAL: Call this EXACTLY ONCE per turn. DO NOT use parallel function calling to queue multiple exercises. "
                                "You must wait for the user to perform the exercise before calling this tool again. "
                                "Multiple simultaneous calls will be ignored."
                            ),
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "internal_monologue": {
                                        "type": "STRING",
                                        "description": "MANDATORY THOUGHT BUCKET. Put all your internal reasoning, step-by-step planning, performance evaluation, and state tracking here. Do NOT speak this out loud. Provide a detailed explanation of why you are calling this tool and what your plan is."
                                    },
                                    "exercise_type": {
                                        "type": "STRING",
                                        "description": "One of: chord, pentascale, progression, listen, hands_together, sustain_pedal, steady_pulse"
                                    },
                                    "exercise_name": {
                                        "type": "STRING",
                                        "description": "Human-readable name for this exercise group (e.g. 'Minor Triads')"
                                    },
                                    "root_idx": {
                                        "type": "INTEGER",
                                        "description": "Root note as semitone offset from C: C=0, C#=1, D=2, ... B=11"
                                    },
                                    "chord_type_name": {
                                        "type": "STRING",
                                        "description": "Chord quality: Major, Minor, Diminished, Augmented, Sus2, Sus4, Major7, Minor7, Dominant7"
                                    },
                                    "hand": {
                                        "type": "STRING",
                                        "description": "Which hand: right, left, or both"
                                    },
                                    "hold_ms": {
                                        "type": "INTEGER",
                                        "description": "How long the student must hold the chord in ms. 0 = strike only, 2000+ = sustain"
                                    },
                                    "track": {
                                        "type": "STRING",
                                        "description": "Curriculum track: technique, theory, ear, repertoire"
                                    },
                                    "milestone_id": {
                                        "type": "STRING",
                                        "description": "Curriculum milestone identifier"
                                    },
                                    "scale_type": {
                                        "type": "STRING",
                                        "description": "For pentascale exercises: Major or Minor"
                                    },
                                    "direction": {
                                        "type": "STRING",
                                        "description": "For pentascale: ascending or descending"
                                    },
                                    "octave": {
                                        "type": "INTEGER",
                                        "description": "Octave number, usually 4"
                                    },
                                    "bpm": {
                                        "type": "INTEGER",
                                        "description": "Metronome BPM for timed exercises. 0 or omit for free play"
                                    },
                                    "preview_chord": {
                                        "type": "BOOLEAN",
                                        "description": "If true, play the chord on the MIDI keyboard before the student tries"
                                    },
                                    "target_quality": {
                                        "type": "STRING",
                                        "description": "For listen exercises: Major or Minor"
                                    },
                                    "pedal_type": {
                                        "type": "STRING",
                                        "description": "For sustain_pedal exercises: direct or legato"
                                    },
                                    "inversion": {
                                        "type": "INTEGER",
                                        "description": "Chord inversion: 0 = root position (default), 1 = 1st inversion, 2 = 2nd inversion. Omit or 0 for root position."
                                    },
                                    "pulse_count": {
                                        "type": "INTEGER",
                                        "description": "For steady_pulse exercises: how many beats to play. Default is 16."
                                    },
                                    "progression_steps": {
                                        "type": "ARRAY",
                                        "description": "For progression exercises: array of chord steps",
                                        "items": {
                                            "type": "OBJECT",
                                            "properties": {
                                                "root_idx": {"type": "INTEGER"},
                                                "chord_type_name": {"type": "STRING"},
                                                "numeral": {"type": "STRING"}
                                            }
                                        }
                                    },
                                    "piece_name": {
                                        "type": "STRING",
                                        "description": "For song_application exercises: music21 corpus identifier, e.g. 'bach/bwv1.6.mxl' or 'essenFolksong/erk5'"
                                    }
                                },
                                "required": ["exercise_type", "exercise_name", "track", "milestone_id"]
                            }
                        },
                        {
                            "name": "end_lesson",
                            "description": (
                                "End the current lesson. Call this when the student has completed "
                                "enough exercises or the session time is up. Speak your closing "
                                "feedback AND call this tool."
                            ),
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "internal_monologue": {
                                        "type": "STRING",
                                        "description": "MANDATORY THOUGHT BUCKET. Put all your internal reasoning and summary generation here instead of speaking it."
                                    },
                                    "feedback_summary": {
                                        "type": "STRING",
                                        "description": "Brief text summary of the student's performance"
                                    }
                                }
                            }
                        },
                        {
                            "name": "update_theory_visual",
                            "description": (
                                "Updates the interactive Circle of Fifths visualization in real-time. "
                                "Call this at specific beats during the voice narrative to sync animations. "
                                "Supports multi-chord highlighting, prediction arrows, path tracing, and stage control."
                            ),
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {
                                    "internal_monologue": {
                                        "type": "STRING",
                                        "description": "MANDATORY THOUGHT BUCKET. Put all your calculations for the next visual stage update here instead of speaking them."
                                    },
                                    "show_base": { "type": "BOOLEAN", "description": "True to draw the blank base wheel." },
                                    "show_major": { "type": "BOOLEAN", "description": "True to reveal the outer Major key names." },
                                    "show_minor": { "type": "BOOLEAN", "description": "True to reveal the inner Minor key ring." },
                                    "highlight_key": { "type": "STRING", "description": "The specific key (e.g. 'C' or 'Am') to highlight with a golden outline." },
                                    "highlighted_chords": { "type": "ARRAY", "items": {"type": "STRING"}, "description": "List of chord keys to highlight simultaneously (e.g. ['C', 'F', 'G'])." },
                                    "revealed_keys": { "type": "ARRAY", "items": {"type": "STRING"}, "description": "List of keys (e.g. ['C', 'G']) whose text labels should be visible on the ring. If 'ALL', all keys are shown." },
                                    "arrows": { "type": "ARRAY", "items": {"type": "OBJECT", "properties": {"from": {"type": "STRING"}, "to": {"type": "STRING"}, "label": {"type": "STRING"}}}, "description": "Prediction arrows to draw between keys on the circle." },
                                    "path": { "type": "ARRAY", "items": {"type": "STRING"}, "description": "Ordered key sequence to trace as a connected path on the circle." },
                                    "stage": { "type": "INTEGER", "description": "Tutorial stage number (1-5). Controls which interactive mode is active." },
                                    "waypoints": { "type": "ARRAY", "items": {"type": "STRING"}, "description": "Target chord waypoints for guided progression challenges." }
                                },
                                "required": ["show_base", "show_major", "show_minor", "highlight_key"]
                            }
                        }
                    ]
                }]
            else:
                print("Gemini Service: Tools DISABLED for this session (voice-only mode).")
            await self._safe_ws_send(json.dumps(setup_msg))
            
            # Start the receive loop
            asyncio.create_task(self._receive_loop())
            
        except Exception as e:
            print(f"Gemini Service: Connection error: {e}")
            if getattr(e, 'status_code', None) == 400:
                print("Gemini Service: API Key is invalid (HTTP 400).")
                self.apiKeyInvalid.emit()
                self._intentional_disconnect = True

            self.connected = False
            self.connectionStatusChanged.emit(False)

    async def _safe_ws_send(self, message: str):
        """Send a message to the WebSocket, handling connection errors gracefully."""
        ws = self.ws
        if not ws:
            return
        try:
            await ws.send(message)
        except ConnectionClosed:
            print("Gemini Service: WebSocket closed during send.")
        except Exception as e:
            print(f"Gemini Service: Send failed: {e}")

    async def _disconnect_ws(self):
        ws = self.ws
        self.ws = None
        self.connected = False
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
        self.connectionStatusChanged.emit(False)
        print("Gemini Service: WebSocket Disconnected.")

    async def _receive_loop(self):
        try:
            while self.connected and self.ws:
                msg = await self.ws.recv()  # type: ignore
                data = json.loads(msg)
                
                if "setupComplete" in data:
                    print("Gemini Service: Setup is complete.")

                # ── Handle tool calls from the model ──
                if "toolCall" in data:
                    tool_call = data["toolCall"]
                    function_calls = tool_call.get("functionCalls", [])
                    
                    # When tools are disabled (voice-only mode), silently acknowledge and skip
                    if self._tools_disabled:
                        silent_responses = []
                        for fc in function_calls:
                            silent_responses.append({
                                "id": fc.get("id", ""),
                                "name": fc.get("name", ""),
                                "response": {"status": "ok"}
                            })
                        if silent_responses:
                            await self._safe_ws_send(json.dumps({"toolResponse": {"functionResponses": silent_responses}}))
                        continue
                    
                    responses = []
                    
                    for i, fc in enumerate(function_calls):
                        fn_name = fc.get("name", "")
                        fn_args = fc.get("args", {})
                        fn_id = fc.get("id", "")
                        
                        tool_response = {"status": "ok"}
                        
                        if i > 0:
                            # 100% Reject: Parallel function calls are not allowed in this curriculum engine
                            tool_response = {
                                "status": "error", 
                                "message": "Parallel tool calls are strictly forbidden. You must wait for the user to complete the FIRST exercise. Do NOT speak — just wait."
                            }
                        else:
                            print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Tool call received: {fn_name}({json.dumps(fn_args)[:120]})")
                            
                            # Intercept and print the thought bucket
                            if "internal_monologue" in fn_args:
                                print(f"\n🧠 [AI THOUGHT BUCKET] ->\n{fn_args['internal_monologue']}\n")

                            if fn_name == "set_exercise":
                                if self._exercise_pending:
                                    print(f"Gemini Service: Informing AI of pending exercise — skipping duplicate set_exercise")
                                    # Use a success status but inform the model to wait (prevents model retry-loop spam)
                                    tool_response = {"status": "awaiting_completion", "message": "System: An exercise is already active. Please WAIT for the student to finish. Do NOT speak or resend the tool call."}
                                else:
                                    self._exercise_pending = True
                                    self.exerciseReceived.emit(fn_args)
                            elif fn_name == "update_theory_visual":
                                self.theoryVisualReceived.emit(fn_args)
                            elif fn_name == "end_lesson":
                                if self._exercise_pending:
                                    print(f"Gemini Service: Informing AI of pending exercise — skipping early end_lesson")
                                    tool_response = {"status": "awaiting_completion", "message": "System: Exercise in progress. Finish the current drill before ending the lesson. Please WAIT."}
                                else:
                                    self._exercise_pending = False
                                    self.lessonEndReceived.emit(fn_args.get("feedback_summary", ""))
                        
                        responses.append({
                            "id": fn_id,
                            "name": fn_name,
                            "response": tool_response
                        })

                    if responses:
                        # Send toolResponse (required by the API)
                        tool_resp = {
                            "toolResponse": {
                                "functionResponses": responses
                            }
                        }
                        await self._safe_ws_send(json.dumps(tool_resp))
                    
                if "serverContent" in data:
                    content = data["serverContent"]
                    if "modelTurn" in content:
                        parts = content["modelTurn"].get("parts", [])
                        
                        # Gemini 2.0 often sends "thinking" text in separate modelTurns without audio.
                        # We only want to display the final spoken text. We can filter this by
                        # only emitting text chunks if this specific modelTurn also contains audio data.
                        has_audio = any("inlineData" in p for p in parts)
                        
                        for part in parts:
                            if has_audio and "text" in part:
                                text_chunk = part["text"]
                                clean_text = text_chunk.replace("*", "").strip()
                                if clean_text:
                                    self.responseReceived.emit(clean_text)
                                    print(f"Gemini: {clean_text}")
                                
                            if "inlineData" in part:
                                b64_audio = part["inlineData"].get("data", "")
                                if b64_audio:
                                    audio_bytes = base64.b64decode(b64_audio)
                                    self.audioDataReceived.emit(audio_bytes)
                                    self._turn_complete = False # We got data, turn is definitely not done.

                    if content.get("turnComplete"):
                        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Received turnComplete from API.")
                        self._turn_complete = True
                        
                        # If the model turn is complete but we never started speaking, it was silent!
                        # But wait to make sure the audio playback buffer is actually empty.
                        if not self._is_speaking_state and len(self._audio_buffer) == 0:
                            if "toolCall" in data:
                                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Tool call yielded turn. Waiting for model to follow up with audio.")
                            else:
                                print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Turn complete with NO audio. Emitting finished speaking manually.")
                                try:
                                    self.aiFinishedSpeaking.emit()
                                except RuntimeError:
                                    pass  # Signal source deleted during shutdown
                                
        except ConnectionClosed as e:
            print(f"Gemini Service: Connection closed by server. Code: {e.code}, Reason: {e.reason}")
        except Exception as e:
            print(f"Gemini Service: Error in receive loop: {e}")
        finally:
            # Force finish speaking if we were disconnected while speaking
            if self._is_speaking_state:
                print("Gemini Service: Connection dropped while speaking. Emitting finished speaking to clear locks.")
                self._is_speaking_state = False
                self._audio_buffer = b""
                try:
                    self.aiFinishedSpeaking.emit()
                except RuntimeError:
                    pass  # Signal source deleted during shutdown
            
            # Clean up current connection state without emitting disconnected yet
            ws_to_close = self.ws
            if ws_to_close:
                try:
                    await ws_to_close.close()
                except Exception:
                    pass
            self.ws = None
            self.connected = False
            
            if not self._intentional_disconnect:
                await self._attempt_reconnect()
            else:
                self.connectionStatusChanged.emit(False)
                print("Gemini Service: WebSocket Disconnected.")

    async def _attempt_reconnect(self):
        """Attempt to reconnect with exponential backoff."""
        # Reset exercise lock so new exercises can flow after reconnect
        self._exercise_pending = False

        while self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            delay = min(2 ** self._reconnect_attempts, 30)
            print(f"Gemini Service: Connection lost. Reconnecting ({self._reconnect_attempts}/{self._max_reconnect_attempts}) in {delay}s...")
            try:
                self.reconnecting.emit(self._reconnect_attempts, self._max_reconnect_attempts)
            except RuntimeError:
                pass # Already deleted
            
            await asyncio.sleep(delay)
            
            # Check if an intentional disconnect happened while we were waiting
            if self._intentional_disconnect:
                print("Gemini Service: Reconnection cancelled (intentional disconnect).")
                self.connectionStatusChanged.emit(False)
                return
            
            try:
                await self._connect_ws()
                if self.connected:
                    print("Gemini Service: Reconnected successfully!")
                    return
            except Exception as e:
                print(f"Gemini Service: Reconnect attempt {self._reconnect_attempts} failed: {e}")
        
        # All attempts exhausted
        print("Gemini Service: All reconnection attempts failed.")
        self.connectionStatusChanged.emit(False)

    @Slot(str)
    def send_prompt(self, prompt: str):
        """Send a standard text message."""
        if not self.connected or not self.ws:
            print("Gemini Service: Not connected. Dropping prompt.")
            return

        self._turn_complete = False # Expecting a response
            
        # Format the message correctly for the Bidi API
        msg = {
            "clientContent": {
                "turns": [{
                    "role": "user",
                    "parts": [{"text": prompt}]
                }],
                "turnComplete": True
            }
        }
        asyncio.run_coroutine_threadsafe(self._safe_ws_send(json.dumps(msg)), self.loop)

    @Slot()
    def clear_exercise_pending(self):
        """Clear the exercise-pending flag. Call ONLY when the student has
        completed an exercise and performance data is about to be sent."""
        self._exercise_pending = False

    def send_audio_chunk(self, pcm_data: list[float]):
        """
        Takes raw 16kHz Mono Float32 PCM arrays from the C++ AudioHandler.
        (Needs to be converted to Base64 16kHz Mono int16 for the Gemini API)
        """
        if not self.connected or not self.ws:
            return
            
        # Ducking: if the AI is currently talking (buffer has data, or we wrote to speakers recently),
        # drop the microphone input so the AI doesn't hear itself and interrupt its own speech.
        if len(self._audio_buffer) > 0 or (time.time() - self._last_audio_write_time < 0.8):
            return
            
        # 1. Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
        int16_data = [int(max(-1.0, min(1.0, s)) * 32767) for s in pcm_data]
        byte_data = struct.pack(f"<{len(int16_data)}h", *int16_data)
        
        # 2. Encode to base64
        b64_audio = base64.b64encode(byte_data).decode('utf-8')
        
        # 3. Format realtimeInput message
        msg = {
            "realtimeInput": {
                "mediaChunks": [{
                    "mimeType": "audio/pcm;rate=16000",
                    "data": b64_audio
                }]
            }
        }
        
        # 4. Fire and forget to the websocket thread
        asyncio.run_coroutine_threadsafe(self._safe_ws_send(json.dumps(msg)), self.loop)
