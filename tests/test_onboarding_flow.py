"""
ChordCoach Onboarding Flow Test (LIVE AI)
========================================
Simulates the full onboarding experience with REAL Gemini interaction.
NO MOCKS for Gemini allowed.

Features:
- Structured JSONL logging
- Real Gemini connection (Phase 1 & 3)
- Simulated MIDI response for all evaluation levels

Usage:
    python tests/test_onboarding_flow.py
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

# Mock audio output (just the sink, not the AI logic)
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
    def __init__(self, test_name="onboarding"):
        self.start_time = time.time()
        self.log_dir = project_root / "logs" / "diagnostics"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"diag_{test_name}_{timestamp}.jsonl"
        self.events = []
        print(f"DIAGNOSTIC_LOG: Writing to {self.log_file}")

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
            
        self.events.append(entry)
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

# ── 6. Signal Waiter Utility ─────────────────────────────────────────
def wait_for_signal(signal, timeout_ms=30000):
    """Block until a Qt signal fires, or timeout."""
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timed_out = [False]
    
    def on_signal(*args):
        if loop.isRunning():
            loop.quit()
    
    def on_timeout():
        timed_out[0] = True
        if loop.isRunning():
            loop.quit()
    
    signal.connect(on_signal)
    timer.timeout.connect(on_timeout)
    timer.start(timeout_ms)
    loop.exec()
    timer.stop()
    
    try:
        signal.disconnect(on_signal)
    except Exception:
        pass
    
    return not timed_out[0]

def safe_process_events():
    """Helper to process Qt events without lint errors or None checks."""
    a = QCoreApplication.instance()
    if a:
        a.processEvents()

# ── 7. Onboarding Flow Test ──────────────────────────────────────────
def run_onboarding_test():
    diag = DiagnosticLogger("onboarding_live")
    diag.log("TEST_START", "Initializing LIVE services (NO MOCKS FOR GEMINI)...")

    # Capture real API key before clearing it for the Phase -1 test
    real_api_key = os.environ.get("GOOGLE_API_KEY")

    import tempfile
    test_dir = Path(tempfile.mkdtemp())
    db = DatabaseManager(test_dir / "onboarding_test.db")
    
    # Force settings to have NO API key initially to test Phase -1
    os.environ["GOOGLE_API_KEY"] = ""
    settings = SettingsService(db, test_dir)
    
    evaluation = EvaluationService(db, project_root)
    trainer = ChordTrainerService(db, None, settings)
    hw = MockHardwareService()
    gemini = GeminiService(settings)
    coordinator = AppCoordinator(gemini, evaluation, trainer, hw, settings)

    # Logging signals
    gemini.aiStartedSpeaking.connect(lambda: diag.log("AI_STATE", "Coach started speaking"))
    gemini.aiFinishedSpeaking.connect(lambda: diag.log("AI_STATE", "Coach finished speaking"))

    diag.log("PHASE_-1", "Testing API Key Guard...")
    if settings.apiKey == "":
        diag.log("STATE_CHECK", "Validated: API Key is missing.")
    
    # Use the captured real API key
    if not real_api_key or "AIzaSy" not in real_api_key:
        diag.log("FAILURE", "A real GOOGLE_API_KEY is required for this LIVE test.")
        return

    diag.log("UI_INPUT", f"Entering real API key (Length: {len(real_api_key)})...")
    settings.apiKey = real_api_key
    
    # Force Gemini to update its internal key state from settings
    gemini.api_key = settings.apiKey 
    
    diag.log("SERVICE_INIT", "Connecting to Gemini...")
    gemini.connect_service()
    
    if not wait_for_signal(gemini.connectionStatusChanged, timeout_ms=15000):
        diag.log("FAILURE", "Gemini connection timed out.")
        return
    
    if not gemini.connected:
        diag.log("FAILURE", "Gemini failed to connect. Check API key.")
        return
    
    diag.log("PHASE_1", "Starting Skill Evaluation with REAL AI Intro...")
    def on_tick(n):
        diag.log("METRONOME_TICK", f"Beat {n}")
    evaluation.metronomeTick.connect(on_tick)

    # Trigger Evaluation Intro
    coordinator.startEvaluationWithIntro()
    
    # CRITICAL: Wait for AI to finish speaking before checking evaluation state
    diag.log("WAITING", "Waiting for AI intro TURN COMPLETE...")
    # Wait for turnComplete signal via coordinator or gemini finished
    if not wait_for_signal(gemini.aiFinishedSpeaking, timeout_ms=30000):
        diag.log("WARN", "AI Finished Speaking timed out or was skipped.")
    # Wait for evaluation to actually start running
    eval_start_timeout = 45.0
    deadline = time.time() + eval_start_timeout
    while not evaluation.isRunning and time.time() < deadline:
        safe_process_events()
        time.sleep(0.1)

    if not evaluation.isRunning:
        diag.log("FAILURE", "Evaluation did not start (AI error or timeout).")
        return

    # Simulation loop for levels
    while evaluation.isRunning:
        safe_process_events()
        current_level = evaluation.currentLevel
        level_title = evaluation.sequenceTitle
        
        diag.log("LEVEL_SESSION", f"Beginning Level {current_level}: {level_title}")
        
        notes = list(evaluation.sequenceNotes)
        processed_notes = [False] * len(notes)
        
        level_timeout = time.time() + 60
        while evaluation.currentLevel == current_level and evaluation.isRunning:
            safe_process_events()
            now_beat = evaluation.currentBeat
            
            for i, note in enumerate(notes):
                if not processed_notes[i] and now_beat >= note["start_beat"]:
                    diag.log("MIDI_EVENT", f"Simulated Note Hit | Level {current_level} | Pitch {note['pitch']} | Beat {now_beat:.2f}")
                    hw.midiNoteReceived.emit(note["pitch"], True)
                    safe_process_events()
                    time.sleep(0.005)
                    hw.midiNoteReceived.emit(note["pitch"], False)
                    processed_notes[i] = True
            
            if time.time() > level_timeout:
                diag.log("TIMEOUT_FAILURE", f"Level {current_level} timed out.")
                break
            time.sleep(0.01)

    diag.log("PHASE_2", f"Evaluation Finished. Level: {evaluation.assessedLevel}")

    diag.log("PHASE_3", "Triggering Keyboard Arch Tutorial with REAL AI...")
    coordinator.startArchTutorialWithIntro()
    
    # Wait for tutorial intro to finish (just log it)
    speech_wait = 30.0
    speech_deadline = time.time() + speech_wait
    while time.time() < speech_deadline:
        safe_process_events()
        time.sleep(0.1)

    diag.log("FINAL_SYNC", "Marking onboarding complete...")
    settings.markOnboardingComplete()
    
    diag.log("TEST_COMPLETE", "Live onboarding run finished.")
    
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)

if __name__ == "__main__":
    run_onboarding_test()
