import os
import threading
import asyncio
import json
import base64
import struct
import time
import websockets  # type: ignore
from PySide6.QtCore import QObject, Signal, Slot, QTimer  # type: ignore
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices # type: ignore

class GeminiService(QObject):
    responseReceived = Signal(str)
    connectionStatusChanged = Signal(bool)
    audioDataReceived = Signal(bytes)
    aiFinishedSpeaking = Signal()
    reconnecting = Signal(int, int)  # (attempt, max_attempts)
    exerciseReceived = Signal(dict)   # Fired when model calls set_exercise tool
    lessonEndReceived = Signal(str)   # Fired when model calls end_lesson tool

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
        self._exercise_pending = False  # Track if an exercise is awaiting completion
        
        # Start the asyncio loop in a background thread so we don't block the Qt UI
        self.thread = threading.Thread(target=self._start_loop, daemon=True)
        self.thread.start()

        if not self.api_key:
            print("Warning: GOOGLE_API_KEY not found in environment.")

        # Setup audio playback for Gemini responses
        self._setup_playback()
        self.audioDataReceived.connect(self._play_audio_chunk)

    def _setup_playback(self):
        fmt = QAudioFormat()
        fmt.setSampleRate(24000) # Match Gemini's native output rate of 24kHz
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        
        # We start the sink immediately so it is ready to receive bytes
        self.audio_sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self.audio_sink.setBufferSize(32768)
        self.audio_io = self.audio_sink.start()

    @Slot(bytes)
    def _play_audio_chunk(self, data: bytes):
        self._audio_buffer += data

    @Slot()
    def _pump_audio(self):
        # Check if the AI just finished talking (buffer is empty and 500ms has passed since last chunk)
        if self._is_speaking_state and not self._audio_buffer:
            if time.time() - self._last_audio_write_time > 1.5:
                self._is_speaking_state = False
                self.aiFinishedSpeaking.emit()

        if not self.audio_io or not self.audio_io.isOpen() or not self._audio_buffer:
            return
            
        free_bytes = self.audio_sink.bytesFree()
        if free_bytes > 0:
            chunk = self._audio_buffer[:free_bytes] # type: ignore
            written = self.audio_io.write(chunk)
            if written > 0:
                self._audio_buffer = self._audio_buffer[written:] # type: ignore
                self._last_audio_write_time = time.time()
                self._is_speaking_state = True

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def connect_service(self, coach_context: str = "", voice: str = "Kore",
                        brevity: str = "Normal", personality: str = "Encouraging"):
        """Called by AppState or UI to initiate the WebSocket connection."""
        # Refresh API key right before connecting in case it changed
        self.api_key = self.settings.apiKey if self.settings else os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            print("Cannot connect: No API Key")
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

    async def _connect_ws(self):
        if self.connected:
            return
            
        try:
            self.ws = await websockets.connect(self.ws_url)
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
                    "or need to move to a new exercise. 5. Be encouraging and act like a real, helpful music teacher."
                )
            
            # Apply brevity modifier
            if brevity == "Detailed":
                base_instruction += " When speaking, use 2 concise sentences per introduction."
            elif brevity == "Terse":
                base_instruction += " Keep ALL responses to 5-10 words maximum. Be extremely concise."
            else:  # Normal
                base_instruction += " When speaking, use 1 concise sentence per introduction."

            # Global Pronunciation Rules
            base_instruction += " PRONUNCIATION RULE: Whenever you see a Roman Numeral chord progression (like I-V-vi-IV), pronounce it as numbers (e.g. 'one, five, six, four'), NOT as letters (e.g. 'eye, vee')."
            
            # Voice Guidance Rules for exercises
            base_instruction += (
                " VOICE RULES: 1. NEVER say raw numbers like BPM, milliseconds, or technical parameters. "
                "Say 'play slowly and steadily' instead of 'play at 60 BPM'. "
                "2. The student sees the chord/notes on screen — focus on WHY they're doing this, not WHAT keys to press. "
                "3. Between exercises of the SAME type, call set_exercise with ZERO audio output — total silence. "
                "4. Only speak when: introducing a NEW exercise type, giving feedback on struggles, or ending the lesson. "
                "5. Keep transitions fast. Call set_exercise immediately after receiving performance data. "
                "6. When a [System Note] says 'Do NOT call any tools', obey unconditionally — do NOT call set_exercise or end_lesson."
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
                    },
                    "tools": [{
                        "functionDeclarations": [
                            {
                                "name": "set_exercise",
                                "description": (
                                    "Set the next piano exercise for the student. "
                                    "Call this EXACTLY ONCE per exercise. You MUST call this tool "
                                    "whenever you are given a lesson plan or asked for "
                                    "the next exercise. Only speak if introducing a NEW "
                                    "exercise type. For same-type exercises, call silently. "
                                    "NEVER call this tool multiple times in the same response."
                                ),
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "exercise_type": {
                                            "type": "STRING",
                                            "description": "One of: chord, pentascale, progression, listen, hands_together, sustain_pedal"
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
                                        "feedback_summary": {
                                            "type": "STRING",
                                            "description": "Brief text summary of the student's performance"
                                        }
                                    }
                                }
                            }
                        ]
                    }]
                }
            }
            await self.ws.send(json.dumps(setup_msg))  # type: ignore
            
            # Start the receive loop
            asyncio.create_task(self._receive_loop())
            
        except Exception as e:
            print(f"Gemini Service: Connection error: {e}")
            self.connected = False
            self.connectionStatusChanged.emit(False)

    async def _disconnect_ws(self):
        if self.ws:
            await self.ws.close()  # type: ignore
        self.ws = None
        self.connected = False
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
                    for fc in tool_call.get("functionCalls", []):
                        fn_name = fc.get("name", "")
                        fn_args = fc.get("args", {})
                        fn_id = fc.get("id", "")
                        print(f"Gemini Service: Tool call received: {fn_name}({json.dumps(fn_args)[:120]})")

                        tool_response = {"status": "ok"}

                        if fn_name == "set_exercise":
                            if self._exercise_pending:
                                # Reject: model sent another set_exercise before student completed the previous one
                                print(f"Gemini Service: REJECTING duplicate set_exercise — waiting for student completion")
                                tool_response = {"status": "error", "message": "Exercise already active. WAIT for the student to complete it. You will receive a performance report when they finish. Do NOT call set_exercise again until then."}
                            else:
                                self._exercise_pending = True
                                self.exerciseReceived.emit(fn_args)
                        elif fn_name == "end_lesson":
                            self._exercise_pending = False
                            self.lessonEndReceived.emit(fn_args.get("feedback_summary", ""))

                        # Send toolResponse (required by the API)
                        tool_resp = {
                            "toolResponse": {
                                "functionResponses": [{
                                    "id": fn_id,
                                    "name": fn_name,
                                    "response": tool_response
                                }]
                            }
                        }
                        await self.ws.send(json.dumps(tool_resp))  # type: ignore
                    
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
                                
        except websockets.exceptions.ConnectionClosed as e:
            print(f"Gemini Service: Connection closed by server. Code: {e.code}, Reason: {e.reason}")
        except Exception as e:
            print(f"Gemini Service: Error in receive loop: {e}")
        finally:
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
        while self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1
            delay = min(2 ** self._reconnect_attempts, 30)
            print(f"Gemini Service: Connection lost. Reconnecting ({self._reconnect_attempts}/{self._max_reconnect_attempts}) in {delay}s...")
            self.reconnecting.emit(self._reconnect_attempts, self._max_reconnect_attempts)
            
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
            print("Gemini Service: Not connected.")
            return

            
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
        asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(msg)), self.loop)  # type: ignore

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
        asyncio.run_coroutine_threadsafe(self.ws.send(json.dumps(msg)), self.loop)  # type: ignore
