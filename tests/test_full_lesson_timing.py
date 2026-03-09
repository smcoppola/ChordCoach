import unittest
import json
import shutil
import tempfile
import sys
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
import sys
from PySide6.QtCore import QCoreApplication

# We must instantiate a QCoreApplication for real Signals to function in a headless test
if not QCoreApplication.instance():
    app = QCoreApplication(sys.argv)

import PySide6.QtCore as core

# Original Mock implementation that isolates the OS event loop from the test 
class MockSignal:
    def __init__(self, *args, **kwargs):
        self.connections = []
    def emit(self, *args, **kwargs):
        for slot in self.connections:
            try:
                if len(args) == 1: slot(args[0])
                elif len(args) > 1: slot(*args)
                else: slot()
            except Exception: pass
    def connect(self, slot):
        if slot not in self.connections: 
            self.connections.append(slot)

class MockQTimer(core.QObject):
    PreciseTimer = 1
    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeout = MockSignal()
        self._active = False
    def start(self, ms=None): self._active = True
    def stop(self): self._active = False
    def setInterval(self, ms): pass
    def setTimerType(self, t): pass
    def setSingleShot(self, single_shot: bool): pass
    def isActive(self): return self._active
    @staticmethod
    def singleShot(ms, slot):
        if not hasattr(sys, '_pending_timers'): sys._pending_timers = []
        sys._pending_timers.append((ms, slot))

# Inject into PySide6 to bypass the real timer architecture safely
core.QTimer = MockQTimer

# We only mock QtMultimedia since we don't want headless tests looking for physical speakers
mock_qt = MagicMock()
sys.modules['PySide6.QtMultimedia'] = mock_qt

# --- 2. Now Import Application Services ---
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.database_manager import DatabaseManager
from logic.services.curriculum_service import CurriculumService
from logic.services.chord_trainer import ChordTrainerService
from logic.services.evaluation_service import EvaluationService
from logic.coordinators.app_coordinator import AppCoordinator
class MockEvaluationService(core.QObject):
    evaluationFinished = MockSignal()
    metronomeTick = MockSignal()
    def __init__(self):
        super().__init__()
        self.isRunning = False

class MockGeminiService(core.QObject):
    exerciseReceived = MockSignal()
    aiFinishedSpeaking = MockSignal()
    audioDataReceived = MockSignal()
    responseReceived = MockSignal()
    connectionStatusChanged = MockSignal()
    reconnecting = MockSignal()
    lessonEndReceived = MockSignal()
    def __init__(self):
        super().__init__()
        self.connected = True
        self.send_prompt = MagicMock()
        self.clear_exercise_pending = MagicMock()

class MockHardwareService(core.QObject):
    midiNoteReceived = MockSignal()
    sustainPedalChanged = MockSignal()
    def __init__(self):
        super().__init__()
        self.is_connected = True
        
    def play_metronome_tick(self, is_downbeat: bool = False, is_subdivision: bool = False):
        pass
        
    def play_chord_preview(self, pitches: list[int], duration_ms: int = 1500, delay_ms: int = 0):
        pass

