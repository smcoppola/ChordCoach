"""
Application Flow Coordinator.
Responsible for orchestrating interactions between the AI, the Evaluation Engine, 
and the Chord Trainer so the main QML bridge (AppState) doesn't have to carry 
domain-specific bridging logic.
"""
from PySide6.QtCore import QObject, Slot, Signal, QTimer, Property # type: ignore

class AppCoordinator(QObject):
    evalIntroPendingChanged = Signal(bool)
    
    def __init__(self, gemini_service, eval_engine, chord_trainer, hw_service, settings):
        super().__init__()
        self.gemini = gemini_service
        self.evaluation = eval_engine
        self.chord_trainer = chord_trainer
        self.hw_service = hw_service
        self.settings = settings
        
        self._eval_intro_pending = False
        self._eval_audio_received = False
        self._lesson_plan_waiting = False
        self._is_reconnecting = False
        
        # --- Wire Hardware to Engines ---
        self.hw_service.midiNoteReceived.connect(self._dispatch_midi_note)
        self.hw_service.sustainPedalChanged.connect(self.chord_trainer.handle_pedal_event)
        
        # --- Wire AI to Chord Trainer ---
        self.chord_trainer.speakInstruction.connect(self.gemini.send_prompt)
        self.chord_trainer.lessonPlanGenerated.connect(self._on_lesson_plan_generated)
        
        # Play happy/sad tone when the lesson API connectivity check succeeds/fails
        self.chord_trainer.apiConnectivityChanged.connect(self._on_api_connectivity)
        
        # --- AI Connection State Handlers ---
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

    @Slot(int, bool)
    def _dispatch_midi_note(self, pitch: int, is_on: bool):
        """Route MIDI input to whoever is active."""
        if self.evaluation.isRunning:
            self.evaluation.handle_midi_note(pitch, is_on)
        else:
            self.chord_trainer.handle_midi_note(pitch, is_on)

    def _sync_coach_settings(self):
        """Push current voice configs to chord trainer context."""
        self.chord_trainer.coach_personality = self.settings.coachPersonality
        self.chord_trainer.coach_brevity = self.settings.coachBrevity

    @Slot(bool)
    def _on_ai_connected(self, connected: bool):
        if connected and self.hw_service.is_connected:
            self._is_reconnecting = False
            if not self.chord_trainer.isActive and not self.evaluation.isRunning:
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
    def _on_lesson_plan_generated(self):
        if self.evaluation.isRunning:
            print("Coordinator: Lesson plan generated but evaluation is running. Waiting...")
            self._lesson_plan_waiting = True
        else:
            print("Coordinator: Lesson plan generated. Activating now.")
            self.chord_trainer.activate_lesson_plan()

    @Slot()
    def _on_evaluation_finished(self):
        self._eval_intro_pending = False
        self.evalIntroPendingChanged.emit(False)
        if self._lesson_plan_waiting:
            print("Coordinator: Evaluation finished. Activating waiting lesson plan.")
            self._lesson_plan_waiting = False
            self.chord_trainer.activate_lesson_plan()
        elif self.gemini.connected and not self.chord_trainer.isActive:
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
                "[System Note]: This is a skill evaluation. Give a brief, 1-sentence welcome. "
                "Remind them to play the scrolling notes as they hit the green line. Wish them luck."
            )
            self.evaluation.startEvaluation(paused=True)
            QTimer.singleShot(10000, self._evaluation_safety_start)
        else:
            self.evaluation.startEvaluation(paused=False)

    @Slot()
    def startArchTutorialWithIntro(self):
        """Prompt the AI to explain the keyboard arches, used in onboarding phase 3."""
        if self.gemini.connected:
            self.gemini.send_prompt(
                "[System Note]: Onboarding Phase 3. Give a quick, friendly 1-sentence intro. "
                "Mention that green arches show half-steps between notes, and they should click one to see its name."
            )

    @Slot()
    def _evaluation_safety_start(self):
        if self._eval_intro_pending:
            print("Coordinator: AI intro timeout - resuming evaluation.")
            self._eval_intro_pending = False
            self.evalIntroPendingChanged.emit(False)
            self.evaluation.resume()

    @Slot()
    def _on_ai_finished_speaking(self):
        if self._eval_intro_pending:
            # Only start if we actually heard some audio
            if self._eval_audio_received:
                print("Coordinator: AI intro finished. Resuming evaluation.")
                self._eval_intro_pending = False
                self.evalIntroPendingChanged.emit(False)
                self.evaluation.resume()

    @Slot(bytes)
    def _on_ai_audio_received(self, data):
        if self._eval_intro_pending:
            self._eval_audio_received = True
