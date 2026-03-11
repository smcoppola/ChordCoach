"""
ChordCoach Diagnostic Lesson Runner
====================================
Connects to the real Gemini API, starts a lesson, simulates correct MIDI input
for each exercise, and writes a structured log file for post-run analysis.

Usage:
    python tests/test_full_lesson_timing.py

Output:
    tests/logs/lesson_run_YYYYMMDD_HHMMSS.log
"""
import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── 1. Environment Bootstrap ────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load .env manually (same as core.bootstrap)
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

# Mock audio output so the test runs headless (no speakers)
mock_audio_io = MagicMock()
mock_audio_io.isOpen.return_value = True
mock_audio_io.write.side_effect = lambda data: len(data)  # pretend we wrote it all

mock_sink = MagicMock()
mock_sink.bytesFree.return_value = 65536
mock_sink.bufferSize.return_value = 32768
mock_sink.start.return_value = mock_audio_io
mock_sink.state.return_value = 0  # ActiveState

# Patch QAudioSink and QMediaDevices before importing GeminiService
import PySide6.QtMultimedia as qtmm
_OrigSink = qtmm.QAudioSink
_OrigDevices = qtmm.QMediaDevices
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

# ── 4. Diagnostic Logger ────────────────────────────────────────────
class DiagnosticLogger:
    """Captures timestamped events for the diagnostic log file."""
    def __init__(self):
        self.start_time = time.time()
        self.events = []
        self.exercises_received = 0
        self.exercises_completed = 0
        self.failsafe_fires = 0
        self.stuck_locks = 0
        self.dropped_tool_calls = 0
        self.longest_gap = 0.0
        self.longest_gap_time = 0.0
        self._last_event_time = self.start_time

    def log(self, event_type: str, details: str = ""):
        now = time.time()
        elapsed = now - self.start_time
        gap = now - self._last_event_time
        
        if gap > self.longest_gap:
            self.longest_gap = gap
            self.longest_gap_time = elapsed
        
        self._last_event_time = now
        entry = f"[{elapsed:07.3f}] {event_type:<25s}| {details}"
        self.events.append(entry)
        print(entry)  # Also print live

    def write_report(self, log_dir: Path):
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"lesson_run_{timestamp}.log"
        
        duration = time.time() - self.start_time
        
        lines = [
            "=== CHORDCOACH LESSON DIAGNOSTIC RUN ===",
            f"Timestamp: {datetime.now().isoformat()}",
            f"Duration: {duration:.1f}s",
            f"Exercises received: {self.exercises_received}",
            f"Exercises completed: {self.exercises_completed}",
            "",
            "--- EVENT LOG ---",
        ]
        lines.extend(self.events)
        
        lines.append("")
        lines.append("--- TIMING ANALYSIS ---")
        if self.exercises_completed > 0:
            avg = duration / self.exercises_completed
            lines.append(f"Avg time per exercise: {avg:.1f}s")
        lines.append(f"Longest gap (no activity): {self.longest_gap:.1f}s at [{self.longest_gap_time:07.3f}]")
        lines.append(f"Failsafe timer fires: {self.failsafe_fires}")
        lines.append(f"Stuck _is_requesting_exercise locks: {self.stuck_locks}")
        lines.append(f"Dropped tool calls (AI spoke but no set_exercise): {self.dropped_tool_calls}")
        
        lines.append("")
        lines.append("--- FLAGS ---")
        if self.dropped_tool_calls == 0:
            lines.append("[OK] All AI turns produced tool calls")
        else:
            lines.append(f"[WARN] {self.dropped_tool_calls} AI turn(s) did not produce a set_exercise tool call")
        if self.failsafe_fires == 0:
            lines.append("[OK] No failsafe timer activations")
        else:
            lines.append(f"[WARN] Failsafe timer fired {self.failsafe_fires} time(s)")
        if self.stuck_locks == 0:
            lines.append("[OK] No stuck exercise request locks")
        else:
            lines.append(f"[ERROR] _is_requesting_exercise got stuck {self.stuck_locks} time(s)")
        if self.longest_gap > 10.0:
            lines.append(f"[WARN] Longest gap was {self.longest_gap:.1f}s — possible deadlock")
        elif self.longest_gap > 5.0:
            lines.append(f"[INFO] Longest gap was {self.longest_gap:.1f}s — normal for AI speech")
        else:
            lines.append(f"[OK] No suspicious timing gaps")
        
        log_file.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n{'='*60}")
        print(f"Log written to: {log_file}")
        print(f"{'='*60}")
        return log_file

