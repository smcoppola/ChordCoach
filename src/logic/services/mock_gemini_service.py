import json
import base64
import time
from PySide6.QtCore import QObject, Signal, Slot, QTimer

class MockGeminiService(QObject):
    responseReceived = Signal(str)
    connectionStatusChanged = Signal(bool)
    audioDataReceived = Signal(bytes)
    aiStartedSpeaking = Signal()
    aiFinishedSpeaking = Signal()
    reconnecting = Signal(int, int)
    exerciseReceived = Signal(dict)
    lessonEndReceived = Signal(str)
    theoryVisualReceived = Signal(dict)
    apiKeyInvalid = Signal()

    def __init__(self, settings_manager=None, api_key=None):
        super().__init__()
        self.connected = False
        self._intentional_disconnect = False
        self._exercise_pending = False
        self._is_speaking_state = False

    def start(self):
        # Simulate websocket connection delay
        QTimer.singleShot(500, self._simulate_connection)

    def connect_service(self, context_str: str, **kwargs):
        print(f"MockGeminiService: Mock connect_service called with kwargs {kwargs}")
        self.start()

    def _simulate_connection(self):
        self.connected = True
        self.connectionStatusChanged.emit(True)

    def force_disconnect(self):
        self._intentional_disconnect = True
        self.connected = False
        self.connectionStatusChanged.emit(False)

    def clear_exercise_pending(self):
        self._exercise_pending = False

    def send_prompt(self, prompt_text: str):
        self.send_lesson_plan(prompt_text)

    def send_lesson_plan(self, prompt_text: str, context: dict = None):
        print("MockGeminiService: Received prompt for lesson plan.")
        
        # If it's the Circle of Fifths tutorial, we'll simulate the 8 steps
        if "[Circle of Fifths Tutorial Mode]" in prompt_text:
            print("MockGeminiService: Starting Circle of Fifths Mock Sequence")
            self._run_circle_sequence()
        else:
            print("MockGeminiService: Standard lesson plan requested (not mocked here).")
            self.responseReceived.emit("Mock standard lesson started.")

    def _run_circle_sequence(self):
        steps = [
            (
                {"show_base": True, "show_major": False, "show_minor": False, "highlight_key": ""},
                "Welcome to the Circle of Fifths. This wheel is one of the most powerful tools in all of music theory. It maps out the relationship between every key in western music. Let's build it up together, one piece at a time."
            ),
            (
                {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "C"},
                "Here are the twelve major keys, arranged in a circle. At the very top, we have C Major. C Major has no sharps and no flats. It's the simplest key on the piano, just the white keys."
            ),
            (
                {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "G"},
                "Now watch the wheel spin. Moving one step clockwise takes us up a perfect fifth, to G Major. G Major has exactly one sharp: F sharp. Each step clockwise adds one more sharp."
            ),
            (
                {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "D"},
                "Another step clockwise brings us to D Major, with two sharps. See the pattern? Every clockwise step is a perfect fifth higher, and adds one sharp to the key signature."
            ),
            (
                {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "F"},
                "Now let's go the other direction. From C, one step counter-clockwise takes us down a fifth, to F Major. F Major has one flat: B flat. Each step counter-clockwise adds a flat."
            ),
            (
                {"show_base": True, "show_major": True, "show_minor": True, "highlight_key": "C"},
                "But there's a hidden layer. Every major key has a relative minor that shares the exact same notes. The inner ring reveals them. For C Major, the relative minor is A Minor. They are two sides of the same coin."
            ),
            (
                {"show_base": True, "show_major": True, "show_minor": True, "highlight_key": ""},
                "That's the Circle of Fifths. Sharps accumulate clockwise, flats accumulate counter-clockwise, and every major key has a relative minor hiding on the inside. This simple wheel will guide your understanding of keys, chords, and progressions for the rest of your musical journey. Great job today!"
            ),
            (
                "END",
                ""
            )
        ]

        self.step_idx = 0
        self.steps = steps

        # Emit the first tool call immediately, then wait 1s before speaking
        self._execute_next_step()

    def _execute_next_step(self):
        if self.step_idx >= len(self.steps):
            return

        tool_data, text = self.steps[self.step_idx]
        
        if tool_data == "END":
            self.lessonEndReceived.emit("Completed Circle of Fifths introduction.")
            return

        print(f"MockGeminiService: Emitting tool: {tool_data}")
        self.theoryVisualReceived.emit(tool_data)
        
        # We start speaking after the tool has had a little time to animate (e.g. 500ms)
        QTimer.singleShot(500, lambda: self._speak_text(text))

    def _speak_text(self, text):
        print(f"MockGeminiService: Speaking: {text}")
        if not self._is_speaking_state:
            self._is_speaking_state = True
            self.aiStartedSpeaking.emit()

        self.responseReceived.emit(text)

        # Simulate time it takes to speak (roughly 1 second per 15 characters)
        read_time_ms = int((len(text) / 15.0) * 1000)
        
        QTimer.singleShot(read_time_ms, self._finish_speaking)

    def _finish_speaking(self):
        print("MockGeminiService: Finished speaking.")
        self._is_speaking_state = False
        self.aiFinishedSpeaking.emit()
        
        self.step_idx += 1
        
        # Wait 2 seconds between steps for student to absorb the info
        QTimer.singleShot(2000, self._execute_next_step)

    # ── Mute audio entirely (ChordTrainer expects real wav data otherwise)
    def _handle_audio(self):
        pass
