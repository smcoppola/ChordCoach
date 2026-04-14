"""
===============================================================================
File: midi_hardware_service.py
Description: Encapsulates low-level ctypes MIDI output and the high-level C++ 
             extension (chordcoach_hw). Responsible for establishing hardware 
             binding, managing hotplug polling, and handling low-latency audio 
             feedback (metronome, chord previews).
===============================================================================
"""
from PySide6.QtCore import QObject, Signal, Slot, QTimer, Qt # type: ignore
import ctypes
import sys
import threading
from pathlib import Path
from typing import List, Optional

class LowLevelMidiOutput:
    """
    Uses ctypes to call the rtmidi shared library directly for MIDI output (cross-platform).
    Bypasses high-level Python overhead for immediate audio feedback.
    """
    def __init__(self, dll_path: Path):
        """
        Initializes the ctypes bindings and instantiates the default RtMidiOut pointer.
        
        Args:
            dll_path (Path): Absolute path to the compiled rtmidi dynamic library.
        """
        try:
            # 1. Load the shared library into the process space
            self.dll = ctypes.CDLL(str(dll_path))
            
            # 2. Define C-function signatures to ensure correct memory alignment and types
            self.dll.rtmidi_out_create_default.restype = ctypes.c_void_p
            self.dll.rtmidi_get_port_count.argtypes = [ctypes.c_void_p]
            self.dll.rtmidi_get_port_count.restype = ctypes.c_int
            self.dll.rtmidi_get_port_name.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
            self.dll.rtmidi_get_port_name.restype = ctypes.c_int
            self.dll.rtmidi_open_port.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
            self.dll.rtmidi_out_send_message.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
            
            # 3. Instantiate the C++ RtMidiOut object and store the opaque pointer
            self.midi_out = self.dll.rtmidi_out_create_default()
            self._port_open = False
        except Exception as e:
            print(f"LowLevelMidiOutput Init Error: {e}")
            self.midi_out = None

    def get_port_names(self) -> List[str]:
        """
        Queries the OS via RtMidi for available MIDI output port names.
        
        Returns:
            List[str]: A list of UTF-8 decoded port name strings.
        """
        if not self.midi_out: return []
        names = []
        
        # 1. Query total available ports to bound the iteration
        count = self.dll.rtmidi_get_port_count(self.midi_out)
        
        # 2. Pre-allocate a C-string buffer for the port names
        buf = ctypes.create_string_buffer(256)
        for i in range(count):
            buf_len = ctypes.c_int(256)
            # 3. Retrieve name into buffer, passing length by reference
            self.dll.rtmidi_get_port_name(self.midi_out, i, buf, ctypes.byref(buf_len))
            names.append(buf.value.decode('utf-8'))
        return names

    def open_port(self, index: int):
        """
        Binds the internal RtMidiOut pointer to a specific OS port index.
        
        Args:
            index (int): The 0-based hardware port index.
        """
        if not self.midi_out: return
        # 1. Open the requested port and label the client "ChordCoachOutput"
        self.dll.rtmidi_open_port(self.midi_out, index, b"ChordCoachOutput")
        # 2. Flag the port as open to unblock send operations
        self._port_open = True

    def send_message(self, message: List[int]):
        """
        Transmits a raw sequence of MIDI bytes to the bound hardware port.
        
        Args:
            message (List[int]): Array of raw MIDI bytes (e.g., [0x90, 60, 100]).
        """
        if not self._port_open or not self.midi_out: return
        # 1. Cast Python integer list to a contiguous C unsigned byte array
        msg_type = ctypes.c_ubyte * len(message)
        msg_array = msg_type(*message)
        # 2. Dispatch array to the C-API
        self.dll.rtmidi_out_send_message(self.midi_out, msg_array, len(message))


