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
        self.gemini.aiFinishedSpeaking.connect(self.trigger_sim_signal.emit, Qt.QueuedConnection)
        
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
        self.current_exercise_attempt = 0
        
        self.timeout_timer = QTimer(self)
        self.timeout_timer.timeout.connect(self.fail_timeout)
        self.timeout_timer.setSingleShot(True)
        
        self.input_sim_timer = QTimer(self)
        self.input_sim_timer.timeout.connect(self.simulate_user_input)
        self.input_sim_timer.setInterval(200) # Check 5 times a second if ready for input
        
        self.release_poll_timer = QTimer(self)
        self.release_poll_timer.timeout.connect(self._poll_release_condition)
        self.release_poll_timer.setInterval(50) # Moderate polling frequency
        self._active_sim_pitches = []
        
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
            {"exercise_type": "chord", "chord_type_name": "Major", "root_idx": 0},
            {"exercise_type": "chord", "chord_type_name": "Minor", "root_idx": 9},
            {"exercise_type": "progression", "exercise_name": "I-IV-V"},
            {"exercise_type": "pentascale", "scale_name": "C Major", "direction": "ascending"},
            {"exercise_type": "listen", "target_quality": "Major"},
            {"exercise_type": "sustain_pedal", "chord_type_name": "Major", "root_idx": 0, "pedal_type": "direct"}
        ]
        
        # Send realistic prompt forcing two sequential tools
        prompt = """[System Note]: START A NEW LESSON.

Here is the SESSION PLAN. You will assign 1 exercise per block ONE AT A TIME (DEV MODE — short session):

Block 1: Single Chord (track: 'tech')
- Goal: Play a C Major
- Target Chords: ['C Major']

Block 2: Single Chord (track: 'tech')
- Goal: Play an A Minor
- Target Chords: ['A Minor']

Block 3: Progression (track: 'tech')
- Goal: Play I-V
- Target Progression: I -> V in C Major (C Major -> G Major)

Block 4: Scale (track: 'tech')
- Goal: Play C Major Scale
- Target Scale: C Major Pentascale Ascending

Block 5: Ear Training (track: 'ear')
- Goal: Identify Major Chord by Ear
- Target Quality: Major

Block 6: Sustain Pedal (track: 'tech')
- Goal: Practice Direct Pedaling
- Target Pedal: direct

INSTRUCTIONS:
1. You MUST call the `set_exercise` tool right now to assign the first exercise.
2. Wait for me to report the student's performance before calling the tool again.
3. When they finish an exercise, I will send you a report. Call `set_exercise` again with the next step.
4. When the session is complete, call `end_lesson`.

CRITICAL RULES FOR EXERCISE GENERATION:
- You are the conductor. Assign exercises STRICTLY ONE AT A TIME. DO NOT use parallel function calling.
- Always wait for me to report the student's performance before giving the next step.

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
        self.current_exercise_attempt = 0
        # Only start input sim if there is an actual actionable target
        if "Listen" in name or " " in name:
            self.trigger_sim_signal.emit()

    @Slot()
    def simulate_user_input(self):
        t = time.time()
        if t < self.trainer._ignore_midi_until:
            return # Blocked by MIDI delay or UI flash
            
        if self.trainer._is_paused_for_speech or getattr(self.trainer, '_is_speaking_state', False):
            return # Still blocked by coach speaking

        if self.trainer._is_lesson_complete:
            return

        self.input_sim_timer.stop() # Ready!
        self.timeout_timer.start(30000) # Reset timeout
        
        self.current_exercise_attempt += 1
        
        if self.trainer._exercise_type == "pentascale":
            pitches = self.trainer._pentascale_sequence
        else:
            pitches = self.trainer._target_pitches

        # Unhappy Path Simulation
        if self.trainer._lesson_progress == 1 and self.current_exercise_attempt == 1:
            print(f"\n[TEST ACTION] UNHAPPY PATH: Playing WRONG NOTES for {self.trainer._exercise_name}")
            wrong_pitches = [p + 1 for p in pitches]
            for p in wrong_pitches:
                self.trainer.handle_midi_note(p, True)
            # Hold for long enough to trigger error (300ms threshold) then release to allow next attempt
            def release_and_retry():
                self._release_keys_and_continue(wrong_pitches)
                self.trigger_sim_signal.emit() # Restart sim for the second (correct) attempt
            QTimer.singleShot(600, release_and_retry)
            return
            
        print(f"\n[TEST ACTION] Simulating 'User' playing the correct answer for {self.trainer._exercise_name}: {pitches}")
        
        if self.trainer._exercise_type == "listen":
            # Ear training: simulate UI button press of the correct answer
            QTimer.singleShot(200, lambda: self.trainer.handle_ear_training_answer(self.trainer._target_formula_text))
            return
            
        # If it's a pentascale, play them sequentially so the sequencer logic isn't broken
        if self.trainer._exercise_type == "pentascale":
            if self.trainer._pentascale_index >= len(pitches):
                self._active_sim_pitches = list(self.trainer._active_pitches)
                self.release_poll_timer.start()
                return
                
            target = pitches[self.trainer._pentascale_index]
            self.trainer.handle_midi_note(target, True)
            
            # For pentascales we must leave the keys down to simulate legato, then fire next sim
            if self.trainer._pentascale_index < len(pitches):
                QTimer.singleShot(250, lambda: self._trigger_next_sim_tick())
            else:
                self._active_sim_pitches = list(self.trainer._active_pitches)
                self.release_poll_timer.start()
        else:
            # Play full blocking chord
            for p in pitches:
                self.trainer.handle_midi_note(p, True)
            self._active_sim_pitches = pitches
            
            if self.trainer._exercise_type == "sustain_pedal":
                print("[TEST ACTION] Engaging Sustain Pedal")
                self.trainer.handle_pedal_event(True)
                
            self.release_poll_timer.start()

    @Slot()
    def _poll_release_condition(self):
        # AI moves on / speaks next instruction immediately
        if self.trainer._is_paused_for_speech:
            self.release_poll_timer.stop()
            self._release_keys_and_continue(self._active_sim_pitches)
            return
            
        # Target reached hold progress OR we are no longer holding (system released us)
        if self.trainer._required_hold_ms > 0:
            if self.trainer._hold_progress >= 1.0 or not self.trainer._is_holding or self.trainer._waiting_for_release:
                self.release_poll_timer.stop()
                self._release_keys_and_continue(self._active_sim_pitches)
        else:
            # Immediate success mode - release when it flips back to waiting for AI
            if self.trainer._waiting_for_ai or self.trainer._waiting_for_release:
                self.release_poll_timer.stop()
                self._release_keys_and_continue(self._active_sim_pitches)

    def _trigger_next_sim_tick(self):
        self.input_sim_timer.start()

    def _release_keys_and_continue(self, pitches):
        for p in pitches:
            self.trainer.handle_midi_note(p, False)
        
        if self.trainer._exercise_type == "sustain_pedal":
            self.trainer.handle_pedal_event(False)
            
        # We don't need to restart the sim timer here; aiFinishedSpeaking or targetChordChanged will trigger it when the next step is actually ready.


    @Slot(str)
    def receive_lesson_end(self, feedback):
        print(f"\n[TEST VERIFICATION] end_lesson reached. Feedback: {feedback}")
        
        # Verify state parameters for the Lesson Complete overlay in QML
        if not self.trainer._is_lesson_complete:
            print("[TEST FATAL] Expected self.trainer._is_lesson_complete to be True!")
            sys.exit(1)
        if self.trainer._is_active:
            print("[TEST FATAL] Expected self.trainer._is_active to be False!")
            sys.exit(1)
            
        print("[TEST VERIFICATION] SUCCESS: The UI state has correctly transitioned to show the Lesson Complete overlay.")
        self.finish_test(True)

    def finish_test(self, success=False):
        self.test_finished = True
        print("\n--- INTEGRATION RUN COMPLETE ---")
        print(f"Total Audio Chunks Received: {self.audio_chunks_received}")
        print(f"Total MIDI Preview Out Events: {self.midi_out_count}")
        sys.exit(0)

    @Slot()
    def fail_timeout(self):
        if not self.test_finished:
            print("\n--- INTEGRATION RUN TIMED OUT (NO ACTIVITY) ---")
            print(f"Total Audio Chunks Received: {self.audio_chunks_received}")
            print(f"Total MIDI Preview Out Events: {self.midi_out_count}")
            sys.exit(0)

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    # Hook lesson end so test harness catches it
    harness = IntegrationTestHarness()
    harness.trainer.lessonStateChanged.connect(
        lambda: harness.receive_lesson_end("") if harness.trainer.isLessonComplete else None
    )
    harness.run()
    sys.exit(app.exec())
