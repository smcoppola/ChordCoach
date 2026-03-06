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
from PySide6.QtCore import QTimer
from logic.services.gemini_service import GeminiService

class TestHarness:
    def __init__(self):
        self.gemini = GeminiService()
        self.gemini.exerciseReceived.connect(self.on_exercise)
        self.gemini.lessonEndReceived.connect(self.on_lesson_end)
        self.gemini.connectionStatusChanged.connect(self.on_connected)
        self.call_count = 0
        self.max_calls = 10 # Safety limit
        self.test_finished = False
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self.fail_timeout)
        self.timeout_timer.setSingleShot(True)
        
    def run(self):
        print("Connecting to Gemini API...")
        self.gemini.connect_service(
            voice="Kore",
            brevity="Normal",
            personality="Encouraging"
        )
        self.timeout_timer.start(25000)
        
    def on_connected(self, connected):
        if connected:
            print("Connected to Gemini. Sending session plan prompt...")
            
            prompt = """[System Note]: START A NEW LESSON.

Here is the SESSION PLAN. You will assign 2-3 exercises per block ONE AT A TIME (DEV MODE — short session):

Block 1: Right Hand C Pentascale (track: 'technique', milestone_id: 'rh_pentascale_c')
- Goal: Play a C major pentascale with the right hand.
- Target Keys: [60, 62, 64, 65, 67]
- Target Chords: []
- Target exercise count: 3

Block 2: Your First Song (track: 'repertoire', milestone_id: 'first_song')
- Goal: Progression using I-V-vi-IV (C, G, Am, F)
- Target Keys: []
- Target Chords: ['C Major', 'G Major', 'A Minor', 'F Major']
- Target exercise count: 2

INSTRUCTIONS:
1. You MUST call the `set_exercise` tool right now to assign the first exercise. Do NOT forget to call the tool.
2. Wait for me to report the student's performance before calling the tool again.
3. When they finish an exercise, I will send you a report. Decide the next step (advance, repeat, or simplify) and call `set_exercise` again.
4. When the session is complete, call `end_lesson`.

CRITICAL RULES FOR EXERCISE GENERATION:
- You are the conductor. Assign exercises STRICTLY ONE AT A TIME.
- DO NOT use parallel function calling to dispense the entire block at once.
- Always wait for me to report the student's performance before giving the next step.

Start the lesson now by calling set_exercise and speaking."""
            
            self.gemini.send_prompt(prompt)
            
    def on_exercise(self, data):
        self.timeout_timer.start(25000) # Reset timeout for next interaction
        self.call_count += 1
        name = data.get('exercise_name', 'Unknown')
        ex_type = data.get('exercise_type', '')
        print(f"-> AI called set_exercise {self.call_count}: {name} (type: {ex_type})")
        
        if self.call_count >= self.max_calls:
            print("Reached max calls safety limit! Exiting early to prevent loop.")
            self.finish_test(False)
            return
            
        report = f"""[System Note]: Student completed exercise #{self.call_count}. Last: '{name}' (type={ex_type}). Last chord latency: 850ms. Wrong notes this step: 0.

CRITICAL INSTRUCTION: Call set_exercise EXACTLY ONCE for the next step, or end_lesson if complete. NEVER call set_exercise multiple times in the same response. Just give me one exercise and WAIT."""

        self.gemini.clear_exercise_pending() # Unlock the service to receive the next call
        print(f"   [User plays correctly...] -> sending performance report to AI in 2s")
        QTimer.singleShot(2000, lambda: self.gemini.send_prompt(report))
        
    def on_lesson_end(self, feedback):
        print(f"-> AI called end_lesson! Feedback: {feedback}")
        self.finish_test(True)

    def finish_test(self, success=False):
        print("\n--- TEST RESULTS ---")
        print(f"Total set_exercise consecutive calls successfully looped: {self.call_count}")
        if success:
            print("PASS: Runthrough completed and gracefully ended via end_lesson.")
        else:
            print("FAIL: Test stopped early before AI finished lesson.")
            
        self.test_finished = True
        sys.exit(0 if success else 1)
        
    def fail_timeout(self):
        if not self.test_finished:
            print("\n--- TEST RESULTS ---")
            print("FAIL: Test harness timed out waiting for AI tool call.")
            sys.exit(1)

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    harness = TestHarness()
    harness.run()
    sys.exit(app.exec())
