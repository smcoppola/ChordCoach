"""
ChordCoach Onboarding Flow FULL REVIEW (Live AI)
================================================
This script follows the 'chordcoach-lesson-flow-reviewer' skill.
It executes the onboarding flow with NO MOCKS for Gemini, allowing
for evaluation of Tone, Clarity, and Pacing.

WARNING: This will use real Gemini API tokens.

Usage:
    python tests/review_onboarding_flow.py
"""
import sys
import os
import time
import json
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

# Mock audio output (Hardware output only, NOT Gemini input/output)
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
from logic.services.chord_trainer import ChordTrainerService
from logic.services.evaluation_service import EvaluationService
from logic.services.gemini_service import GeminiService
from logic.coordinators.app_coordinator import AppCoordinator

# ── 4. Diagnostic Logger ────────────────────────────────────────────
class DiagnosticLogger:
    def __init__(self, test_name="onboarding_review"):
        self.start_time = time.time()
        self.log_dir = project_root / "logs" / "diagnostics"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"diag_{test_name}_{timestamp}.jsonl"
        print(f"REVIEW_LOG: Writing to {self.log_file}")

    def log(self, event_type: str, details: str = "", raw_data: any = None):
        now = time.time()
        elapsed = now - self.start_time
        
        entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": round(elapsed * 1000, 2),
            "event": event_type,
            "details": details
        }
        if raw_data:
            entry["raw"] = raw_data
            
        # Console output
        print(f"[{elapsed:07.3f}] {event_type:<25s}| {details}")
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"LOGGER_ERROR: {e}")

# ── 5. Mock Hardware ────────────────────────────────────────────────
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

# ── 6. Live Review Execution ────────────────────────────────────────
def run_live_review():
    diag = DiagnosticLogger("onboarding_live_review")
    diag.log("REVIEW_START", "Initializing LIVE services (No AI Mocks)...")

    # Use a real DB for context check, or temp for clean state
    # We use temp to ensure a 'new user' flow
    import tempfile
    test_dir = Path(tempfile.mkdtemp())
    db = DatabaseManager(test_dir / "review.db")
    
    settings = SettingsService(db, project_root)
    # Ensure a real API key is present!
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key or "AIzaSy_TEST" in api_key:
         diag.log("ERROR", "No REAL Google API Key found. Skipping live test.")
         print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
         print("ERROR: Real GOOGLE_API_KEY required in .env for live review.")
         print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
         return

    evaluation = EvaluationService(db, project_root)
    trainer = ChordTrainerService(db, None, settings)
    hw = MockHardwareService()
    gemini = GeminiService(settings)
    coordinator = AppCoordinator(gemini, evaluation, trainer, hw, settings)

    # Monitor Gemini communication
    def on_prompt(p): diag.log("PROMPT_OUT", "Sending to Gemini...", {"prompt": p})
    def on_speaking(speaking): diag.log("AI_STATE", "Coach speaking: " + str(speaking))
    def on_status(status): diag.log("SYNC_STATUS", f"Gemini Status: {status}")
    
    gemini.connectionStatusChanged.connect(on_status)
    gemini.aiStartedSpeaking.connect(lambda: on_speaking(True))
    gemini.aiFinishedSpeaking.connect(lambda: on_speaking(False))

    diag.log("PHASE_0", "Attempting Live Connection to Gemini...")
    # Wait for connection
    max_wait = 10
    while not gemini.connected and max_wait > 0:
        app.processEvents()
        time.sleep(1)
        max_wait -= 1

    if not gemini.connected:
        diag.log("ERROR", "Connection to Gemini failed. Check internet/API key.")
        return

    diag.log("PHASE_1", "Starting Skill Evaluation with REAL AI Intro...")
    coordinator.startEvaluationWithIntro()
    
    # Wait for evaluation to start
    start_wait = 30 # Give AI 30s to talk
    while not evaluation.isRunning and start_wait > 0:
        app.processEvents()
        time.sleep(1)
        start_wait -= 1

    if not evaluation.isRunning:
        diag.log("TIMEOUT", "Evaluation engine never started (AI might be silent or slow).")
        return

    # Simulate levels (Slow beginner pacing)
    while evaluation.isRunning:
        app.processEvents()
        current_level = evaluation.currentLevel
        diag.log("LEVEL_PROGRESS", f"Now playing Level {current_level}: {evaluation.sequenceTitle}")
        
        notes = list(evaluation.sequenceNotes)
        processed_notes = [False] * len(notes)
        
        level_timeout = time.time() + 60
        while evaluation.currentLevel == current_level and evaluation.isRunning:
            app.processEvents()
            now_beat = evaluation.currentBeat
            
            for i, note in enumerate(notes):
                if not processed_notes[i] and now_beat >= note["start_beat"]:
                    # Simulate slight latency/hesitation
                    time.sleep(0.05) 
                    hw.midiNoteReceived.emit(note["pitch"], True)
                    app.processEvents()
                    time.sleep(0.1) # Note duration
                    hw.midiNoteReceived.emit(note["pitch"], False)
                    processed_notes[i] = True
            
            if time.time() > level_timeout:
                diag.log("LEVEL_FAIL", "Level timeout.")
                break
            time.sleep(0.05)

    diag.log("PHASE_2", "Evaluation Complete. Reviewing Gemini summary...")
    # Coordinator handles auto-transition if settings allow, but for onboarding
    # we usually have Phase 2 results screen.
    time.sleep(5)
    
    diag.log("PHASE_3", "Triggering Arch Tutorial Intro...")
    coordinator.startArchTutorialWithIntro()
    time.sleep(10) # Let them speak

    diag.log("REVIEW_COMPLETE", "Closing session.")
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    run_live_review()
