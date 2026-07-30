"""
ChordCoach Companion - Main Entry Point
NOTE: If your IDE reports missing imports for chordcoach_hw, PySide6, etc., 
ensure your environment is correctly configured. chordcoach_hw is a dynamic 
binary extension built in the 'build' directory.
"""
from PySide6.QtGui import QGuiApplication, QFontDatabase # type: ignore
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
# Diagnostic path logging for frozen build troubleshooting
if getattr(sys, 'frozen', False):
    print(f"--- FROZEN DIAGNOSTICS ---")
    meipass = getattr(sys, '_MEIPASS', '')
    print(f"sys.executable: {sys.executable}")
    print(f"sys._MEIPASS: {meipass}")
    
    # In PyInstaller 6+, _MEIPASS often points directly to the _internal folder
    # We ensure either the root or the _internal folder (whichever contains our packages) is in path
    if meipass:
        # Standard approach: check if we are in the collection root or already inside _internal
        if meipass.endswith('_internal') or os.path.exists(os.path.join(meipass, 'core')):
            # We are already in the folder that contains our packages
            if meipass not in sys.path:
                sys.path.insert(0, meipass)
        else:
            # We are in the root, check if _internal exists
            internal_dir = os.path.join(meipass, '_internal')
            if os.path.exists(internal_dir) and internal_dir not in sys.path:
                sys.path.insert(0, internal_dir)
                print(f"Added to sys.path: {internal_dir}")
                
    print(f"sys.path: {sys.path}")
    print(f"--------------------------")

# This must happen before we try to import chordcoach_hw or load the UI
import core.bootstrap as bootstrap

project_root, hw_bin_path, user_data_path, is_frozen = bootstrap.setup_env()

# --- Persistent Logging ---
# Redirect stdout/stderr to a log file so frozen macOS builds produce
# inspectable output even without a terminal attached.
bootstrap.setup_logging(user_data_path)
print(f"ChordCoach starting — root={project_root}, frozen={is_frozen}")
print(f"sys.path[0]: {sys.path[0]}")

try:
    import chordcoach_hw # type: ignore
    print("chordcoach_hw C++ extension loaded successfully.")
except ImportError as e:
    print(f"Warning: chordcoach_hw extension not found or failed to load: {e}")
    chordcoach_hw = None

from hardware.midi_hardware_service import MidiHardwareService

from logic.services.gemini_service import GeminiService # type: ignore
from logic.services.repertoire_crawler import RepertoireCrawler # type: ignore
from logic.services.database_manager import DatabaseManager # type: ignore
from logic.services.chord_trainer import ChordTrainerService # type: ignore
from logic.services.evaluation_service import EvaluationService # type: ignore
from logic.services.settings_service import SettingsService # type: ignore
from logic.services.curriculum_service import CurriculumService # type: ignore
from logic.services.metronome_service import MetronomeService # type: ignore
from logic.services.circle_of_fifths_service import CircleOfFifthsService # type: ignore
from logic.services.music21_service import Music21Service # type: ignore
from logic.services.playback_service import PlaybackService # type: ignore
from logic.coordinators.app_coordinator import AppCoordinator # type: ignore
from ui.notation_view import NotationView