# ── 5. Mock Hardware & Evaluation ────────────────────────────────────
class MockHardwareService(QObject):
    midiNoteReceived = Signal(int, bool)
    sustainPedalChanged = Signal(bool)
    connectionStatusChanged = Signal(bool)
    def __init__(self):
        super().__init__()
        self.is_connected = True
        self.device_name = "Diagnostic Virtual MIDI"
    def initialize(self): pass
    def play_metronome_tick(self, *a, **kw): pass
    def play_chord_preview(self, *a, **kw): pass

class MockEvaluationService(QObject):
    evaluationFinished = Signal()
    metronomeTick = Signal()
    def __init__(self):
        super().__init__()
        self.isRunning = False

# ── 6. Signal Waiter Utility ─────────────────────────────────────────
def wait_for_signal(signal, timeout_ms=30000):
    """Block until a Qt signal fires, or timeout."""
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timed_out = [False]
    result = [None]
    
    def on_signal(*args):
        result[0] = args
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
    
    # Disconnect to avoid leaks
    try:
        signal.disconnect(on_signal)
    except Exception:
        pass
    
    return (not timed_out[0], result[0])

import random

# ── 7. Sloppy Human Simulation ───────────────────────────────────────

def human_play_during_speech(hw, diag):
    """Simulate a human noodling on the keys while the AI is still talking."""
    random_pitches = random.sample(range(48, 84), random.randint(1, 3))
    diag.log("HUMAN_CHAOS", f"Playing during speech: pitches={random_pitches}")
    for p in random_pitches:
        hw.midiNoteReceived.emit(p, True)
    app.processEvents()
    time.sleep(0.1)
    for p in random_pitches:
        hw.midiNoteReceived.emit(p, False)
    app.processEvents()

def human_linger_keys(hw, diag, pitches):
    """Simulate NOT releasing keys from the previous exercise — they linger."""
    if pitches:
        linger = pitches[:random.randint(1, len(pitches))]
        diag.log("HUMAN_CHAOS", f"Lingering keys from previous: {linger} (NOT released)")
        # We simply don't emit Note Off for these — they stay stuck
        return linger
    return []

def human_wrong_notes_first(hw, trainer, diag):
    """Simulate pressing the wrong chord first, then correcting."""
    wrong_pitches = [p + random.choice([-1, 1, 2]) for p in trainer._target_pitches[:2]]
    diag.log("HUMAN_CHAOS", f"Wrong notes first attempt: {wrong_pitches}")
    for p in wrong_pitches:
        hw.midiNoteReceived.emit(p, True)
    app.processEvents()
    time.sleep(0.15)
    # Release wrong notes
    for p in wrong_pitches:
        hw.midiNoteReceived.emit(p, False)
    app.processEvents()
    time.sleep(0.2)
    app.processEvents()

def human_extra_note(hw, trainer, diag):
    """Simulate pressing an extra accidental note along with the correct chord."""
    used = set(trainer._target_pitches)
    extra = random.choice([p for p in range(48, 84) if p not in used])
    diag.log("HUMAN_CHAOS", f"Extra accidental note: {extra}")
    hw.midiNoteReceived.emit(extra, True)
    app.processEvents()
    time.sleep(0.08)
    hw.midiNoteReceived.emit(extra, False)
    app.processEvents()

