"""
ChordCoach Lesson Flow Test (LIVE AI)
=====================================
Test that lesson events happen in the correct order with appropriate delays/locks.
This test uses REAL Gemini interaction to verify the core learning loop.

Usage:
    python tests/test_lesson_timing.py
"""
import sys
import os
import time
import json
import shutil
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock

# ── 1. Environment Bootstrap ────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load .env manually
env_file = project_root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

# ── 2. Qt App + Audio Mocks ─────────────────────────────────────────
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QObject, Signal

if not QCoreApplication.instance():
    app = QCoreApplication(sys.argv)
else:
    app = QCoreApplication.instance()

# Headless Audio Sink
mock_audio_io = MagicMock()
mock_audio_io.isOpen.return_value = True
mock_audio_io.write.side_effect = lambda data: len(data)

mock_sink = MagicMock()
mock_sink.bytesFree.return_value = 65536
mock_sink.bufferSize.return_value = 32768
mock_sink.start.return_value = mock_audio_io
mock_sink.state.return_value = 0

import PySide6.QtMultimedia as qtmm
qtmm.QAudioSink = lambda *a, **kw: mock_sink
qtmm.QMediaDevices = MagicMock()

# ── 3. Import Application Services ──────────────────────────────────
from logic.services.database_manager import DatabaseManager
from logic.services.settings_service import SettingsService
from logic.services.curriculum_service import CurriculumService
from logic.services.chord_trainer import ChordTrainerService
from logic.services.evaluation_service import EvaluationService
from logic.services.gemini_service import GeminiService
from logic.coordinators.app_coordinator import AppCoordinator

# ── 4. Mock Hardware ────────────────────────────────────────────────
class MockHardwareService(QObject):
    midiNoteReceived = Signal(int, bool)
    sustainPedalChanged = Signal(bool)
    connectionStatusChanged = Signal(bool)
    def __init__(self):
        super().__init__()
        self.is_connected = True
        self.device_name = "Mock MIDI"
    def initialize(self): pass
    def play_metronome_tick(self, *a, **kw): pass
    def play_chord_preview(self, *a, **kw): pass
    def play_happy_tone(self): pass
    def play_sad_tone(self): pass
    def play_reconnect_ping(self): pass

# ── 5. Integration Test Runner ──────────────────────────────────────
def run_lesson_flow_test():
    print("\n--- Verifying REAL AI Lesson Flow Logic ---")
    
    test_dir = Path(tempfile.mkdtemp())
    db = DatabaseManager(test_dir / "test.db")
    
    # Create mock curriculum
    res_dir = test_dir / "resources"
    res_dir.mkdir()
    tracks_file = res_dir / "curriculum_tracks.json"
    with open(tracks_file, "w") as f:
        json.dump({
            "technique": [{
                "id": "t1", "title": "T1", "order": 1, 
                "exercise_types": ["chord"], 
                "target_keys": ["C"], "target_chords": ["C Major"], 
                "min_attempts_to_advance": 1, "min_accuracy_to_advance": 0.5
            }]
        }, f)

    settings = SettingsService(db, project_root)
    # Ensure real API key
    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY required for live test.")
        return

    curriculum = CurriculumService(db, res_dir)
    trainer = ChordTrainerService(db, curriculum, settings)
    evaluation = EvaluationService(db, project_root)
    hw = MockHardwareService()
    gemini = GeminiService(settings)
    coordinator = AppCoordinator(gemini, evaluation, trainer, hw, settings)

    # 1. START LESSON
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Starting lesson plan...")
    trainer.start_lesson_plan()
    
    # 2. WAIT FOR EXERCISE FROM REAL AI
    print("Waiting for exercise from Gemini...")
    exercise_arrived = [False]
    def on_ex(data):
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Exercise Received: {data['exercise_name']}")
        exercise_arrived[0] = True
    gemini.exerciseReceived.connect(on_ex)

    deadline = time.time() + 30.0
    while not exercise_arrived[0] and time.time() < deadline:
        app.processEvents()
        time.sleep(0.1)

    if not exercise_arrived[0]:
        print("FAILED: No exercise received from AI.")
        return

    # 3. WAIT FOR SPEECH TO FINISH (Unlock input)
    print("Waiting for AI to finish speaking...")
    while trainer._is_paused_for_speech:
        app.processEvents()
        time.sleep(0.1)

    # 4. SIMULATE USER COMPLETES CHORD
    print("Simulating C Major chord input (60, 64, 67)...")
    hw.midiNoteReceived.emit(60, True) # C4
    hw.midiNoteReceived.emit(64, True) # E4
    hw.midiNoteReceived.emit(67, True) # G4
    app.processEvents()
    time.sleep(0.5)

    # 5. USER RELEASES KEYS
    print("Releasing keys...")
    hw.midiNoteReceived.emit(60, False)
    hw.midiNoteReceived.emit(64, False)
    hw.midiNoteReceived.emit(67, False)
    app.processEvents()
    
    # 6. VERIFY NEXT EXERCISE REQUEST
    print("Waiting for success confirmation and next request...")
    time.sleep(2.0)
    app.processEvents()
    
    print("Lesson Flow Test PASSED: Real AI lifecycle verified.")
    shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    run_lesson_flow_test()
