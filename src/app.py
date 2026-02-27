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
# --- Platform Helpers ---
def _native_lib_name(base: str) -> str:
    """Return the platform-specific shared library filename."""
    if sys.platform == "win32":
        return f"{base}.dll"
    elif sys.platform == "darwin":
        return f"lib{base}.dylib"
    else:  # Linux / other POSIX
        return f"lib{base}.so"

def _build_subdir() -> str:
    """CMake multi-config generators (MSVC) put binaries in Release/; single-config (Make/Ninja) don't."""
    return "Release" if sys.platform == "win32" else ""

# --- Frozen vs Dev Environment ---
if getattr(sys, 'frozen', False):
    bundle_dir = Path(sys._MEIPASS)
    project_root = bundle_dir
    hw_bin_path = bundle_dir
    native_lib_dir = bundle_dir
    # Explicitly point to QtWebEngineProcess for some PySide6 environments
    if sys.platform == "win32":
        os.environ["QTWEBENGINEPROCESS_PATH"] = str(bundle_dir / "PySide6" / "QtWebEngineProcess.exe")
    elif sys.platform == "darwin":
        webengine = bundle_dir / "PySide6" / "Qt" / "lib" / "QtWebEngineCore.framework" / "Helpers" / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess"
        if webengine.exists():
            os.environ["QTWEBENGINEPROCESS_PATH"] = str(webengine)
else:
    project_root = Path(__file__).parent.parent
    hw_bin_path = project_root / "build" / "src" / "hardware" / _build_subdir()
    native_lib_dir = None  # Resolved per-platform below

# Add local paths for imports
sys.path.append(str(hw_bin_path))
sys.path.append(str(project_root / "src"))

# Add native library search paths (platform-specific)
if sys.platform == "win32":
    if native_lib_dir:
        os.add_dll_directory(str(native_lib_dir))
    else:
        dll_paths = [
            project_root / "build" / "_deps" / "rtmidi-build" / _build_subdir(),
            project_root / "build" / "_deps" / "portaudio-build" / _build_subdir()
        ]
        for p in dll_paths:
            if p.exists():
                os.add_dll_directory(str(p))
else:
    # macOS / Linux: add library paths to environment so the dynamic linker can find them
    env_var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
    if native_lib_dir:
        extra_paths = [str(native_lib_dir)]
    else:
        extra_paths = [
            str(project_root / "build" / "_deps" / "rtmidi-build" / _build_subdir()),
            str(project_root / "build" / "_deps" / "portaudio-build" / _build_subdir())
        ]
    existing = os.environ.get(env_var, "")
    os.environ[env_var] = os.pathsep.join(extra_paths + ([existing] if existing else []))

try:
    import chordcoach_hw # type: ignore
except ImportError as e:
    print(f"Warning: chordcoach_hw extension not found or failed to load: {e}")
    chordcoach_hw = None

class LowLevelMidiOutput:
    """Uses ctypes to call the rtmidi shared library directly for MIDI output (cross-platform)."""
    def __init__(self, dll_path):
        try:
            self.dll = ctypes.CDLL(str(dll_path))
            
            # Setup function signatures
            self.dll.rtmidi_out_create_default.restype = ctypes.c_void_p
            self.dll.rtmidi_get_port_count.argtypes = [ctypes.c_void_p]
            self.dll.rtmidi_get_port_count.restype = ctypes.c_int
            self.dll.rtmidi_get_port_name.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
            self.dll.rtmidi_get_port_name.restype = ctypes.c_int
            self.dll.rtmidi_open_port.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
            self.dll.rtmidi_out_send_message.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
            
            self.midi_out = self.dll.rtmidi_out_create_default()
            self._port_open = False
        except Exception as e:
            print(f"LowLevelMidiOutput Init Error: {e}")
            self.midi_out = None

    def get_port_names(self):
        if not self.midi_out: return []
        names = []
        count = self.dll.rtmidi_get_port_count(self.midi_out)
        
        buf = ctypes.create_string_buffer(256)
        for i in range(count):
            buf_len = ctypes.c_int(256)
            self.dll.rtmidi_get_port_name(self.midi_out, i, buf, ctypes.byref(buf_len))
            names.append(buf.value.decode('utf-8'))
        return names

    def open_port(self, index):
        if not self.midi_out: return
        self.dll.rtmidi_open_port(self.midi_out, index, b"ChordCoachOutput")
        self._port_open = True

    def send_message(self, message: list[int]):
        if not self._port_open or not self.midi_out: return
        msg_type = ctypes.c_ubyte * len(message)
        msg_array = msg_type(*message)
        self.dll.rtmidi_out_send_message(self.midi_out, msg_array, len(message))

