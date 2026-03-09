import sys
import os
import time
from pathlib import Path

# Bootstrap env
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

import core.bootstrap as bootstrap
project_root, hw_bin_path, is_frozen = bootstrap.setup_env()

from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer, QObject, Signal, Slot
from logic.services.gemini_service import GeminiService
from logic.services.chord_trainer import ChordTrainerService
from logic.services.evaluation_service import EvaluationService
from logic.coordinators.app_coordinator import AppCoordinator

# Dummy dependencies
class DummyDB:
    def get_coach_context(self): return ""
    def get_learned_term_names(self): return []
    def get_seen_exercise_intros(self): return []
    def record_exercise_intro(self, ex_type): pass
    def record_chord_attempt(self, *args): pass

class MockHardwareService(QObject):
    midiNoteReceived = Signal(int, bool)
    sustainPedalChanged = Signal(bool)
    def __init__(self):
        super().__init__()
        self.is_connected = True
    def play_metronome_tick(self, is_downbeat: bool = False, is_subdivision: bool = False): pass
    def play_chord_preview(self, pitches: list[int], duration_ms: int = 1500, delay_ms: int = 0): pass

class DummySettings:
    hasCompletedOnboarding = True
    coachPersonality = "Encouraging"
    coachBrevity = "Normal"
    coachVoice = "Kore"
    
    @property
    def apiKey(self):
        return os.environ.get("GOOGLE_API_KEY", "")

class EdgeCaseTestHarness(QObject):
    def __init__(self):
        super().__init__()
        self.db = DummyDB()
        self.settings = DummySettings()
        
        eval_engine = EvaluationService(db=self.db, project_root=project_root)
        self.coordinator = AppCoordinator(
            gemini_service=GeminiService(settings_manager=self.settings),
            eval_engine=eval_engine,
            chord_trainer=ChordTrainerService(self.db, curriculum_service=None, settings_manager=self.settings),
            hw_service=MockHardwareService(), # Add MockHardwareService
            settings=self.settings
        )
        
        self.gemini = self.coordinator.gemini
        self.trainer = self.coordinator.chord_trainer
        self.evaluation = self.coordinator.evaluation
        
        # Monitor states
        self.test_finished = False
        self.eval_intro_played = False
        self.arch_intro_played = False
        self.failsafe_triggered = False
        
        # Bind verification slots
        self.gemini.connectionStatusChanged.connect(self.on_connected)
        self.coordinator.evalIntroPendingChanged.connect(self.on_eval_intro_changed)
        self.coordinator.archIntroPendingChanged.connect(self.on_arch_intro_changed)
        
        # Test 3 failsafe signal interception
        self.trainer.requestLessonStart.connect(self.on_lesson_prompt_sent)
        
        self.timeout_timer = QTimer(self)
        self.timeout_timer.timeout.connect(self.fail_timeout)
        self.timeout_timer.setSingleShot(True)

    def run(self):
        print("\n=== STARTING EDGE CASE INTEGRATION TESTS ===")
        print("Connecting to Gemini API...")
        self.gemini.connect_service(
            voice="Kore", brevity="Normal", personality="Encouraging"
        )
        self.timeout_timer.start(45000) # Give 45s for all 3 phases

    @Slot(bool)
    def on_connected(self, connected):
        if not connected: return
        print("\n[TEST] Connected! Starting Phase 1: Skill Evaluation Handoff...")
        # Start phase 1
        self.coordinator.startEvaluationWithIntro()

    # --- Phase 1: Eval Intro Verification ---
    @Slot(bool)
    def on_eval_intro_changed(self, is_pending):
        if not self.gemini.connected or self.eval_intro_played: return
        
        if is_pending:
            print("\n[PHASE 1] 'evalIntroPending' became TRUE. Waiting for AI to speak...")
        else:
            print("\n[PHASE 1] 'evalIntroPending' became FALSE. Coach finished speaking!")
            if self.evaluation.isRunning:
                print("PASS: Evaluation model automatically un-paused upon intro completion.")
                self.eval_intro_played = True
                
                # Start Phase 2: Arch Tutorial Overlay
                QTimer.singleShot(1000, self.start_phase_two)
            else:
                print("FAIL: Evaluation model did not resume.")
                self.finish_test()

    # --- Phase 2: Arch Tutorial Overlay Verification ---
    def start_phase_two(self):
        print("\n[TEST] Starting Phase 2: Arch Tutorial Overlay Handoff...")
        self.coordinator.startArchTutorialWithIntro()

    @Slot(bool)
    def on_arch_intro_changed(self, is_pending):
        if not self.gemini.connected: return
        
        if is_pending:
            print("\n[PHASE 2] 'archIntroPending' became TRUE. Waiting for AI to speak...")
        else:
            print("\n[PHASE 2] 'archIntroPending' became FALSE. Overlay unlocked!")
            self.arch_intro_played = True
            
            # Start Phase 3: Network Failsafe
            QTimer.singleShot(1000, self.start_phase_three)

    # --- Phase 3: 4-Second Network Drop Failsafe Verification ---
    def start_phase_three(self):
        print("\n[TEST] Starting Phase 3: Missing Tool Call Failsafe test...")
        self.trainer._is_lesson_mode = True
        self.trainer._is_loading = True
        
        print("\n[PHASE 3] Intentionally sending a prompt that explicitly forbids calling `set_exercise`...")
        self.trainer.requestLessonStart.emit(
            "[System Note]: This is a test. Greet the student, say 1 sentence, and then STOP TALKING. "
            "CRITICAL: Do absolutely nothing else. DO NOT CALL ANY TOOLS. Do not call `set_exercise`. Just talk and end the turn."
        )

    @Slot(str)
    def on_lesson_prompt_sent(self, prompt):
        if "forgot to call the set_exercise tool" in prompt:
            print(f"\n[PHASE 3] Caught Failsafe Recalibration Prompt: '{prompt}'")
            print("PASS: The 4-second internal failsafe correctly detected the missing tool call after audio stopped streaming and re-prompted Gemini.")
            self.failsafe_triggered = True
            self.finish_test()

    def finish_test(self):
        self.test_finished = True
        print("\n--- EDGE CASE TEST RESULTS ---")
        if self.eval_intro_played and self.arch_intro_played and self.failsafe_triggered:
            print("PASS: All orchestration state flags and timing failsafes triggered successfully.")
            sys.exit(0)
        else:
            print(f"FAIL: Eval={self.eval_intro_played}, Arch={self.arch_intro_played}, Failsafe={self.failsafe_triggered}")
            sys.exit(1)

    @Slot()
    def fail_timeout(self):
        if not self.test_finished:
            print("\n--- TEST TIMEOUT ---")
            print(f"FAIL: Eval={self.eval_intro_played}, Arch={self.arch_intro_played}, Failsafe={self.failsafe_triggered}")
            sys.exit(1)

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    harness = EdgeCaseTestHarness()
    harness.run()
    sys.exit(app.exec())
