"""
ChordCoach Companion - Main Entry Point
NOTE: If your IDE reports missing imports for chordcoach_hw, PySide6, etc., 
ensure your environment is correctly configured. chordcoach_hw is a dynamic 
binary extension built in the 'build' directory.
"""
from PySide6.QtGui import QGuiApplication # type: ignore
from PySide6.QtQml import QQmlApplicationEngine # type: ignore
from PySide6.QtCore import QObject, Slot, Signal, Property, QTimer, Qt # type: ignore
import sys
import os
import time
import random
import ctypes
from PySide6.QtWebEngineQuick import QtWebEngineQuick # type: ignore
from pathlib import Path
from typing import cast

# --- Environment Bootstrap ---
# This must happen before we try to import chordcoach_hw or load the UI
import core.bootstrap as bootstrap
project_root, hw_bin_path, user_data_path, is_frozen = bootstrap.setup_env()

try:
    import chordcoach_hw # type: ignore
except ImportError as e:
    print(f"Warning: chordcoach_hw extension not found or failed to load: {e}")
    chordcoach_hw = None

from hardware.midi_hardware_service import MidiHardwareService

from logic.services.gemini_service import GeminiService # type: ignore
from logic.services.midi_ingestor import MidiIngestor # type: ignore
from logic.services.repertoire_crawler import RepertoireCrawler # type: ignore
from logic.services.database_manager import DatabaseManager # type: ignore
from logic.services.chord_trainer import ChordTrainerService # type: ignore
from logic.services.evaluation_service import EvaluationService # type: ignore
from logic.services.adaptive_engine import AdaptiveEngineService # type: ignore
from logic.services.settings_service import SettingsService # type: ignore
from logic.services.curriculum_service import CurriculumService # type: ignore
from logic.services.circle_of_fifths_service import CircleOfFifthsService # type: ignore
from logic.coordinators.app_coordinator import AppCoordinator # type: ignore