from logic.services.gemini_service import GeminiService # type: ignore
from logic.services.midi_ingestor import MidiIngestor # type: ignore
from logic.services.repertoire_crawler import RepertoireCrawler # type: ignore
from logic.services.database_manager import DatabaseManager # type: ignore
from logic.services.chord_trainer import ChordTrainerService # type: ignore
from logic.services.evaluation_service import EvaluationService # type: ignore
from logic.services.adaptive_engine import AdaptiveEngineService # type: ignore
from logic.services.settings_service import SettingsService # type: ignore
from logic.services.curriculum_service import CurriculumService # type: ignore

class AppState(QObject):
    midiNoteReceived = Signal(int, bool)
    aiTranscriptReceived = Signal(str)
    aiConnectedChanged = Signal(bool)
    evalIntroPendingChanged = Signal(bool)
    
    def __init__(self):
        super().__init__()
        self._ai_connected = False
        self._eval_intro_pending = False
        self._eval_audio_received = False
        self._gemini = GeminiService()
        self.midi_ingestor = MidiIngestor()
        self.crawler = RepertoireCrawler()
        self.db = DatabaseManager(project_root / "database" / "userdata.db")
        self.settings = SettingsService(self.db, project_root)
        self.curriculum = CurriculumService(self.db, project_root / "src" / "resources")
        self.chord_trainer = ChordTrainerService(self.db, self.curriculum)
        self.evaluation_engine = EvaluationService(self.db, project_root)
        self.adaptive_engine = AdaptiveEngineService(self.db)
        self._lesson_plan_waiting = False
        
        # Low-level MIDI output for hardware feedback
        self._ll_midi_out = None
        try:
            lib_name = _native_lib_name("rtmidi")
            if getattr(sys, 'frozen', False):
                lib_file = project_root / lib_name
            else:
                lib_file = project_root / "build" / "_deps" / "rtmidi-build" / _build_subdir() / lib_name

            if lib_file.exists():
                print(f"AppState: Initializing LowLevelMidiOutput with {lib_file}")
                self._ll_midi_out = LowLevelMidiOutput(lib_file)
            else:
                print(f"AppState: {lib_name} not found at {lib_file}")
        except Exception as e:
            print(f"AppState: LowLevelMidiOutput initialization error: {e}")
            self._ll_midi_out = None
        
        # Connect Gemini text stream to QML
        self._gemini.responseReceived.connect(self._on_ai_text)
        self._gemini.audioDataReceived.connect(self._on_ai_audio_received)
        
        # Dispatch MIDI events to the appropriate engine on the main thread
        self.midiNoteReceived.connect(self._dispatch_midi_note)
        
        # Connect the chord trainer to Gemini Live so it can speak instructions
        self.chord_trainer.speakInstruction.connect(self._gemini.send_prompt)
        self.chord_trainer.lessonPlanGenerated.connect(self._on_lesson_plan_generated)
        self.chord_trainer.midiOutRequested.connect(self._on_midi_out_requested)
        
        # Connect AI audio completion back to chord trainer to resume lesson
        self._gemini.aiFinishedSpeaking.connect(self.chord_trainer.resume_lesson)
        self._gemini.aiFinishedSpeaking.connect(self._on_ai_finished_speaking)
        
        # Play happy/sad tone when the lesson API connectivity check succeeds/fails
        # Must use QueuedConnection since the signal is emitted from a background thread
        self.chord_trainer.apiConnectivityChanged.connect(self._on_api_connectivity, Qt.QueuedConnection)
        
        # Trigger welcome riff when AI connects
        self._gemini.connectionStatusChanged.connect(self._on_ai_connected)
        self._gemini.reconnecting.connect(self._on_ai_reconnecting)
        self._is_reconnecting = False
        
        # Connect metronome ticks from evaluation to MIDI clicks
        self.evaluation_engine.metronomeTick.connect(self._on_metronome_tick)
        
        # When evaluation finishes, start the lesson plan
        self.evaluation_engine.evaluationFinished.connect(self._on_evaluation_finished)
        
        # Hardware handlers with explicit guards for linting
        self.hw_midi = None
        self.hw_audio = None
        self._midi_connected = False
        self._midi_device_name = "Not Connected"
        
        if chordcoach_hw:
            # 1. MIDI Initialization
            try:
                m_handler = chordcoach_hw.MidiHandler()
                ports = m_handler.getPortNames()
                if ports:
                    m_handler.openPort(0) # Default to first input port for evaluation
                    m_handler.setCallback(self._on_midi_data)
                    self.hw_midi = m_handler
                    self._midi_connected = True
                    self._midi_device_name = ports[0]
                    print(f"MIDI Input Hardware initialized: {ports[0]}")
                    
                    # 2. Match Output Port
                    if self._ll_midi_out and hasattr(self._ll_midi_out, 'get_port_names'):
                        try:
                            out_names = self._ll_midi_out.get_port_names()
                            target = ports[0]
                            # Try matching first word or significant part
                            target_base = target.split(' ')[0] if ' ' in target else target
                            paired = False
                            for i, name in enumerate(out_names):
                                if target_base in name and "Synth" not in name:
                                    if self._ll_midi_out: # Null check for _ll_midi_out
                                        self._ll_midi_out.open_port(i)
                                    print(f"LowLevel Paired MIDI Output: {name}")
                                    paired = True
                                    break
                            
                            # Fallback: If no match and only one output exists (likely the right one)
                            if not paired and len(out_names) == 1:
                                if self._ll_midi_out:
                                    self._ll_midi_out.open_port(0)
                                print(f"LowLevel MIDI Output Fallback: {out_names[0]}")
                                paired = True
                            elif not paired:
                                print(f"LowLevel MIDI Output Pairing Failed for {target}. Found: {out_names}")
                        except Exception as oe:
                            print(f"MIDI Output Pairing Error: {oe}")
                    else:
                        print(f"AppState: Low-level MIDI output skipped (Enabled: {self._ll_midi_out is not None})")
                    
                    # Play auditory confirmation
                    self._play_startup_riff()
                else:
                    print("No MIDI ports found. Hardware MIDI feedback disabled.")
            except Exception as e:
                print(f"MIDI Hardware Init Error: {e}")
                
        # Automatically connect to Gemini AI Coach on startup
        context = self.curriculum.get_curriculum_context()
        self._sync_coach_settings()
        self._gemini.connect_service(
            context,
            voice=self.settings.coachVoice,
            brevity=self.settings.coachBrevity,
            personality=self.settings.coachPersonality
        )

    def _sync_coach_settings(self):
        """Push current settings to chord trainer."""
        self.chord_trainer.coach_personality = self.settings.coachPersonality
        self.chord_trainer.coach_brevity = self.settings.coachBrevity

    @Slot(bool)
    def _on_ai_connected(self, connected: bool):
        self._ai_connected = connected
        self.aiConnectedChanged.emit(connected)
        if connected and self.hw_midi:
            self._is_reconnecting = False
            # Only start a new lesson if one isn't already in progress and evaluation isn't running
            if not self.chord_trainer.isActive and not self.evaluation_engine.isRunning:
                self._sync_coach_settings()
                self.chord_trainer.start_lesson_plan()
        elif not connected and self.hw_midi:
            # Only play sad tone if all reconnect attempts are exhausted
            if not self._is_reconnecting:
                self._play_sad_tone()
    
    @Slot(bool)
    def _on_api_connectivity(self, confirmed: bool):
        """Plays happy/sad tone when the lesson API ping succeeds or fails."""
        if confirmed:
            self._play_happy_tone()
        else:
            self._play_sad_tone()
    
    @Slot(int, int)
    def _on_ai_reconnecting(self, attempt: int, max_attempts: int):
        self._is_reconnecting = True
        print(f"AppState: AI reconnecting ({attempt}/{max_attempts})...")
        # Play a subtle single-note ping on each attempt
        if self._ll_midi_out:
            self._ll_midi_out.send_message([0x90, 72, 40])  # Soft C5
            QTimer.singleShot(200, lambda: self._ll_midi_out.send_message([0x80, 72, 0]) if self._ll_midi_out else None)
            
    def _play_startup_riff(self):
        """Plays a cheerful C Maj9 arpeggio via LowLevel MIDI with natural sustain."""
        if not self._ll_midi_out: return
        
        # Sustain ON to allow notes to ring out
        self._ll_midi_out.send_message([0xB0, 64, 127])
        
        notes = [60, 64, 67, 71, 74]
        for i, n in enumerate(notes):
             # Staggered Note Ons
             QTimer.singleShot(i * 70, lambda note=n: self._ll_midi_out.send_message([0x90, note, 80]))
        
        # Release notes after the arpeggio, but keep sustain down for the "echo"
        off_time = len(notes) * 70 + 200
        QTimer.singleShot(off_time, lambda: [self._ll_midi_out.send_message([0x80, n, 0]) for n in notes])
        
        # Finally release sustain pedal after 2.5 seconds for a natural fade
        QTimer.singleShot(off_time + 2500, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]))

    def _play_happy_tone(self):
        """Rising 2-note interval (C5→G5) for AI connected."""
        if not self._ll_midi_out: return
        
        self._ll_midi_out.send_message([0xB0, 64, 127]) # Sustain ON
        self._ll_midi_out.send_message([0x90, 72, 90])   # C5
        QTimer.singleShot(120, lambda: self._ll_midi_out.send_message([0x90, 79, 90]))  # G5
        
        QTimer.singleShot(600, lambda: [self._ll_midi_out.send_message([0x80, n, 0]) for n in [72, 79]])
        QTimer.singleShot(2000, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]))  # Sustain OFF

    def _play_sad_tone(self):
        """Falling 2-note interval (E♭5→C5) for AI disconnected."""
        if not self._ll_midi_out: return
        
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0xB0, 64, 127]) # Sustain ON
        self._ll_midi_out.send_message([0x90, 75, 70])   # Eb5
        QTimer.singleShot(200, lambda: self._ll_midi_out.send_message([0x90, 72, 70]) if self._ll_midi_out else None)  # C5
        
        QTimer.singleShot(800, lambda: [self._ll_midi_out.send_message([0x80, n, 0]) for n in [75, 72]] if self._ll_midi_out else None)
        QTimer.singleShot(2500, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]) if self._ll_midi_out else None)  # Sustain OFF

    @Slot(int)
    def _on_metronome_tick(self, beat_num: int):
        """Play a MIDI click for the 4-beat count-in. Beat 1 is accented."""
        print(f"AppState: Received metronome tick {beat_num}")
        if not self._ll_midi_out:
            print("AppState: Metronome skipped - self._ll_midi_out is None")
            return
        if not hasattr(self._ll_midi_out, '_port_open') or not getattr(self._ll_midi_out, '_port_open', False):
            print("AppState: Metronome skipped - MIDI output port is not open")
            return
            
        # Channel 10 is the General MIDI percussion channel (0x99 for Note On)
        status = 0x99
        # 76 = High Wood Block (accent), 77 = Low Wood Block (regular)
        note = 76 if beat_num == 1 else 77
        velocity = 100
        
        self._ll_midi_out.send_message([status, note, velocity])
        # Note Off for percussion is often ignored but good practice
        def note_off():
            if self._ll_midi_out:
                self._ll_midi_out.send_message([0x89, note, 0])
        QTimer.singleShot(80, note_off)
        
    @Slot(list)
    def _on_midi_out_requested(self, pitches: list):
        """Play a list of MIDI pitches through the hardware for feedback or preview."""
        if not self._ll_midi_out:
            return
            
        print(f"AppState: Playing MIDI preview for {pitches}")
        status = 0x90 # Note On, Channel 1
        velocity = 80
        
        # Send Note On for all pitches
        for pitch in pitches:
            self._ll_midi_out.send_message([status, pitch, velocity])
            
        # Schedule Note Off after 1.5 seconds
        def all_notes_off():
            if self._ll_midi_out:
                for pitch in pitches:
                    self._ll_midi_out.send_message([0x80, pitch, 0])
        
        QTimer.singleShot(1500, all_notes_off)

    @Slot()
    def _on_lesson_plan_generated(self):
        """Called when ChordTrainer has finished background generation of a lesson."""
        if self.evaluation_engine.isRunning:
            print("AppState: Lesson plan generated but evaluation is running. Waiting...")
            self._lesson_plan_waiting = True
        else:
            print("AppState: Lesson plan generated. Activating now.")
            self.chord_trainer.activate_lesson_plan()

    @Slot()
    def _on_evaluation_finished(self):
        """Start the lesson plan after onboarding evaluation completes."""
        self._eval_intro_pending = False
        if self._lesson_plan_waiting:
            print("AppState: Evaluation finished. Activating waiting lesson plan.")
            self._lesson_plan_waiting = False
            self.chord_trainer.activate_lesson_plan()
        elif self._ai_connected and not self.chord_trainer.isActive:
            print("AppState: Evaluation finished. Starting new lesson plan generation.")
            self._sync_coach_settings()
            self.chord_trainer.start_lesson_plan()


    @Slot()
    def startEvaluationWithIntro(self):
        """Send a spoken intro to the AI, then start the evaluation after it finishes speaking."""
        if self._ai_connected and self._gemini.connected:
            self._eval_intro_pending = True
            self._eval_audio_received = False
            self.evalIntroPendingChanged.emit(True)
            self._gemini.send_prompt(
                "[System Note]: The user is about to take a skill evaluation. "
                "Give a brief, encouraging 2-sentence introduction. Tell them short melodies will scroll "
                "across the screen and they should play along as each note reaches the green line. "
                "Wish them luck!"
            )
            # Start evaluation in PAUSED mode immediately so the UI shows up
            self.evaluation_engine.startEvaluation(paused=True)
            # Safety timeout: if AI doesn't finish speaking in 10s, resume anyway
            QTimer.singleShot(10000, self._evaluation_safety_start)
        else:
            # AI not connected — start immediately
            self.evaluation_engine.startEvaluation(paused=False)

    @Slot()
    def _evaluation_safety_start(self):
        """Fallback to start evaluation if AI intro hangs."""
        if self._eval_intro_pending:
            print("AppState: AI intro timeout - resuming evaluation.")
            self._eval_intro_pending = False
            self.evalIntroPendingChanged.emit(False)
            self.evaluation_engine.resume()

    @Slot()
    def _on_ai_finished_speaking(self):
        """Called when the AI finishes a spoken response."""
        if self._eval_intro_pending:
            # Only start if we actually heard some audio, or if we've been waiting too long (timeout handles that)
            if self._eval_audio_received:
                print("AppState: AI intro finished. Resuming evaluation.")
                self._eval_intro_pending = False
                self.evalIntroPendingChanged.emit(False)
                self.evaluation_engine.resume()
            else:
                print("AppState: AI silence received but no audio yet. Waiting for intro...")

    @Slot(bytes)
    def _on_ai_audio_received(self, data):
        """Track if audio is being received during eval intro pending."""
        if self._eval_intro_pending:
            self._eval_audio_received = True

    def _on_midi_data(self, deltatime: float, message: list[int]):
        """Called by C++ RtMidi thread."""
        if not message:
            return
            
        status = message[0] & 0xF0
        if status == 0x90: # Note On
            pitch = message[1]
            velocity = message[2] if len(message) > 2 else 0
            is_on = velocity > 0
            self.midiNoteReceived.emit(pitch, is_on)
                
        elif status == 0x80: # Note Off
            pitch = message[1]
            self.midiNoteReceived.emit(pitch, False)

    @Slot(int, bool)
    def _dispatch_midi_note(self, pitch: int, is_on: bool):
        """Called on main UI thread via queued connection from midiNoteReceived signal."""
        if self.evaluation_engine.isRunning:
            self.evaluation_engine.handle_midi_note(pitch, is_on)
        else:
            self.chord_trainer.handle_midi_note(pitch, is_on)

    @Slot(str)
    def _on_ai_text(self, text: str):
        """Bounces text from background Gemini websockets loop onto the main UI thread."""
        preview = text[:50] # type: ignore
        print(f"AppState: AI text received, emitting to UI: {preview}...")
        self.aiTranscriptReceived.emit(text)

    # Expose the GeminiService explicitly to QML
    @Property(QObject, constant=True)
    def gemini(self):
        return self._gemini

    @Property(bool, constant=True)
    def midiConnected(self):
        return self._midi_connected

    @Property(bool, notify=aiConnectedChanged)
    def aiConnected(self):
        return self._ai_connected

    @Property(bool, notify=evalIntroPendingChanged)
    def evalIntroPending(self):
        return self._eval_intro_pending

    @Property(str, constant=True)
    def midiDeviceName(self):
        return self._midi_device_name

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
    # Load env vars manually for local testing
    env_file = project_root / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(env_file, "r", encoding="utf-16") as f:
                lines = f.readlines()
                
        for line in lines:
            if line.strip().startswith("GOOGLE_API_KEY="):
                os.environ["GOOGLE_API_KEY"] = line.strip().split("=", 1)[1]

    # Use the Basic style to allow full customization of UI components (removes native warnings)
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()

    app_state = AppState()
    engine.rootContext().setContextProperty("appState", app_state)
    
    # Add UI components path
    engine.addImportPath(str(project_root / "src" / "ui" if not getattr(sys, 'frozen', False) else project_root / "ui"))

    if getattr(sys, 'frozen', False):
        qml_file = project_root / "ui" / "main.qml"
    else:
        qml_file = project_root / "src" / "ui" / "main.qml"
    engine.load(os.fspath(qml_file))

    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
