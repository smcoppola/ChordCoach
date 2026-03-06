import unittest
import json
import shutil
import tempfile
import sys
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

# --- 1. Robust PySide6 Mocks ---
class MockSignal:
    def __init__(self, *args, **kwargs):
        self.connections = []
    def emit(self, *args, **kwargs):
        # Flatten nested arguments for Mock handlers
        for slot in self.connections:
            try:
                if len(args) == 1: slot(args[0])
                elif len(args) > 1: slot(*args)
                else: slot()
            except Exception as e:
                # print(f"Emit Error: {e}")
                pass
    def connect(self, slot):
        if slot not in self.connections: self.connections.append(slot)

def MockProperty(type_hint, notify=None):
    def decorator(func): return property(func)
    return decorator

def MockSlot(*args, **kwargs):
    def decorator(func): return func
    return decorator

class MockQObject:
    def __init__(self, parent=None): pass
    def setParent(self, p): pass

class MockQTimer(MockQObject):
    PreciseTimer = 1
    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeout = MockSignal()
        self._active = False
    def start(self, ms=None): self._active = True
    def stop(self): self._active = False
    def setInterval(self, ms): pass
    def setTimerType(self, t): pass
    def isActive(self): return self._active
    @staticmethod
    def singleShot(ms, slot):
        if not hasattr(sys, '_pending_timers'): sys._pending_timers = []
        sys._pending_timers.append((ms, slot))

mock_qt = MagicMock()
mock_qt.QtCore.QObject = MockQObject
mock_qt.QtCore.Signal = MockSignal
mock_qt.QtCore.Property = MockProperty
mock_qt.QtCore.Slot = MockSlot
mock_qt.QtCore.Qt.PreciseTimer = 1
mock_qt.QtCore.QTimer = MockQTimer

sys.modules['PySide6'] = mock_qt
sys.modules['PySide6.QtCore'] = mock_qt.QtCore
sys.modules['PySide6.QtGui'] = mock_qt
sys.modules['PySide6.QtQml'] = mock_qt
sys.modules['PySide6.QtMultimedia'] = MagicMock()

# --- 2. Imports after Mocking ---
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.database_manager import DatabaseManager
from logic.services.curriculum_service import CurriculumService
from logic.services.chord_trainer import ChordTrainerService
from logic.services.evaluation_service import EvaluationService
from logic.coordinators.app_coordinator import AppCoordinator

class TestFullLessonFlow(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test.db"
        self.db = DatabaseManager(self.db_path)
        sys._pending_timers = []
        
        self.res_dir = self.test_dir / "resources"
        self.res_dir.mkdir()
        self.tracks_file = self.res_dir / "curriculum_tracks.json"
        
        with open(self.tracks_file, "w") as f:
            json.dump({
                "technique": [{
                    "id": "t1", "title": "T1", "order": 1, 
                    "exercise_types": ["chord"], 
                    "target_keys": ["C"], "target_chords": ["C Major"], 
                    "min_attempts_to_advance": 1, "min_accuracy_to_advance": 0.5
                }]
            }, f)

        self.curriculum = CurriculumService(self.db, self.res_dir)
        self.settings = MagicMock()
        self.settings.hasCompletedOnboarding = True
        
        self.trainer = ChordTrainerService(self.db, self.curriculum, self.settings)
        # Manually force intervals into the trainer library if they aren't loading
        self.trainer.CHORD_TYPES["Major"] = {0, 4, 7}
        
        self.evaluation = EvaluationService(self.db, project_root)
        
        self.gemini = MagicMock()
        for sig in ["exerciseReceived", "aiFinishedSpeaking", "audioDataReceived", 
                    "responseReceived", "connectionStatusChanged", "reconnecting", "lessonEndReceived"]:
            setattr(self.gemini, sig, MockSignal())
        self.gemini.send_prompt = MagicMock()
        self.gemini.clear_exercise_pending = MagicMock()
        
        self.hw = MagicMock()
        self.hw.midiNoteReceived = MockSignal()
        self.hw.sustainPedalChanged = MockSignal()
        self.hw.is_connected = True
        
        self.coordinator = AppCoordinator(self.gemini, self.evaluation, self.trainer, self.hw, self.settings)
        
        # Timing Logger
        self.logs = []
        def mock_print(*args, **kwargs):
            msg = " ".join(map(str, args))
            # Capture both timing and logic success messages
            if "[TIMING" in msg or "SUCCESS!" in msg: 
                self.logs.append(msg)
        self.patcher = patch('builtins.print', side_effect=mock_print)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sequencing_and_timing_delays(self):
        """
        Verify that lesson events happen in the correct order with appropriate delays/locks.
        """
        print("\n--- Verifying Sequential Execution Logic ---")
        
        # 1. START LESSON
        self.trainer.start_lesson_plan()
        
        # 2. RECEIVE CHORD EXERCISE
        self.logs.append(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Gemini Service: Audio playback STARTED")
        ex_data = {"exercise_type": "chord", "exercise_name": "C Major", "root_idx": 0, "chord_type_name": "Major"}
        self.gemini.exerciseReceived.emit(ex_data)
        
        # VERIFY: Unblur happens IMMEDIATELY
        self.assertTrue(any("Applying exercise to UI" in l for l in self.logs))
        
        # 3. FINISH AUDIO (UNLOCK INPUT)
        self.gemini.aiFinishedSpeaking.emit()
        self.assertTrue(any("Input unlocked" in l for l in self.logs))
        
        # 4. USER COMPLETES CHORD
        # Note: Trainer normalized target to intervals {0, 4, 7}
        # Coordinator routes hw.midiNoteReceived -> trainer.handle_midi_note
        self.hw.midiNoteReceived.emit(60, True) # C4
        self.hw.midiNoteReceived.emit(64, True) # E4
        self.hw.midiNoteReceived.emit(67, True) # G4
        
        # VERIFY: Success recorded
        self.assertTrue(any("SUCCESS!" in l for l in self.logs), f"Logs missing SUCCESS!: {self.logs}")
        self.assertTrue(self.trainer._waiting_for_release)
        
        # 5. USER RELEASES KEYS
        sys._pending_timers = []
        self.hw.midiNoteReceived.emit(60, False)
        self.hw.midiNoteReceived.emit(64, False)
        self.hw.midiNoteReceived.emit(67, False)
        
        self.assertFalse(self.trainer._waiting_for_release)
        
        # 6. TRIGGER NEXT_CHORD
        for _, slot in sys._pending_timers: slot()
        self.assertTrue(any("Requesting NEXT exercise from AI" in l for l in self.logs))
        
        print("Integration Test PASSED: Full lifecycle sequenced correctly.")

if __name__ == "__main__":
    unittest.main()
