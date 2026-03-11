"""
Application Flow Coordinator.
Responsible for orchestrating interactions between the AI, the Evaluation Engine, 
and the Chord Trainer so the main QML bridge (AppState) doesn't have to carry 
domain-specific bridging logic.
"""
from PySide6.QtCore import QObject, Slot, Signal, QTimer, Property # type: ignore

class AppCoordinator(QObject):
    evalIntroPendingChanged = Signal(bool)
    archIntroPendingChanged = Signal(bool)
    isReconnectingChanged = Signal(bool)
    @Slot()
    def stopSession(self):
        """Stops whatever is currently active: Evaluation or Lesson."""
        if self.evaluation.isRunning:
            self.evaluation.stop()
        if self.chord_trainer.isActive:
            self.chord_trainer.stop_session()
        
        # We need to silence any audio that the Gemini model is currently playing back
        # and clear any pending locks so a future session start isn't blocked.
        if self.gemini.connected:
            self.gemini.stop_current_audio()
            self.gemini.clear_exercise_pending()
            
        self._eval_intro_pending = False
        self._arch_intro_pending = False
        self.evalIntroPendingChanged.emit(False)
        self.archIntroPendingChanged.emit(False)
        
    def __init__(self, gemini_service, eval_engine, chord_trainer, hw_service, settings):
        super().__init__()
        self.gemini = gemini_service
        self.evaluation = eval_engine
        self.chord_trainer = chord_trainer
        self.hw_service = hw_service
        self.settings = settings
        
        self._eval_intro_pending = False
        self._eval_audio_received = False
        self._arch_intro_pending = False
        self._is_reconnecting = False
        
        # --- Wire Hardware to Engines ---
        self.hw_service.midiNoteReceived.connect(self._dispatch_midi_note)
        self.hw_service.sustainPedalChanged.connect(self.chord_trainer.handle_pedal_event)
        
        # --- Wire AI ↔ Chord Trainer (Single-Model Architecture) ---
        # Lesson flow: trainer requests → coordinator sends to gemini → gemini tools → trainer receives
        self.chord_trainer.requestLessonStart.connect(self.gemini.send_prompt)
        self.chord_trainer.reportPerformance.connect(self.gemini.clear_exercise_pending)
        self.chord_trainer.reportPerformance.connect(self.gemini.send_prompt)
        self.chord_trainer.exerciseRequestUnlocked.connect(self.gemini.clear_exercise_pending)
        self.chord_trainer.speakInstruction.connect(self.gemini.send_prompt)
        self.chord_trainer.speakBrief.connect(self.gemini.send_prompt)  # Non-blocking commentary (no pause)
        self.gemini.exerciseReceived.connect(self._on_exercise_received)
        self.gemini.lessonEndReceived.connect(self._on_lesson_end_received)
        
        # Play happy/sad tone when the lesson API connectivity check succeeds/fails
        self.chord_trainer.apiConnectivityChanged.connect(self._on_api_connectivity)
        
        # --- AI Connection State Handlers ---
        self.gemini.aiStartedSpeaking.connect(self.chord_trainer.pause_for_speech)
        self.gemini.aiFinishedSpeaking.connect(self.chord_trainer.resume_lesson)
        self.gemini.aiFinishedSpeaking.connect(self._on_ai_finished_speaking)
        self.gemini.connectionStatusChanged.connect(self._on_ai_connected)
        self.gemini.reconnecting.connect(self._on_ai_reconnecting)
        self.gemini.audioDataReceived.connect(self._on_ai_audio_received)
        
        # --- Wire Engines together ---
        self.evaluation.metronomeTick.connect(self.hw_service.play_metronome_tick)
        self.chord_trainer.midiOutRequested.connect(self.hw_service.play_chord_preview)
        self.chord_trainer.metronomeTick.connect(self._on_trainer_metronome)
        self.evaluation.evaluationFinished.connect(self._on_evaluation_finished)

    @Property(bool, notify=evalIntroPendingChanged) # type: ignore
    def evalIntroPending(self):
        return self._eval_intro_pending

    @Property(bool, notify=archIntroPendingChanged) # type: ignore
    def archIntroPending(self):
        return self._arch_intro_pending

    @Property(bool, notify=isReconnectingChanged) # type: ignore
    def isReconnecting(self):
        return self._is_reconnecting

    @Slot(int, bool)
    def _dispatch_midi_note(self, pitch: int, is_on: bool):
        """Route MIDI input to whoever is active."""
        if self.evaluation.isRunning:
            self.evaluation.handle_midi_note(pitch, is_on)
        else:
            self.chord_trainer.handle_midi_note(pitch, is_on)

    @Slot(dict)
    def _on_exercise_received(self, exercise_data: dict):
        """Guard: only forward tool-call exercises to the trainer if evaluation is NOT running."""
        if self.evaluation.isRunning or self._eval_intro_pending:
            print(f"Coordinator: Ignoring set_exercise during evaluation — {exercise_data.get('exercise_name', '?')}")
            self.gemini.clear_exercise_pending()  # Prevent deadlock from rejected exercise
            return
        self.chord_trainer.receive_exercise(exercise_data)

    @Slot(str)
    def _on_lesson_end_received(self, feedback: str):
        """Guard: only forward lesson-end to the trainer if evaluation is NOT running."""
        if self.evaluation.isRunning or self._eval_intro_pending:
            print("Coordinator: Ignoring end_lesson during evaluation.")
            return
        self.chord_trainer.receive_lesson_end(feedback)

    def _sync_coach_settings(self):
        """Push current voice configs to chord trainer context."""
        self.chord_trainer.coach_personality = self.settings.coachPersonality
        self.chord_trainer.coach_brevity = self.settings.coachBrevity

    @Slot(bool)
    def _on_ai_connected(self, connected: bool):
        if connected and self.hw_service.is_connected:
            was_reconnecting = self._is_reconnecting
            self._is_reconnecting = False
            self.isReconnectingChanged.emit(False)
            
            # If we just reconnected during an active lesson, re-send context
            if was_reconnecting and self.chord_trainer.isActive and self.chord_trainer.isLessonMode:
                print("Coordinator: Reconnected during active lesson — re-sending context.")
                self._sync_coach_settings()
                resume_prompt = self.chord_trainer.get_resume_context()
                self.gemini.send_prompt(resume_prompt)
            elif not self.chord_trainer.isActive and not self.evaluation.isRunning:
                self._sync_coach_settings()
        elif not connected and self.hw_service.is_connected:
            if not self._is_reconnecting:
                self.hw_service.play_sad_tone()
    
    @Slot(bool)
    def _on_api_connectivity(self, confirmed: bool):
        if confirmed:
            self.hw_service.play_happy_tone()
        else:
            self.hw_service.play_sad_tone()
    
    @Slot(int, int)
    def _on_ai_reconnecting(self, attempt: int, max_attempts: int):
        self._is_reconnecting = True
        self.isReconnectingChanged.emit(True)
        print(f"Coordinator: Gemini is reconnecting ({attempt}/{max_attempts})...")
        self.hw_service.play_reconnect_ping()

    @Slot()
    def _on_trainer_metronome(self):
        """Map logical beat metrics from the trainer to standard 1..4 ticks for the hardware service."""
        beat_num = getattr(self.chord_trainer, '_pentascale_beat_count', 0)
        measure_beat = (beat_num % 4)
        if measure_beat == 0:
            measure_beat = 4
        if beat_num < 0:
            logical_beat = 4 + beat_num + 1 
        else:
            logical_beat = (beat_num % 4) + 1
        self.hw_service.play_metronome_tick(logical_beat)

    @Slot()
    def _on_evaluation_finished(self):
        self._eval_intro_pending = False
        self.evalIntroPendingChanged.emit(False)
        # After evaluation, auto-start a lesson ONLY if onboarding is already done.
        # During onboarding, the user still has Results → Arch Tutorial phases to go through.
        if not self.settings.hasCompletedOnboarding:
            print("Coordinator: Evaluation finished during onboarding — skipping auto lesson start.")
            return
        if self.gemini.connected and not self.chord_trainer.isActive:
            print("Coordinator: Evaluation finished. Starting new lesson plan generation.")
            self._sync_coach_settings()
            self.chord_trainer.start_lesson_plan()

    # --- QML Exposed Orchestration Actions ---
    
    @Slot()
    def startEvaluationWithIntro(self):
        """Send a spoken intro to the AI, then start the evaluation after it finishes speaking."""
        if self.gemini.connected:
            self._eval_intro_pending = True
            self._eval_audio_received = False
            self.evalIntroPendingChanged.emit(True)
            self.gemini.send_prompt(
                "<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>\nSKILL EVALUATION MODE — this is NOT a lesson. "
                "Say ONE short sentence welcoming the student to the skill check and reminding them "
                "to play the scrolling notes as they hit the green line. Wish them luck. "
                "Then STOP TALKING. Do NOT call any tools. Do NOT discuss exercises, chords, or lessons. "
                "Your only job right now is the welcome sentence, then silence.\n</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"
            )
            self.evaluation.startEvaluation(paused=True)
            QTimer.singleShot(10000, self._evaluation_safety_start)
        else:
            self.evaluation.startEvaluation(paused=False)

    @Slot()
    def startArchTutorialWithIntro(self):
        """Prompt the AI to explain the keyboard arches, used in onboarding phase 3."""
        if self.gemini.connected:
            self._arch_intro_pending = True
            self.archIntroPendingChanged.emit(True)
            self.gemini.send_prompt(
                "<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>\nOnboarding Phase 3. Give a quick, friendly 1-sentence intro. "
                "Mention that green arches show half-steps between notes, and they should click one to see its name. "
                "Then STOP TALKING. Do NOT call any tools. Do NOT discuss exercises or lessons.\n</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"
            )
            QTimer.singleShot(10000, self._arch_tutorial_safety_start)
        else:
            # No AI connected — clear immediately so QML shows content right away
            self._arch_intro_pending = False
            self.archIntroPendingChanged.emit(False)

    @Slot()
    def _evaluation_safety_start(self):
        if self._eval_intro_pending:
            print("Coordinator: AI intro timeout - resuming evaluation.")
            self._eval_intro_pending = False
            self.evalIntroPendingChanged.emit(False)
            self.evaluation.resume()

    @Slot()
    def _arch_tutorial_safety_start(self):
        if self._arch_intro_pending:
            print("Coordinator: Arch intro timeout - showing tutorial.")
            self._arch_intro_pending = False
            self.archIntroPendingChanged.emit(False)

    @Slot()
    def _on_ai_finished_speaking(self):
        if self._eval_intro_pending:
            # Only start if we actually heard some audio
            if self._eval_audio_received:
                print("Coordinator: AI intro finished. Resuming evaluation.")
                self._eval_intro_pending = False
                self.evalIntroPendingChanged.emit(False)
                self.evaluation.resume()
        if self._arch_intro_pending:
            print("Coordinator: Arch intro finished. Showing tutorial.")
            self._arch_intro_pending = False
            self.archIntroPendingChanged.emit(False)

    @Slot(bytes)
    def _on_ai_audio_received(self, data):
        if self._eval_intro_pending:
            self._eval_audio_received = True
        
        # If the chord trainer is still loading, update status to show coach is speaking
        if self.chord_trainer.isLoading:
            self.chord_trainer._loading_status_text = "LISTEN TO YOUR COACH..."
            self.chord_trainer.loadingStatusChanged.emit()