def simulate_correct_input(trainer, exercise_data, hw, diag, with_chaos=True):
    """Simulate pressing the correct keys for the given exercise,
    optionally with sloppy human behaviors mixed in."""
    ex_type = exercise_data.get("exercise_type", "chord")
    
    if ex_type == "listen":
        # Occasionally give wrong answer first
        if with_chaos and random.random() < 0.3:
            wrong = "Minor" if exercise_data.get("target_quality", "Major") == "Major" else "Major"
            diag.log("HUMAN_CHAOS", f"Wrong ear training answer: {wrong}")
            trainer.handle_ear_training_answer(wrong)
            app.processEvents()
            time.sleep(0.5)
        
        quality = exercise_data.get("target_quality", 
                  exercise_data.get("chord_type_name", "Major"))
        diag.log("MIDI_INPUT_SENT", f"ear_training_answer={quality}")
        trainer.handle_ear_training_answer(quality)
        return
    
    # Optionally press wrong notes first (30% chance)
    if with_chaos and random.random() < 0.3 and ex_type in ("chord", "hands_together"):
        human_wrong_notes_first(hw, trainer, diag)
    
    if ex_type == "pentascale":
        sequence = list(trainer._pentascale_sequence)
        diag.log("MIDI_INPUT_SENT", f"pentascale pitches={sequence}")
        for i, pitch in enumerate(sequence):
            # Occasionally hit a wrong note in pentascale (20% chance per note)
            if with_chaos and random.random() < 0.2:
                wrong = pitch + random.choice([-1, 1])
                diag.log("HUMAN_CHAOS", f"Wrong pentascale note: {wrong} (expected {pitch})")
                hw.midiNoteReceived.emit(wrong, True)
                app.processEvents()
                time.sleep(0.05)
                hw.midiNoteReceived.emit(wrong, False)
                app.processEvents()
                time.sleep(0.1)
            hw.midiNoteReceived.emit(pitch, True)
            app.processEvents()
            time.sleep(0.05)
        return

    if ex_type == "progression":
        for step_idx, step in enumerate(trainer._progression_steps):
            app.processEvents()
            pitches = list(trainer._target_pitches)
            diag.log("MIDI_INPUT_SENT", f"progression[{step_idx}] pitches={pitches}")
            
            # Extra accidental note (20% chance per chord)
            if with_chaos and random.random() < 0.2:
                human_extra_note(hw, trainer, diag)
            
            for p in pitches:
                hw.midiNoteReceived.emit(p, True)
            app.processEvents()
            time.sleep(0.1)
            for p in pitches:
                hw.midiNoteReceived.emit(p, False)
            app.processEvents()
            time.sleep(0.8)
            app.processEvents()
        return

    # Default: chord, sustain_pedal, hands_together
    pitches = list(trainer._target_pitches)
    diag.log("MIDI_INPUT_SENT", f"pitches={pitches}")
    
    # For sustain_pedal, sometimes press pedal too late (25% chance)
    if ex_type == "sustain_pedal":
        if with_chaos and random.random() < 0.25:
            diag.log("HUMAN_CHAOS", "Pressing keys BEFORE pedal (wrong order)")
            for p in pitches:
                hw.midiNoteReceived.emit(p, True)
            app.processEvents()
            time.sleep(0.3)
            hw.sustainPedalChanged.emit(True)
        else:
            hw.sustainPedalChanged.emit(True)
            app.processEvents()
            time.sleep(0.05)
            for p in pitches:
                hw.midiNoteReceived.emit(p, True)
    else:
        # Optionally add an extra accidental note (20% chance)
        if with_chaos and random.random() < 0.2:
            human_extra_note(hw, trainer, diag)
        
        for p in pitches:
            hw.midiNoteReceived.emit(p, True)
    
    app.processEvents()
    
    hold_ms = trainer._required_hold_ms
    if hold_ms > 0:
        time.sleep(hold_ms / 1000.0 + 0.1)
        app.processEvents()