class AppState(QObject):
    midiNoteReceived = Signal(int, bool)
    aiTranscriptReceived = Signal(str)
    aiConnectedChanged = Signal(bool)
    midiConnectedChanged = Signal(bool)
    midiInitialSearchDoneChanged = Signal(bool)
    evalIntroPendingChanged = Signal(bool)
    archIntroPendingChanged = Signal(bool)
    isReconnectingChanged = Signal(bool)
    sustainPedalChanged = Signal(bool)
    
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager(user_data_path / "database" / "userdata.db")
        self.settings = SettingsService(self.db, user_data_path)
        self.settings.setParent(self)
        
        self._gemini = GeminiService(self.settings)
        self._gemini.setParent(self)
        
        self._circle_of_fifths = CircleOfFifthsService()
        self._circle_of_fifths.setParent(self)
        
        self.crawler = RepertoireCrawler()
        self.curriculum = CurriculumService(self.db, project_root / "src" / "resources")
        self.curriculum.setParent(self)
        
        self._metronome = MetronomeService()
        self._metronome.setParent(self)
        
        self.music21_service = Music21Service(project_root)
        self.music21_service.setParent(self)
        
        self.chord_trainer = ChordTrainerService(self.db, self.curriculum, self.settings, self.music21_service)
        self.chord_trainer.set_metronome(self._metronome)
        self.chord_trainer.setParent(self)

        # Library view needs mastery stats and the "song currently in play" guard
        self.music21_service.set_database(self.db)
        self.music21_service.set_chord_trainer(self.chord_trainer)
        
        self.evaluation_engine = EvaluationService(self.db, project_root)
        self.evaluation_engine.setParent(self)
        
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
            
        self.hw_service = MidiHardwareService(chordcoach_hw, ll_lib_file, midi_out_enabled=bool(self.settings.midiOutEnabled)) # type: ignore
        self.hw_service.setParent(self)
        
        self.playback_service = PlaybackService(self.hw_service)
        self.playback_service.setParent(self)
        self.chord_trainer.set_playback_service(self.playback_service)
        
        self.coordinator = AppCoordinator(
            self._gemini, 
            self.evaluation_engine, 
            self.chord_trainer, 
            self.hw_service, 
            self.settings,
            self._circle_of_fifths
        )
        self.coordinator.setParent(self)
        
        # Connect Gemini signals to AppState/QML
        self._gemini.responseReceived.connect(self._on_ai_text)
        self._gemini.connectionStatusChanged.connect(self.aiConnectedChanged)
        
        # Forward coordinator signals to AppState so QML receives them
        self.coordinator.evalIntroPendingChanged.connect(self.evalIntroPendingChanged)
        self.coordinator.archIntroPendingChanged.connect(self.archIntroPendingChanged)
        self.coordinator.isReconnectingChanged.connect(self.isReconnectingChanged)
        self.coordinator.theoryVisualUpdated.connect(self._circle_of_fifths.set_tutorial_state_v2)
        
        # Connect Hardware signals to AppState/QML
        self.hw_service.connectionStatusChanged.connect(self.midiConnectedChanged)
        self.hw_service.initialSearchComplete.connect(self._on_midi_initial_search_complete)
        self.chord_trainer.midiOutRequested.connect(self.hw_service.play_chord_preview)
        
        # NOTE: Hardware initialisation and AI connection are deliberately
        # deferred until after the QML engine has loaded the UI.  On macOS,
        # calling CoreMIDI / CoreAudio APIs before the run-loop is active can
        # cause the application to hang on launch (the Dock icon bounces
        # forever).  See deferred_start() below.
        print("AppState.__init__ complete - hardware init deferred.")

    @Slot()
    def deferred_start(self):
        """Called ~100 ms after the QML engine has loaded the UI.

        This ensures the Qt event loop is running before we touch native
        hardware APIs (CoreMIDI, CoreAudio, PortAudio) which on macOS
        require an active run-loop to function correctly.
        """
        print("AppState.deferred_start: Initialising hardware (async)…")
        self.hw_service.initialize_async()

        print("AppState.deferred_start: Connecting to Gemini AI Coach…")
        context = self.curriculum.get_curriculum_context()
        self.coordinator._sync_coach_settings()
        self._gemini.connect_service(
            context,
            voice=cast(str, self.settings.coachVoice),
            brevity=cast(str, self.settings.coachBrevity),
            personality=cast(str, self.settings.coachPersonality)
        )
        print("AppState.deferred_start: Done.")

    @Slot()
    def _on_midi_initial_search_complete(self):
        self.midiInitialSearchDoneChanged.emit(True)

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

    @Property(bool, notify=midiInitialSearchDoneChanged)
    def midiInitialSearchDone(self):
        return self.hw_service._initial_search_done

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
    def curriculumEngine(self):
        return self.curriculum

    @Property(QObject, constant=True)
    def settingsService(self):
        return self.settings

    @Property(QObject, constant=True)
    def metronome(self):
        return self._metronome
        
    @Property(QObject, constant=True)
    def music21Service(self):
        return self.music21_service

    @Property(QObject, constant=True)
    def playback(self):
        return self.playback_service
            
    @Slot(str)
    def fetch_song(self, query: str):
        print(f"AppState: UI requested song fetch for '{query}'")
        self.crawler.search_and_download(query)

def main():
    print("main(): Initialising QtWebEngine…")
    QtWebEngineQuick.initialize()
    
    from PySide6.QtQml import qmlRegisterType
    qmlRegisterType(NotationView, "ChordCoach", 1, 0, "NotationView") # type: ignore
    
    app = QGuiApplication(sys.argv)
    app.setApplicationName("ChordCoach")
    app.setOrganizationName("ChordCoach")
    print("main(): QGuiApplication created (Name: CoachCoach).")

    # Register bundled fonts so QML can render them natively without warnings
    font_dir = project_root / "src" / "resources" / "fonts"
    if font_dir.exists():
        for font_ext in ["*.ttf", "*.otf", "*.woff2"]:
            for font_file in font_dir.glob(font_ext):
                print(f"main(): Registering font {font_file.name}")
                QFontDatabase.addApplicationFont(os.fspath(font_file))

    engine = QQmlApplicationEngine()

    print("main(): Creating AppState…")
    app_state = AppState()
    engine.rootContext().setContextProperty("appState", app_state)

    # Add UI components path
    engine.addImportPath(str(project_root / "src" / "ui" if not is_frozen else project_root / "ui"))

    if is_frozen:
        qml_file = project_root / "ui" / "main.qml"
    else:
        qml_file = project_root / "src" / "ui" / "main.qml"

    print(f"main(): Loading QML from {qml_file}…")
    engine.load(os.fspath(qml_file))

    if not engine.rootObjects():
        print("main(): FATAL — QML engine produced no root objects!")
        sys.exit(-1)

    # ── Deferred hardware & AI initialisation ──
    # Schedule the heavy hardware/network init to run AFTER the event loop
    # has started and the UI window is on screen.  This prevents the macOS
    # launch hang caused by CoreMIDI/CoreAudio calls before the run-loop
    # is active. On Windows, this also gives the OS a moment to release
    # MIDI ports from any previous process.
    print("main(): Scheduling deferred_start in 250 ms…")
    QTimer.singleShot(250, app_state.deferred_start)

    print("main(): Entering event loop.")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