class MidiHardwareService(QObject):
    """
    Manages input from the user's MIDI keyboard (via chordcoach_hw) and output to the 
    system synth (via LowLevelMidiOutput). Emits unified signals to the application thread.
    """
    midiNoteReceived = Signal(int, bool)
    sustainPedalChanged = Signal(bool)
    connectionStatusChanged = Signal(bool)
    
    # Internal signals for thread-safe main-loop delegation
    _cmdStartPolling = Signal()
    _cmdStopPolling = Signal()
    _cmdBulkSend = Signal(list)
    _cmdPlayStartupRiff = Signal()

    def __init__(self, chordcoach_hw, ll_lib_path: Path, midi_out_enabled: bool = True):
        """
        Constructs the service and configures internal state and cross-thread signals.
        
        Args:
            chordcoach_hw: The compiled C++ pybind11 module for hardware input.
            ll_lib_path (Path): Path to the rtmidi dynamic library for output.
            midi_out_enabled (bool): Toggle to disable audio output initialization.
        """
        super().__init__()
        self.hw_module = chordcoach_hw
        self.hw_midi_in = None
        self._is_sustain_pedal_down = False
        self.is_connected = False
        self.device_name = "Not Connected"
        
        self._ll_lib_path = ll_lib_path
        self._ll_midi_out: Optional[LowLevelMidiOutput] = None
        self._midi_out_enabled = midi_out_enabled
            
        self._polling_timer = QTimer(self)
        self._is_polling = False # Thread-safe state tracking to avoid QTimer checks outside main thread
        
        # 1. Bind Qt signals to ensure execution happens on the main thread loop
        self._polling_timer.timeout.connect(self.initialize_async)
        self._cmdStartPolling.connect(self._start_polling_safe)
        self._cmdStopPolling.connect(self._stop_polling_safe)
        self._cmdBulkSend.connect(self._do_safe_bulk_send)
        self._cmdPlayStartupRiff.connect(self.play_startup_riff)
        
    @Slot()
    def _start_polling_safe(self):
        """Thread-safe timer activation."""
        self._is_polling = True
        self._polling_timer.start(2000)

    @Slot()
    def _stop_polling_safe(self):
        """Thread-safe timer deactivation."""
        self._is_polling = False
        self._polling_timer.stop()

    @Slot()
    def initialize_async(self):
        """
        Dispatches initialization to a background thread to prevent GUI stall during hardware scans.
        """
        # 1. Spawn daemon thread targeting main init payload. Daemon ensures it dies with the app.
        t = threading.Thread(target=self._execute_initialization, daemon=True)
        t.start()
            
    def _execute_initialization(self) -> bool:
        """
        Threaded payload: Probes for MIDI hardware, binds input listeners, and attempts to map
        a corresponding output port. Mutates internal connection state.
        
        Returns:
            bool: True if initialization fully succeeded, False if ports missing or failed.
        """
        if self.is_connected:
            return True
        if not self.hw_module:
            print("MidiHardwareService: chordcoach_hw extension not available.")
            return False
            
        try:
            # 1. Instantiate temporary probe to check for input ports
            probe_handler = None
            try:
                probe_handler = self.hw_module.MidiHandler()
            except Exception as e:
                print(f"MidiHardwareService: Failed to create primary MidiHandler probe: {e}")
            
            # 2. Retrieve port listing from the OS
            ports = probe_handler.getPortNames() if probe_handler else []
            
            # 3. Fallback: If C++ extension fails, verify if lower-level ctypes can see ports
            if not ports and self._ll_midi_out:
                ports = self._ll_midi_out.get_port_names()

            # 4. Handle Disconnected State
            if not ports:
                if not self._is_polling:
                    print("MidiHardwareService: No MIDI ports found. Starting background polling…")
                    self._cmdStartPolling.emit()
                
                if self.is_connected:
                    print("MidiHardwareService: MIDI device lost.")
                    self.is_connected = False
                    self.device_name = "Not Connected"
                    self.connectionStatusChanged.emit(False)
                return False
                
            # 5. Handle Connected State (Transition from polling)
            if self._is_polling:
                self._cmdStopPolling.emit()
                print(f"MidiHardwareService: MIDI Device detected during polling: {ports[0]}")

            # 6. Instantiate permanent listener and bind to first available hardware port (Index 0)
            try:
                # Force garbage collection/release of old pointer if re-initializing
                self.hw_midi_in = None 
                
                m_handler = self.hw_module.MidiHandler()
                m_handler.openPort(0)
                m_handler.setCallback(self._on_raw_midi_data)
                self.hw_midi_in = m_handler
            except Exception as e:
                print(f"MidiHardwareService: Failed to bind MIDI port listener: {e}")
                return False

            # 7. Update internal state and notify application
            self.is_connected = True
            self.device_name = ports[0]
            self.connectionStatusChanged.emit(True)
            print(f"MidiHardwareService: MIDI Input Hardware initialized: {ports[0]}")
            
            # 8. Defer output initialization/matching to sub-routine
            self._initialize_output_hardware(target_name=ports[0])
            
            return True
        except Exception as e:
            print(f"MidiHardwareService: MIDI Hardware Init Error: {e}")
            self.is_connected = False
            self.connectionStatusChanged.emit(False)
            return False

    def _initialize_output_hardware(self, target_name: str):
        """
        Attempts to spin up the ctypes MIDI out module and match it to the connected input device.
        
        Args:
            target_name (str): The name of the successfully bound input port to pair against.
        """
        # 1. Validate output configuration requirements
        if not self._midi_out_enabled:
            print("MidiHardwareService: MIDI output DISABLED by user setting (Settings → Hardware)")
            return
            
        if self._ll_midi_out:
            return # Output already initialized
            
        if not self._ll_lib_path or not self._ll_lib_path.exists():
            print("MidiHardwareService: Low-level MIDI output skipped (Library missing)")
            return

        # 2. Instantiate ctypes interface
        print(f"MidiHardwareService: Initializing LowLevelMidiOutput with {self._ll_lib_path}")
        self._ll_midi_out = LowLevelMidiOutput(self._ll_lib_path)
        
        # 3. Execute matching algorithm to find a valid output port
        try:
            out_names = self._ll_midi_out.get_port_names()
            target_base = target_name.split(' ')[0] if ' ' in target_name else target_name
            paired = False
            
            # Attempt A: Direct string match against the input hardware name
            for i, name in enumerate(out_names):
                if target_base in name:
                    self._ll_midi_out.open_port(i)
                    print(f"MidiHardwareService: LowLevel MIDI Output Hardware Match: {name}")
                    paired = True
                    break

            # Attempt B: Fallback to a known OS software synth
            if not paired:
                for i, name in enumerate(out_names):
                    if "Synth" in name or "FluidSynth" in name or "Microsoft GS" in name:
                        self._ll_midi_out.open_port(i)
                        print(f"MidiHardwareService: LowLevel MIDI Output (Synth): {name}")
                        paired = True
                        break
            
            # Attempt C: Bruteforce bind to index 0 if any outputs exist
            if not paired and out_names:
                self._ll_midi_out.open_port(0)
                print(f"MidiHardwareService: LowLevel MIDI Output Fallback: {out_names[0]}")
            elif not paired:
                print(f"MidiHardwareService: No MIDI output ports available")
                
            # 4. Confirm binding by transmitting startup sequence via main thread signal
            if self._ll_midi_out and self._ll_midi_out._port_open:
                self._cmdPlayStartupRiff.emit()
                
        except Exception as oe:
            print(f"MidiHardwareService: MIDI Output Pairing Error: {oe}")

    def _on_raw_midi_data(self, deltatime: float, message: List[int]):
        """
        Callback executed by the C++ RtMidi thread (via pybind11) upon incoming data.
        Maps raw hex status bytes to normalized application signals.
        
        Args:
            deltatime (float): Time delta since last message (provided by RtMidi).
            message (List[int]): Array of raw MIDI bytes.
        """
        if not message:
            return
            
        # 1. Mask out the channel data (lower nibble) to isolate the status command
        status = message[0] & 0xF0
        
        # 2. Process Note On
        if status == 0x90: 
            pitch = message[1]
            velocity = message[2] if len(message) > 2 else 0
            # A Note On with velocity 0 is mathematically equivalent to a Note Off
            is_on = velocity > 0
            self.midiNoteReceived.emit(pitch, is_on)
                
        # 3. Process Note Off
        elif status == 0x80: 
            pitch = message[1]
            self.midiNoteReceived.emit(pitch, False)

        # 4. Process Control Changes (Specifically CC 64 - Sustain)
        elif status == 0xB0: 
            controller = message[1]
            value = message[2] if len(message) > 2 else 0
            if controller == 64: 
                is_down = value >= 64
                if is_down != self._is_sustain_pedal_down:
                    self._is_sustain_pedal_down = is_down
                    self.sustainPedalChanged.emit(is_down)

    def _safe_bulk_send(self, messages: List[List[int]]):
        """
        Dispatches a batch of MIDI messages to the main thread for throttled delivery.
        
        Args:
            messages (List[List[int]]): Array of MIDI messages.
        """
        if messages:
            self._cmdBulkSend.emit(messages)

    @Slot(list)
    def _do_safe_bulk_send(self, messages: List[List[int]]):
        """
        Executes the batch send on the main thread using throttled recursion. 
        Yields control back to the Qt event loop between frames to prevent blocking.
        
        Args:
            messages (List[List[int]]): Array of MIDI messages.
        """
        if not self._ll_midi_out or not messages: return
        
        def _send_next(idx: int):
            # 1. Ensure output hasn't been destroyed mid-transmission
            if not self._ll_midi_out or idx >= len(messages): return
            
            # 2. Dispatch frame
            self._ll_midi_out.send_message(messages[idx])
            
            # 3. Schedule next frame on the event queue
            if idx + 1 < len(messages):
                QTimer.singleShot(2, self, lambda: _send_next(idx + 1))
                
        _send_next(0)
    
    @Slot()
    def play_startup_riff(self):
        """Plays a cheerful C Maj9 arpeggio via LowLevel MIDI with natural sustain."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] MidiHardware: Playing startup riff")
        if not self._ll_midi_out: return
        
        self._ll_midi_out.send_message([0xB0, 64, 127])
        
        notes = [60, 64, 67, 71, 74]
        for i, n in enumerate(notes):
             QTimer.singleShot(i * 70, lambda note=n: self._ll_midi_out.send_message([0x90, note, 80]) if self._ll_midi_out else None)
        
        off_time = len(notes) * 70 + 200
        QTimer.singleShot(off_time, lambda: self._safe_bulk_send([[0x80, n, 0] for n in notes]))
        QTimer.singleShot(off_time + 2500, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]) if self._ll_midi_out else None)
        QTimer.singleShot(off_time + 2600, self._send_controller_reset)

    @Slot()
    def play_happy_tone(self):
        """Rising 2-note interval (C5→G5) for AI connected."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] MidiHardware: Playing happy connected tone")
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0xB0, 64, 127]) 
        self._ll_midi_out.send_message([0x90, 72, 90])  
        QTimer.singleShot(120, lambda: self._ll_midi_out.send_message([0x90, 79, 90]) if self._ll_midi_out else None)
        QTimer.singleShot(600, lambda: self._safe_bulk_send([[0x80, n, 0] for n in [72, 79]]))
        QTimer.singleShot(2000, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]) if self._ll_midi_out else None)
        QTimer.singleShot(2100, self._send_controller_reset)

    @Slot()
    def play_sad_tone(self):
        """Falling 2-note interval (E♭5→C5) for AI disconnected."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] MidiHardware: Playing sad disconnected tone")
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0xB0, 64, 127]) 
        self._ll_midi_out.send_message([0x90, 75, 70])   
        QTimer.singleShot(200, lambda: self._ll_midi_out.send_message([0x90, 72, 70]) if self._ll_midi_out else None)
        QTimer.singleShot(800, lambda: self._safe_bulk_send([[0x80, n, 0] for n in [75, 72]]))
        QTimer.singleShot(2500, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]) if self._ll_midi_out else None)
        QTimer.singleShot(2600, self._send_controller_reset)

    @Slot()
    def _send_controller_reset(self):
        """Send All Notes Off + Reset All Controllers to prevent stuck synth state."""
        if not self._ll_midi_out:
            return
        self._ll_midi_out.send_message([0xB0, 123, 0])  # All Notes Off
        self._ll_midi_out.send_message([0xB0, 121, 0])  # Reset All Controllers
        print("MidiHardwareService: Sent controller reset (CC 123 + CC 121)")

    @Slot()
    def play_reconnect_ping(self):
        """Soft single note ping used while reconnecting to AI."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] MidiHardware: Playing reconnect ping")
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0x90, 72, 40])
        QTimer.singleShot(200, lambda: self._ll_midi_out.send_message([0x80, 72, 0]) if self._ll_midi_out else None)

    @Slot(int)
    def play_metronome_tick(self, beat_num: int):
        """Play a MIDI click for the 4-beat count-in. Requires General MIDI percussion channel 10."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] MidiHardware: Playing metronome tick (beat {beat_num})")
        if not self._ll_midi_out: return
        if not hasattr(self._ll_midi_out, '_port_open') or not getattr(self._ll_midi_out, '_port_open', False):
            return
            
        status = 0x99 # Channel 10 Note On
        note = 76 if beat_num == 1 else 77 # High/Low Wood Block
        velocity = 100
        
        self._ll_midi_out.send_message([status, note, velocity])
        QTimer.singleShot(80, lambda: self._ll_midi_out.send_message([0x89, note, 0]) if self._ll_midi_out else None)
        
    @Slot(list)
    def play_chord_preview(self, pitches: List[int]):
        """Play a list of MIDI pitches through the hardware for feedback or preview."""
        from datetime import datetime
        print(f"[TIMING {datetime.now().strftime('%H:%M:%S.%f')[:-3]}] MidiHardware: Playing chord preview (pitches {pitches})")
        if not self._ll_midi_out: return
        
        status = 0x90 
        velocity = 80
        
        self._safe_bulk_send([[status, pitch, velocity] for pitch in pitches])
        QTimer.singleShot(1500, lambda: self._safe_bulk_send([[0x80, p, 0] for p in pitches]))