# ── 8. Main Diagnostic Runner ────────────────────────────────────────
def run_diagnostic():
    diag = DiagnosticLogger()
    diag.log("INIT", "Bootstrapping services...")
    
    import tempfile
    test_dir = Path(tempfile.mkdtemp())
    db = DatabaseManager(test_dir / "diagnostic.db")
    settings = SettingsService(db, project_root)
    curriculum = CurriculumService(db, project_root / "src" / "resources")
    trainer = ChordTrainerService(db, curriculum, settings)
    evaluation = MockEvaluationService()
    hw = MockHardwareService()
    gemini = GeminiService(settings)
    coordinator = AppCoordinator(gemini, evaluation, trainer, hw, settings)
    
    diag.log("INIT", "Services bootstrapped. Connecting to Gemini...")
    
    context = curriculum.get_curriculum_context()
    coordinator._sync_coach_settings()
    gemini.connect_service(
        context,
        voice=str(settings.coachVoice),
        brevity=str(settings.coachBrevity),
        personality=str(settings.coachPersonality)
    )
    
    ok, _ = wait_for_signal(gemini.connectionStatusChanged, timeout_ms=15000)
    if not ok or not gemini.connected:
        diag.log("ERROR", "Failed to connect to Gemini API")
        return diag.write_report(project_root / "tests" / "logs")
    
    diag.log("CONNECTED", "WebSocket connected to Gemini")
    
    # ── Hook up diagnostic signal listeners ──
    last_exercise_data = [None]
    speech_start_time = [0.0]
    chord_failed_count = [0]
    chord_success_this_round = [False]
    
    def on_exercise_received(data):
        diag.exercises_received += 1
        last_exercise_data[0] = data
        ex_type = data.get("exercise_type", "?")
        ex_name = data.get("exercise_name", "?")
        root = data.get("root_idx", "?")
        chord = data.get("chord_type_name", "?")
        diag.log("EXERCISE_RECEIVED", f"type={ex_type} | name={ex_name} | root={root} | chord={chord}")
    
    def on_ai_started():
        speech_start_time[0] = time.time()
        diag.log("AI_STARTED_SPEAKING")
    
    def on_ai_finished():
        duration_ms = (time.time() - speech_start_time[0]) * 1000 if speech_start_time[0] else 0
        diag.log("AI_FINISHED_SPEAKING", f"speech_duration={duration_ms:.0f}ms")
    
    def on_chord_success(name, latency):
        diag.exercises_completed += 1
        chord_success_this_round[0] = True
        diag.log("CHORD_SUCCESS", f"name={name} | latency={latency:.1f}ms")
    
    def on_chord_failed():
        chord_failed_count[0] += 1
        diag.log("CHORD_FAILED", f"total_failures={chord_failed_count[0]}")
    
    def on_performance_sent(report):
        preview = report[:80].replace('\n', ' ')
        diag.log("PERFORMANCE_SENT", f"{preview}...")
    
    def on_lesson_end(feedback):
        diag.log("LESSON_END", f"feedback={feedback[:80]}")
    
    gemini.exerciseReceived.connect(on_exercise_received)
    gemini.aiStartedSpeaking.connect(on_ai_started)
    gemini.aiFinishedSpeaking.connect(on_ai_finished)
    trainer.chordSuccess.connect(on_chord_success)
    trainer.chordFailed.connect(on_chord_failed)
    trainer.reportPerformance.connect(on_performance_sent)
    gemini.lessonEndReceived.connect(on_lesson_end)
    
    # ── Intercept print() to capture failsafe/lock messages ──
    _original_print = print
    _in_diagnostic_print = [False]  # Re-entry guard
    def diagnostic_print(*args, **kwargs):
        if _in_diagnostic_print[0]:
            _original_print(*args, **kwargs)
            return
        _in_diagnostic_print[0] = True
        try:
            msg = " ".join(map(str, args))
            if "Failsafe timer popped" in msg:
                diag.failsafe_fires += 1
                diag.log("FAILSAFE_FIRED", msg.strip())
            elif "AI finished turn but no exercise received" in msg:
                diag.dropped_tool_calls += 1
                diag.log("DROPPED_TOOL_CALL", msg.strip())
            elif "Sending nudge prompt to request set_exercise" in msg:
                diag.log("NUDGE_SENT", "Nudging AI to call set_exercise")
            elif "IGNORING _request_next_exercise because a request is already in flight" in msg:
                diag.stuck_locks += 1
                diag.log("STUCK_LOCK", msg.strip())
            _original_print(*args, **kwargs)
        finally:
            _in_diagnostic_print[0] = False
    
    import builtins
    builtins.print = diagnostic_print
    
    # ── Start the lesson ──
    diag.log("LESSON_START", "Calling start_lesson_plan()")
    trainer.start_lesson_plan()
    
    # ── Main event loop: react to exercises ──
    MAX_EXERCISES = 12
    TIMEOUT_MS = 45000
    lesson_ended = [False]
    lingering_pitches = []  # Keys still held from previous exercise
    
    def on_end(feedback):
        lesson_ended[0] = True
    gemini.lessonEndReceived.connect(on_end)
    
    exercises_played = 0
    
    while exercises_played < MAX_EXERCISES and not lesson_ended[0]:
        chord_success_this_round[0] = False
        
        # Wait for exercise to arrive
        diag.log("WAITING", f"Waiting for exercise #{exercises_played + 1}...")
        
        exercise_arrived = [False]
        def on_ex(data):
            exercise_arrived[0] = True
        gemini.exerciseReceived.connect(on_ex)
        
        deadline = time.time() + (TIMEOUT_MS / 1000.0)
        while not exercise_arrived[0] and not lesson_ended[0] and time.time() < deadline:
            app.processEvents()
            time.sleep(0.05)
        
        try:
            gemini.exerciseReceived.disconnect(on_ex)
        except Exception:
            pass
        
        if lesson_ended[0]:
            diag.log("LESSON_COMPLETE", "AI called end_lesson")
            break
        
        if not exercise_arrived[0]:
            diag.log("TIMEOUT", f"No exercise received after {TIMEOUT_MS/1000:.0f}s")
            if trainer._is_requesting_exercise:
                diag.stuck_locks += 1
                diag.log("STUCK_LOCK", "_is_requesting_exercise is True at timeout")
            break
        
        # ── CHAOS: Linger keys from previous exercise (40% chance) ──
        if lingering_pitches and random.random() < 0.4:
            diag.log("HUMAN_CHAOS", f"Still holding keys from last exercise: {lingering_pitches}")
            # They're already held — don't release them yet
        else:
            # Release any lingering keys
            for p in lingering_pitches:
                hw.midiNoteReceived.emit(p, False)
            lingering_pitches = []
            app.processEvents()
        
        # ── CHAOS: Play during AI speech (30% chance) ──
        if trainer._is_paused_for_speech and random.random() < 0.3:
            human_play_during_speech(hw, diag)
        
        # Wait for AI to finish speaking
        diag.log("WAITING", "Waiting for AI to finish speaking...")
        speech_deadline = time.time() + 30.0
        while trainer._is_paused_for_speech and time.time() < speech_deadline:
            app.processEvents()
            time.sleep(0.05)
            # CHAOS: Occasionally noodle during speech (10% per loop)
            if random.random() < 0.005:
                human_play_during_speech(hw, diag)
        
        if trainer._is_paused_for_speech:
            diag.log("WARN", "AI speech did not complete within 30s, forcing unpause")
            trainer._is_paused_for_speech = False
        
        # Release any lingering keys NOW (before attempting the real chord)
        if lingering_pitches:
            diag.log("HUMAN_CHAOS", f"Finally releasing lingered keys: {lingering_pitches}")
            for p in lingering_pitches:
                hw.midiNoteReceived.emit(p, False)
            lingering_pitches = []
            app.processEvents()
            time.sleep(0.2)
            app.processEvents()
        
        # Small settle delay
        time.sleep(0.2)
        app.processEvents()
        
        # Simulate MIDI input with sloppy human chaos
        if last_exercise_data[0]:
            simulate_correct_input(trainer, last_exercise_data[0], hw, diag, with_chaos=True)
        
        # Wait for result
        app.processEvents()
        time.sleep(0.3)
        app.processEvents()
        
        # If we didn't get success yet (wrong notes blocked it), retry cleanly
        if not chord_success_this_round[0] and last_exercise_data[0]:
            ex_type = last_exercise_data[0].get("exercise_type", "chord")
            if ex_type not in ("listen", "pentascale"):
                diag.log("HUMAN_RETRY", "First attempt didn't succeed, retrying cleanly")
                # Release everything first
                for p in list(trainer._active_pitches):
                    hw.midiNoteReceived.emit(p, False)
                app.processEvents()
                time.sleep(0.3)
                app.processEvents()
                # Play correct notes cleanly
                simulate_correct_input(trainer, last_exercise_data[0], hw, diag, with_chaos=False)
                app.processEvents()
                time.sleep(0.3)
                app.processEvents()
        
        # ── CHAOS: Decide whether to linger keys (for the next exercise) ──
        current_pitches = list(trainer._active_pitches)
        if current_pitches and random.random() < 0.35:
            lingering_pitches = human_linger_keys(hw, diag, current_pitches)
            # Release the ones that aren't lingering
            for p in current_pitches:
                if p not in lingering_pitches:
                    hw.midiNoteReceived.emit(p, False)
        else:
            # Clean release
            for p in list(trainer._active_pitches):
                hw.midiNoteReceived.emit(p, False)
            lingering_pitches = []
        
        if trainer._is_pedal_down:
            hw.sustainPedalChanged.emit(False)
        app.processEvents()
        
        # Wait for the _next_chord timer to fire
        time.sleep(1.0)
        app.processEvents()
        
        exercises_played += 1
    
    # ── Cleanup ──
    # Release any final lingering keys
    for p in lingering_pitches:
        hw.midiNoteReceived.emit(p, False)
    app.processEvents()
    
    builtins.print = _original_print
    diag.log("SHUTDOWN", "Disconnecting from Gemini...")
    gemini.disconnect_service()
    time.sleep(1.0)
    app.processEvents()
    
    # Add chaos stats to the report
    diag.events.append("")
    diag.events.append("--- HUMAN CHAOS STATS ---")
    chaos_events = [e for e in diag.events if "HUMAN_CHAOS" in e]
    diag.events.append(f"Total chaos events injected: {len(chaos_events)}")
    diag.events.append(f"Chord failures triggered: {chord_failed_count[0]}")
    diag.events.append(f"Retries needed: {len([e for e in diag.events if 'HUMAN_RETRY' in e])}")
    
    log_file = diag.write_report(project_root / "tests" / "logs")
    
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    return log_file

# ── Entry Point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    run_diagnostic()

