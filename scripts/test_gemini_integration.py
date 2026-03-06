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
from PySide6.QtCore import QTimer, QObject, Signal, Slot, Qt
from logic.services.gemini_service import GeminiService
from logic.services.chord_trainer import ChordTrainerService

# Dummy dependencies for ChordTrainer
class DummyDB:
    def get_coach_context(self): return ""
    def get_learned_term_names(self): return []
    def get_seen_exercise_intros(self): return []
    def record_exercise_intro(self, ex_type): pass
    def record_chord_attempt(self, *args): pass

class DummySettings:
    coachPersonality = "Encouraging"
    coachBrevity = "Normal"
    coachVoice = "Kore"
    
    @property
    def apiKey(self):
        return os.environ.get("GOOGLE_API_KEY", "")

class IntegrationTestHarness(QObject):
    trigger_sim_signal = Signal()

    def __init__(self):
        super().__init__()
        self.db = DummyDB()
        self.settings = DummySettings()
        
        self.gemini = GeminiService(settings_manager=self.settings)
        self.trainer = ChordTrainerService(self.db, curriculum_service=None, settings_manager=self.settings)
        
        # --- Wire them together exactly like AppCoordinator does ---
        self.trainer.requestLessonStart.connect(self.gemini.send_prompt)
        
        def on_report(report_str):
            self.gemini.clear_exercise_pending()
            self.gemini.send_prompt(report_str)
        self.trainer.reportPerformance.connect(on_report)
        
        self.gemini.exerciseReceived.connect(self.trainer.receive_exercise)
        self.gemini.lessonEndReceived.connect(self.trainer.receive_lesson_end)
        self.gemini.aiFinishedSpeaking.connect(self.trainer.resume_lesson)
        
        # --- Connections for Test Verification ---
        self.gemini.connectionStatusChanged.connect(self.on_connected)
        self.gemini.audioDataReceived.connect(self.on_audio_data)
        self.trainer.midiOutRequested.connect(self.on_midi_out)
        self.trainer.targetChordChanged.connect(self.on_target_chord_changed)
        
        self.test_finished = False
        self.audio_chunks_received = 0
        self.midi_out_count = 0
        self.current_target_index = 0
        self.step_completed_count = 0
        
        self.timeout_timer = QTimer(self)
        self.timeout_timer.timeout.connect(self.fail_timeout)
        self.timeout_timer.setSingleShot(True)
        
        self.input_sim_timer = QTimer(self)
        self.input_sim_timer.timeout.connect(self.simulate_user_input)
        self.input_sim_timer.setInterval(200) # Check 5 times a second if ready for input
        
        self.trigger_sim_signal.connect(self.start_sim, Qt.QueuedConnection)

    @Slot()
    def start_sim(self):
        print("[DEBUG SIM] Timer Started explicitly!")
        self.input_sim_timer.start()

    def run(self):
        print("\n=== STARTING END-TO-END INTEGRATION TEST ===")
        print("Connecting to Gemini API...")
        self.gemini.connect_service(
            voice="Kore",
            brevity="Normal",
            personality="Encouraging"
        )
        self.timeout_timer.start(30000)

    @Slot(bool)
    def on_connected(self, connected):
        if not connected:
            return
        
        print("\n[TEST] Connected to Gemini! Starting simulated lesson mode...")
        
        # Create a hardcoded lesson playlist to mimic CurriculumService
        self.trainer._is_lesson_mode = True
        self.trainer._is_loading = True
        self.trainer._lesson_progress = 0
        self.trainer._lesson_playlist = [
            {"exercise_type": "listen", "chord_type_name": "Major", "target_quality": "Major", "root_idx": 0, "preview_chord": True},
            {"exercise_type": "listen", "chord_type_name": "Minor", "target_quality": "Minor", "root_idx": 2, "preview_chord": True}
        ]
        
        # Send realistic prompt forcing two sequential tools
        prompt = """[System Note]: START A NEW LESSON.

Here is the SESSION PLAN. You will assign 1 exercise per block ONE AT A TIME (DEV MODE — short session):

Block 1: Ear Training - Major (track: 'ear', milestone_id: '1.1')
- Goal: Recognize Major chords
- Target Keys: []
- Target Chords: ['C Major']
- Target exercise count: 1

Block 2: Ear Training - Minor (track: 'ear', milestone_id: '1.2')
- Goal: Recognize Minor chords
- Target Keys: []
- Target Chords: ['D Minor']
- Target exercise count: 1

INSTRUCTIONS:
1. You MUST call the `set_exercise` tool right now to assign the first exercise.
2. Wait for me to report the student's performance before calling the tool again.
3. When they finish an exercise, I will send you a report. Call `set_exercise` again with the next step.
4. When the session is complete, call `end_lesson`.

CRITICAL RULES FOR EXERCISE GENERATION:
- You are the conductor. Assign exercises STRICTLY ONE AT A TIME. DO NOT use parallel function calling.
- Always wait for me to report the student's performance before giving the next step.
- Make them "listen" exercise_type.

Start the lesson now by calling set_exercise and speaking."""
        
        self.trainer.requestLessonStart.emit(prompt)

    @Slot(bytes)
    def on_audio_data(self, data):
        if self.audio_chunks_received % 10 == 0:
            print(f"[TEST VERIFICATION] AI Voice Data is streaming down... chunk #{self.audio_chunks_received}")
        self.audio_chunks_received += 1

    @Slot(list)
    def on_midi_out(self, pitches):
        print(f"[TEST VERIFICATION] Application requested MIDI Preview Output: {pitches}")
        self.midi_out_count += 1

    @Slot(str)
    def on_target_chord_changed(self, name):
        if not name or self.test_finished:
            return
            
        print(f"\n[TEST VERIFICATION] Target loaded: {name}")
        # Only start input sim if there is an actual actionable target
        if "Listen" in name or " " in name:
            self.trigger_sim_signal.emit()

    @Slot()
    def simulate_user_input(self):
        # AND if the AI is paused for speech, we should wait until it finishes speaking
        t = time.time()
        if t < self.trainer._ignore_midi_until:
            print(f"[DEBUG SIM] Blocked by MIDI delay. Wait {(self.trainer._ignore_midi_until - t):.1f}s")
            return # Still blocked by MIDI preview delays
            
        if self.trainer._is_paused_for_speech:
            print(f"[DEBUG SIM] Blocked by AI Speech pause.")
            return # Still blocked by coach speaking

        self.input_sim_timer.stop() # Ready!
        self.timeout_timer.start(30000) # Reset timeout
        
        print(f"\n[TEST ACTION] All previews done! Simulating 'User' playing the correct answer for {self.trainer._exercise_name}...")
        
        # For listen exercises, input comes from UI buttons, not MIDI keys.
        if self.trainer._exercise_type == "listen":
            ans = self.trainer._target_formula_text
            self.trainer.handle_ear_training_answer(ans)
        else:
            # Play needed MIDI keys based on trainer state
            pitches = self.trainer._target_pitches
            for p in pitches:
                self.trainer.handle_midi_note(p, True)
            
            # Wait 100ms then release
            QTimer.singleShot(100, lambda: self._release_keys(pitches))

    def _release_keys(self, pitches):
        for p in pitches:
            self.trainer.handle_midi_note(p, False)

    @Slot(str)
    def receive_lesson_end(self, feedback):
        print(f"\n[TEST VERIFICATION] end_lesson reached. Feedback: {feedback}")
        self.finish_test(True)

    def finish_test(self, success=False):
        self.test_finished = True
        print("\n--- INTEGRATION TEST RESULTS ---")
        print(f"Audio Chunks Received: {self.audio_chunks_received} (Expected > 0)")
        print(f"MIDI Preview Accords Played: {self.midi_out_count} (Expected 2)")
        
        if success and self.audio_chunks_received > 0 and self.midi_out_count >= 2:
            print("PASS: System timings, voice sync, and MIDI queues functioned perfectly.")
            sys.exit(0)
        else:
            print("FAIL: Verification conditions were not met.")
            sys.exit(1)

    @Slot()
    def fail_timeout(self):
        if not self.test_finished:
            print("\n--- INTEGRATION TEST RESULTS ---")
            print(f"FAIL: Timeout. Audio={self.audio_chunks_received}, MIDI={self.midi_out_count}")
            sys.exit(1)

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    # Hook lesson end so test harness catches it
    harness = IntegrationTestHarness()
    harness.trainer.lessonStateChanged.connect(
        lambda: harness.receive_lesson_end("") if harness.trainer.isLessonComplete else None
    )
    harness.run()
    sys.exit(app.exec())