class AppState(QObject):
    midiNoteReceived = Signal(int, bool)
    aiTranscriptReceived = Signal(str)
    aiConnectedChanged = Signal(bool)
    midiConnectedChanged = Signal(bool)
    evalIntroPendingChanged = Signal(bool)
    archIntroPendingChanged = Signal(bool)
    isReconnectingChanged = Signal(bool)
    sustainPedalChanged = Signal(bool)
    
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager(user_data_path / "database" / "userdata.db")
        self.settings = SettingsService(self.db, user_data_path)
        self._gemini = GeminiService(self.settings)
        self._circle_of_fifths = CircleOfFifthsService()
        
        self.midi_ingestor = MidiIngestor()
        self.crawler = RepertoireCrawler()
        self.curriculum = CurriculumService(self.db, project_root / "src" / "resources")
        self.chord_trainer = ChordTrainerService(self.db, self.curriculum, self.settings)
        self.evaluation_engine = EvaluationService(self.db, project_root)
        self.adaptive_engine = AdaptiveEngineService(self.db, self.settings)
        
        # Initialize hardware service (handles C++ chordcoach_hw extension and ctypes rtmidi out)
        ll_lib_file = None
        try:
            lib_name = bootstrap._native_lib_name("rtmidi")
            if is_frozen:
                ll_lib_file = project_root / lib_name
            else:
                ll_lib_file = project_root / "build" / "_deps" / "rtmidi-build" / bootstrap._build_subdir() / lib_name
        except Exception as e:
            print(f"AppState: Pathing error for rtmidi: {e}")
            
        self.hw_service = MidiHardwareService(chordcoach_hw, ll_lib_file, midi_out_enabled=bool(self.settings.midiOutEnabled))
        self.coordinator = AppCoordinator(
            self._gemini, 
            self.evaluation_engine, 
            self.chord_trainer, 
            self.hw_service, 
            self.settings
        )
        
        # Connect Gemini signals to AppState/QML
        self._gemini.responseReceived.connect(self._on_ai_text)
        self._gemini.connectionStatusChanged.connect(self.aiConnectedChanged)
        
        # Forward coordinator signals to AppState so QML receives them
        self.coordinator.evalIntroPendingChanged.connect(self.evalIntroPendingChanged)
        self.coordinator.archIntroPendingChanged.connect(self.archIntroPendingChanged)
        self.coordinator.isReconnectingChanged.connect(self.isReconnectingChanged)
        
        # Connect Hardware signals to AppState/QML
        self.hw_service.connectionStatusChanged.connect(self.midiConnectedChanged)
        self.hw_service.midiNoteReceived.connect(self._circle_of_fifths.handle_midi_note)
        
        # Initialize the hardware layer
        self.hw_service.initialize()
                
        # Automatically connect to Gemini AI Coach on startup
        context = self.curriculum.get_curriculum_context()
        self.coordinator._sync_coach_settings()
        self._gemini.connect_service(
            context,
            voice=cast(str, self.settings.coachVoice),
            brevity=cast(str, self.settings.coachBrevity),
            personality=cast(str, self.settings.coachPersonality)
        )

    @Slot(bool)
    def _on_sustain_pedal_changed_bridge(self, is_down: bool):
        """Bridge hardware events to QML via Property signal."""
        self.sustainPedalChanged.emit(is_down)

    @Slot(str)
    def _on_ai_text(self, text: str):
        """Bounces text from background Gemini websockets loop onto the main UI thread."""
        preview = text[:50] # type: ignore
        print(f"AppState: AI text received, emitting to UI: {preview}...")
        self.aiTranscriptReceived.emit(text)

    # Expose the Coordinator explicitly to QML
    @Property(QObject, constant=True)
    def appCoordinator(self):
        return self.coordinator
    # Expose the GeminiService explicitly to QML
    @Property(QObject, constant=True)
    def gemini(self):
        return self._gemini

    @Property(QObject, constant=True)
    def circleOfFifths(self):
        return self._circle_of_fifths

    @Property(bool, notify=midiConnectedChanged)
    def midiConnected(self):
        return self.hw_service.is_connected

    @Property(bool, notify=aiConnectedChanged)
    def aiConnected(self):
        return self._gemini.connected

    @Property(bool, notify=evalIntroPendingChanged)
    def evalIntroPending(self):
        return self.coordinator.evalIntroPending

    @Property(bool, notify=archIntroPendingChanged)
    def archIntroPending(self):
        return self.coordinator.archIntroPending

    @Property(bool, notify=isReconnectingChanged)
    def isReconnecting(self):
        return self.coordinator.isReconnecting

    @Property(str, constant=True)
    def midiDeviceName(self):
        return self.hw_service.device_name

    @Property(bool, notify=sustainPedalChanged)
    def isSustainPedalDown(self):
        return self.hw_service._is_sustain_pedal_down

    @Property(QObject, constant=True)
    def chordTrainer(self):
        return self.chord_trainer
        
    @Property(QObject, constant=True)
    def evaluationEngine(self):
        return self.evaluation_engine

    @Property(QObject, constant=True)
    def adaptiveEngine(self):
        return self.adaptive_engine

    @Property(QObject, constant=True)
    def curriculumEngine(self):
        return self.curriculum

    @Property(QObject, constant=True)
    def settingsService(self):
        return self.settings
            
    @Slot(str)
    def fetch_song(self, query: str):
        print(f"AppState: UI requested song fetch for '{query}'")
        self.crawler.search_and_download(query)

def main():
    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    app_state = AppState()
    engine.rootContext().setContextProperty("appState", app_state)
    
    # Add UI components path
    engine.addImportPath(str(project_root / "src" / "ui" if not is_frozen else project_root / "ui"))

    if is_frozen:
        qml_file = project_root / "ui" / "main.qml"
    else:
        qml_file = project_root / "src" / "ui" / "main.qml"
    engine.load(os.fspath(qml_file))

    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
