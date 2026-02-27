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

    def __init__(self, api_key=None):
        super().__init__()
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
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

    def connect_service(self, coach_context: str = "", voice: str = "Puck",
                        brevity: str = "Normal", personality: str = "Encouraging"):
        """Called by AppState or UI to initiate the WebSocket connection."""
        if not self.api_key:
            print("Cannot connect: No API Key")
            return
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
            voice = getattr(self, '_voice', 'Puck')
            
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
            else:  # Encouraging (default)
                base_instruction = (
                    "You are 'ChordCoach', an expert, encouraging, and highly expressive AI piano teacher. "
                    "Your job is to make learning the piano an exciting and engaging experience for your student. "
                    "CRITICAL RULES: 1. When a new exercise starts, introduce it with rich, descriptive sentences. "
                    "Give background on WHY this exercise is important, what it sounds like, or how it will help them "
                    "play real songs in the future. 2. NEVER narrate what you are doing. NEVER output any internal "
                    "monologue like 'I will now give feedback'. Just speak the script directly to the user. "
                    "3. DO NOT provide verbal feedback after every single chord—the user gets visual feedback on-screen. "
                    "4. If a user plays a chord correctly, stay silent and let them continue unless they ask a question "
                    "or need to move to a new exercise. 5. Be extremely encouraging, use vocal variety, and act like "
                    "a real, passionate music teacher."
                )
            
            # Apply brevity modifier
            if brevity == "Detailed":
                base_instruction += " When speaking, use 3-4 rich sentences per introduction."
            elif brevity == "Terse":
                base_instruction += " Keep ALL responses to 1 SHORT sentence maximum. No filler words. Be extremely concise."
            else:  # Normal
                base_instruction += " When speaking, use 1-2 concise sentences per introduction."
            
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
                
                # We're looking for serverContent -> modelTurn -> parts -> text
                if "setupComplete" in data:
                    print("Gemini Service: Setup is complete.")
                    
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