class TestFullLessonTiming(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test.db"
        self.db = DatabaseManager(self.db_path)
        sys._pending_timers = []
        
        # Setup resources
        self.res_dir = self.test_dir / "resources"
        self.res_dir.mkdir()
        self.tracks_file = self.res_dir / "curriculum_tracks.json"
        
        with open(self.tracks_file, "w") as f:
            json.dump({
                "technique": [{
                    "id": "t1", "title": "T1", "order": 1, 
                    "exercise_types": ["chord", "progression", "pentascale", "listen"], 
                    "target_keys": ["C"], "target_chords": ["C Major"], 
                    "min_attempts_to_advance": 1, "min_accuracy_to_advance": 0.5,
                    "step_count": 5, "milestone_title": "T1 Title", "milestone_description": "Descr"
                }]
            }, f)

        self.curriculum = CurriculumService(self.db, self.res_dir)
        self.settings = MagicMock()
        self.settings.hasCompletedOnboarding = True
        self.settings.coachVoice = "Kore"
        self.settings.coachPersonality = "Encouraging"
        self.settings.coachBrevity = "Normal"
        
        self.trainer = ChordTrainerService(self.db, self.curriculum, self.settings)
        self.trainer.CHORD_TYPES = {
            "Major": {0, 4, 7},
            "Minor": {0, 3, 7}
        }
        
        self.evaluation = MockEvaluationService()
        
        # Mock Gemini
        self.gemini = MockGeminiService()
        
        self.hw = MockHardwareService()
        
        self.coordinator = AppCoordinator(self.gemini, self.evaluation, self.trainer, self.hw, self.settings)
        
        # Timing Logger
        self.logs = []
        def mock_print(*args, **kwargs):
            msg = " ".join(map(str, args))
            self.logs.append(msg)
        self.patcher = patch('builtins.print', side_effect=mock_print)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        import gc
        gc.collect()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def trigger_pending_timers(self, wait_ms=None):
        timers = sys._pending_timers[:]
        sys._pending_timers = []
        for _, slot in timers:
            slot()

    def test_standard_chord_drill_timing(self):
        """1. Verify 'Listen First, Play Second' and Key Release rules."""
        self.trainer._is_loading = False
        self.trainer.start_lesson_plan()
        
        ex_data = {"exercise_type": "chord", "exercise_name": "C Major", "root_idx": 0, "chord_type_name": "Major"}
        self.gemini.exerciseReceived.emit(ex_data)
        
        # LOCK TEST: Play during speech
        self.hw.midiNoteReceived.emit(60, True) # C4
        self.hw.midiNoteReceived.emit(64, True) # E4
        self.hw.midiNoteReceived.emit(67, True) # G4
        self.assertFalse(any("SUCCESS!" in l for l in self.logs))
        # Simulate AI speaking for 2 seconds while user tries to spam keys
        self.trigger_pending_timers(2000)
        
        # Finish audio
        self.gemini.aiFinishedSpeaking.emit()
        
        # ChordTrainer is deaf while speaking, so it missed the notes. 
        # We must play them AGAIN after speech for success.
        self.hw.midiNoteReceived.emit(60, True)
        self.hw.midiNoteReceived.emit(64, True)
        self.hw.midiNoteReceived.emit(67, True)
        
        self.assertTrue(any("SUCCESS!" in l for l in self.logs), f"Logs: {self.logs}")
        
        # Must wait >500ms for the success hold delay to clear before releasing
        self.trigger_pending_timers(600)
        
        # Release keys
        self.hw.midiNoteReceived.emit(60, False)
        self.hw.midiNoteReceived.emit(64, False)
        self.hw.midiNoteReceived.emit(67, False)
        self.trigger_pending_timers()
        self.assertTrue(any("Requesting NEXT exercise" in l for l in self.logs))

    def test_chord_progression_timing(self):
        """2. Progressions iterate sub-chords without making new AI requests."""
        self.trainer._is_active = True
        self.trainer._is_lesson_mode = True
        self.trainer._is_loading = False
        
        prog_data = {
            "exercise_type": "progression", 
            "exercise_name": "C to G",
            "progression_steps": [
                {"root_idx": 0, "chord_type_name": "Major", "numeral": "I", "intervals": [0, 4, 7], "octave": 4},
                {"root_idx": 7, "chord_type_name": "Major", "numeral": "V", "intervals": [0, 4, 7], "octave": 4}
            ]
        }
        self.gemini.exerciseReceived.emit(prog_data)
        
        # Simulate AI streaming audio delay
        self.trigger_pending_timers(1500)
        self.gemini.aiFinishedSpeaking.emit()
        
        # Chord 1
        self.hw.midiNoteReceived.emit(60, True)
        self.hw.midiNoteReceived.emit(64, True)
        self.hw.midiNoteReceived.emit(67, True)
        self.assertTrue(any("SUCCESS! C Major (I)" in l for l in self.logs), f"Logs: {self.logs}")
        
        self.trigger_pending_timers(600)
        
        # Release to advance
        self.hw.midiNoteReceived.emit(60, False)
        self.hw.midiNoteReceived.emit(64, False)
        self.hw.midiNoteReceived.emit(67, False)
        self.trigger_pending_timers(200)
        
        # Chord 2
        self.hw.midiNoteReceived.emit(67, True)
        self.hw.midiNoteReceived.emit(71, True)
        self.hw.midiNoteReceived.emit(74, True)
        self.assertTrue(any("SUCCESS! G Major (V)" in l for l in self.logs))
        
        self.trigger_pending_timers(600)
        
        # Release -> Final request
        self.hw.midiNoteReceived.emit(67, False)
        self.hw.midiNoteReceived.emit(71, False)
        self.hw.midiNoteReceived.emit(74, False)
        self.trigger_pending_timers(200)
        self.assertTrue(any("Requesting NEXT exercise" in l for l in self.logs))

    def test_human_finger_lingering(self):
        """3. Simulates sloppy humans releasing a sustained chord *during* the AI's next speech."""
        self.trainer._is_loading = False
        self.trainer.start_lesson_plan()
        
        # 1. Lesson starts, AI gives first exercise (C Major)
        ex_data1 = {"exercise_type": "chord", "exercise_name": "C Major", "root_idx": 0, "chord_type_name": "Major"}
        self.gemini.exerciseReceived.emit(ex_data1)
        self.trigger_pending_timers(1000)
        self.gemini.aiFinishedSpeaking.emit()
        
        # 2. User plays and successfully holds C Major
        self.hw.midiNoteReceived.emit(60, True)
        self.hw.midiNoteReceived.emit(64, True)
        self.hw.midiNoteReceived.emit(67, True)
        self.trigger_pending_timers(10)
        self.assertTrue(any("SUCCESS! C Major" in l for l in self.logs))
        
        # 3. AI starts speaking the *next* exercise (G Major). _waiting_for_ai handles the tool call mapping.
        # But wait, in reality, the user hasn't lifted their hands yet!
        # The trainer requested the next exercise automatically on success.
        
        ex_data2 = {"exercise_type": "chord", "exercise_name": "G Major", "root_idx": 7, "chord_type_name": "Major"}
        self.gemini.exerciseReceived.emit(ex_data2) # This applies G Major and sets _is_paused_for_speech = True!
        
        # 4. User releases the old keys WHILE the AI is speaking the new intro. 
        # (This used to cause a permanent state leak because handle_midi_note was deaf)
        self.trigger_pending_timers(500)
        self.hw.midiNoteReceived.emit(60, False)
        self.hw.midiNoteReceived.emit(64, False)
        self.hw.midiNoteReceived.emit(67, False)
        
        # 5. AI finishes speaking
        self.trigger_pending_timers(1000)
        self.gemini.aiFinishedSpeaking.emit() # Speech over, resumes input processing
        self.trigger_pending_timers(50)
        
        # 6. User plays G Major
        self.hw.midiNoteReceived.emit(67, True)
        self.hw.midiNoteReceived.emit(71, True)
        self.hw.midiNoteReceived.emit(74, True)
        
        # 7. Because the old Note Off events were safely processed, this should instantly succeed
        self.trigger_pending_timers(600)  # Wait for hold success
        self.assertTrue(any("SUCCESS! G Major" in l for l in self.logs), f"Logs: {self.logs}")

    def test_pentascale_legato_timing(self):
        """3. Pentascales allow legato playing."""
        self.trainer._is_lesson_mode = True
        self.trainer._is_loading = True
        
        penta_data = {
            "exercise_type": "pentascale", 
            "exercise_name": "C Scale",
            "root_idx": 0,
            "direction": "ascending",
            "scale_name": "C Major"
        }
        self.gemini.exerciseReceived.emit(penta_data)
        
        self.trigger_pending_timers(2500)
        self.gemini.aiFinishedSpeaking.emit()
        
        notes = [60, 62, 64, 65, 67]
        for n in notes:
            self.hw.midiNoteReceived.emit(n, True)
            
        self.trigger_pending_timers(200) # Give it time to register pentascale hit
        self.assertTrue(any("SUCCESS!" in l for l in self.logs))

    def test_ear_training_preview_timing(self):
        """4. Listen exercises preview after speech."""
        self.trainer._is_loading = False
        self.trainer.start_lesson_plan()
        
        listen_data = {
            "exercise_type": "listen", 
            "exercise_name": "Quality Id",
            "root_idx": 0,
            "chord_type_name": "Major",
            "target_quality": "Major"
        }
        self.gemini.exerciseReceived.emit(listen_data)
        
        # Verify MIDI preview deferred
        self.assertTrue(self.trainer._listen_preview_pending)
        
        # AI talks
        self.trigger_pending_timers(2000)
        self.gemini.aiFinishedSpeaking.emit()
        
        # Verify preview fired and ignored input
        self.assertFalse(self.trainer._listen_preview_pending)
        self.assertGreater(self.trainer._ignore_midi_until, time.time())
        
        self.trainer.handle_ear_training_answer("Major")
        self.assertTrue(any("SUCCESS!" in l for l in self.logs))

    def test_failsafe_delay_timer(self):
        """5. Ensure 4s failsafe timer arms when tool call is delayed."""
        self.trainer._is_loading = True
        self.trainer._is_lesson_mode = True
        
        self.gemini.aiFinishedSpeaking.emit()
        self.assertTrue(any("Arming 4s failsafe timer" in l for l in self.logs))
        
        self.trigger_pending_timers(4200) # Must wait > 4s for real failsafe timer!
        self.assertTrue(any("Failsafe timer popped!" in l for l in self.logs))
        self.gemini.send_prompt.assert_called()

    def test_full_lesson_marathon(self):
        """6. Full end-to-end integration test of a session."""
        self.trainer._is_loading = False
        
        # 1. Start lesson
        self.trainer.start_lesson_plan()
        self.assertTrue(self.trainer._is_loading)
        
        # 2. AI sends first exercise (Chord)
        self.gemini.exerciseReceived.emit({
            "exercise_type": "chord", "exercise_name": "C Major", 
            "root_idx": 0, "chord_type_name": "Major"
        })
        self.assertTrue(self.trainer._is_paused_for_speech)
        
        # Simulate AI talking delay
        self.trigger_pending_timers(1500)
        
        # 3. AI finishes speaking -> unlocks
        self.gemini.aiFinishedSpeaking.emit()
        self.assertFalse(self.trainer._is_paused_for_speech)
        
        # 4. Student plays chord
        self.hw.midiNoteReceived.emit(60, True)
        self.hw.midiNoteReceived.emit(64, True)
        self.hw.midiNoteReceived.emit(67, True)
        self.assertTrue(any("SUCCESS! C Major" in l for l in self.logs))
        
        self.trigger_pending_timers(600)
        
        # 5. Student releases chord -> triggers next exercise request
        self.hw.midiNoteReceived.emit(60, False)
        self.hw.midiNoteReceived.emit(64, False)
        self.hw.midiNoteReceived.emit(67, False)
        self.trigger_pending_timers()
        self.assertTrue(any("Requesting NEXT exercise" in l for l in self.logs))
        
        # 6. AI sends second exercise (Pentascale)
        self.gemini.exerciseReceived.emit({
            "exercise_type": "pentascale", "exercise_name": "C Scale",
            "root_idx": 0, "direction": "ascending", "scale_name": "C Major"
        })
        self.trigger_pending_timers(1500)
        self.gemini.aiFinishedSpeaking.emit() # unlock
        
        # 7. Student plays pentascale (legato)
        for n in [60, 62, 64, 65, 67]:
            self.hw.midiNoteReceived.emit(n, True)
        
        # Pentascale success auto-triggers next chord in its `_check_pentascale` logic
        # which calls `_complete_chord()`. Notice we don't need to release keys for pentascales.
        self.trigger_pending_timers(200)
        self.assertTrue(any("Requesting NEXT exercise" in l for l in self.logs))

        # 8. AI says lesson is over
        self.gemini.lessonEndReceived.emit("Great job today!")
        self.assertTrue(self.trainer._is_lesson_complete)

    def test_struggle_and_affirmation_streaks(self):
        """7. Verify handle_mistake and streak affirmations."""
        self.trainer._is_loading = False
        self.trainer.start_lesson_plan()
        
        brief_msgs = []
        self.trainer.speakBrief.connect(lambda msg: brief_msgs.append(msg))
        
        # Helper to simulate a full exercise cycle
        def run_exercise(root, duration_sec):
            self.gemini.exerciseReceived.emit({
                "exercise_type": "chord", "exercise_name": "Test Chord", 
                "root_idx": root, "chord_type_name": "Major"
            })
            self.trigger_pending_timers(1500)
            self.gemini.aiFinishedSpeaking.emit()
            
            # Manipulate prompt time to simulate the user taking a long time
            self.trainer._prompt_time = time.time() - duration_sec
            
            # Play correct notes
            self.hw.midiNoteReceived.emit(60 + root, True)
            self.hw.midiNoteReceived.emit(64 + root, True)
            self.hw.midiNoteReceived.emit(67 + root, True)
            
            self.trigger_pending_timers(600)
            
            # Release to reset
            self.hw.midiNoteReceived.emit(60 + root, False)
            self.hw.midiNoteReceived.emit(64 + root, False)
            self.hw.midiNoteReceived.emit(67 + root, False)
            self.trigger_pending_timers(200)

        # Struggle 1
        run_exercise(0, 5.0)  # C Major, took 5 seconds
        self.assertEqual(len(brief_msgs), 0)
        
        # Struggle 2 -> Should trigger advice
        run_exercise(2, 5.0)  # D Major, took 5 seconds
        self.assertEqual(len(brief_msgs), 1, f"Logs: {self.logs}")
        self.assertTrue("struggled 2 times in a row" in brief_msgs[0])
        brief_msgs.clear()
        
        # Success 1, 2, 3 -> Should trigger affirmation
        run_exercise(0, 1.0)
        run_exercise(2, 1.0)
        run_exercise(4, 1.0) # E Major
        self.assertEqual(len(brief_msgs), 1)
        self.assertTrue("nailed 3 exercises in a row" in brief_msgs[0])

if __name__ == "__main__":
    unittest.main()
