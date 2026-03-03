"""
MIDI Hardware Service
Encapsulates low-level ctypes MIDI output and the high-level C++ extension (chordcoach_hw).
Responsible for sending low latency audio feedback like the metronome or preview chords.
"""
from PySide6.QtCore import QObject, Signal, Slot, QTimer # type: ignore
import ctypes
import sys

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


class MidiHardwareService(QObject):
    """
    Manages both input from the user's MIDI keyboard (via chordcoach_hw)
    and output to the system synth (via LowLevelMidiOutput).
    Emits unified signals to the rest of the application.
    """
    midiNoteReceived = Signal(int, bool)
    sustainPedalChanged = Signal(bool)
    connectionStatusChanged = Signal(bool)

    def __init__(self, chordcoach_hw, ll_lib_path):
        super().__init__()
        self.hw_module = chordcoach_hw
        self._ll_midi_out = None
        self.hw_midi_in = None
        self._is_sustain_pedal_down = False
        self.is_connected = False
        self.device_name = "Not Connected"
        
        self._ll_lib_path = ll_lib_path
        self._ll_midi_out = None
        
        # We DO NOT initialize LowLevelMidiOutput here on Windows!
        # Opening ANY MIDI handle locks the Windows MM device list for the process.
        # This prevents hot-plugged USB MIDI devices from being discovered by polling.
        # We will initialize it only after an input device is found.
            
        self._polling_timer = QTimer(self)
        self._polling_timer.timeout.connect(self.initialize)
        self._probe_handler = None
            
    def initialize(self):
        """Bind hardware ports and start listening. If no ports found, starts polling."""
        if not self.hw_module:
            print("MidiHardwareService: chordcoach_hw extension not available.")
            return False
            
        try:
            # We must instantiate a fresh MidiHandler on every poll to scan the system
            # for newly connected devices. If we reuse an old one, it might cache old ports.
            probe_handler = None
            try:
                probe_handler = self.hw_module.MidiHandler()
            except Exception as e:
                print(f"MidiHardwareService: Failed to create primary MidiHandler probe: {e}")
            
            ports = probe_handler.getPortNames() if probe_handler else []
            
            # Fallback to low-level probe if primary fails
            if not ports and self._ll_midi_out:
                ports = self._ll_midi_out.get_port_names()
                if ports:
                    print(f"MidiHardwareService: Primary probe empty, but LowLevel found: {ports}")

            if not ports:
                if not self._polling_timer.isActive():
                    print("MidiHardwareService: No MIDI ports found. Starting background polling...")
                    self._polling_timer.start(2000) # Poll every 2 seconds
                
                if self.is_connected:
                    print("MidiHardwareService: MIDI device lost.")
                    self.is_connected = False
                    self.device_name = "Not Connected"
                    self.connectionStatusChanged.emit(False)
                return False
                
            # If we were polling and found a port
            if self._polling_timer.isActive():
                self._polling_timer.stop()
                print(f"MidiHardwareService: MIDI Device detected during polling: {ports[0]}")

            # Re-instantiating for the actual listener
            try:
                m_handler = self.hw_module.MidiHandler()
                m_handler.openPort(0) # Default to first input port
                m_handler.setCallback(self._on_raw_midi_data)
                self.hw_midi_in = m_handler
            except Exception as e:
                print(f"MidiHardwareService: Failed to open MIDI port: {e}")
                return False

            self.is_connected = True
            self.device_name = ports[0]
            self.connectionStatusChanged.emit(True)
            print(f"MidiHardwareService: MIDI Input Hardware initialized: {ports[0]}")
            
            # Now we can safely initialize LowLevelMidiOutput without breaking hotplug
            if not self._ll_midi_out and self._ll_lib_path and self._ll_lib_path.exists():
                print(f"MidiHardwareService: Initializing LowLevelMidiOutput with {self._ll_lib_path}")
                self._ll_midi_out = LowLevelMidiOutput(self._ll_lib_path)
            
            # Match Output Port to Input Port if possible
            if self._ll_midi_out:
                try:
                    out_names = self._ll_midi_out.get_port_names()
                    target = ports[0]
                    target_base = target.split(' ')[0] if ' ' in target else target
                    paired = False
                    for i, name in enumerate(out_names):
                        if target_base in name and "Synth" not in name:
                            self._ll_midi_out.open_port(i)
                            print(f"MidiHardwareService: LowLevel Paired MIDI Output: {name}")
                            paired = True
                            break
                    
                    if not paired and len(out_names) == 1:
                        self._ll_midi_out.open_port(0)
                        print(f"MidiHardwareService: LowLevel MIDI Output Fallback: {out_names[0]}")
                        paired = True
                    elif not paired:
                        print(f"MidiHardwareService: LowLevel MIDI Output Pairing Failed for {target}. Found: {out_names}")
                except Exception as oe:
                    print(f"MidiHardwareService: MIDI Output Pairing Error: {oe}")
            else:
                print("MidiHardwareService: Low-level MIDI output skipped (Not available)")
            
            return True
        except Exception as e:
            print(f"MidiHardwareService: MIDI Hardware Init Error: {e}")
            self.is_connected = False
            self.connectionStatusChanged.emit(False)
            return False

    def _on_raw_midi_data(self, deltatime: float, message: list[int]):
        """Called by C++ RtMidi thread (from chordcoach_hw extension)."""
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

        elif status == 0xB0: # Control Change
            controller = message[1]
            value = message[2] if len(message) > 2 else 0
            if controller == 64: # Sustain Pedal
                is_down = value >= 64
                if is_down != self._is_sustain_pedal_down:
                    self._is_sustain_pedal_down = is_down
                    self.sustainPedalChanged.emit(is_down)

    # --- Audio / Tone Generation ---
    
    def play_startup_riff(self):
        """Plays a cheerful C Maj9 arpeggio via LowLevel MIDI with natural sustain."""
        if not self._ll_midi_out: return
        
        # Sustain ON to allow notes to ring out
        self._ll_midi_out.send_message([0xB0, 64, 127])
        
        notes = [60, 64, 67, 71, 74]
        for i, n in enumerate(notes):
             QTimer.singleShot(i * 70, lambda note=n: self._ll_midi_out.send_message([0x90, note, 80]))
        
        off_time = len(notes) * 70 + 200
        QTimer.singleShot(off_time, lambda: [self._ll_midi_out.send_message([0x80, n, 0]) for n in notes])
        QTimer.singleShot(off_time + 2500, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]))

    def play_happy_tone(self):
        """Rising 2-note interval (C5→G5) for AI connected."""
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0xB0, 64, 127]) # Sustain ON
        self._ll_midi_out.send_message([0x90, 72, 90])   # C5
        QTimer.singleShot(120, lambda: self._ll_midi_out.send_message([0x90, 79, 90]))  # G5
        QTimer.singleShot(600, lambda: [self._ll_midi_out.send_message([0x80, n, 0]) for n in [72, 79]])
        QTimer.singleShot(2000, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]))

    def play_sad_tone(self):
        """Falling 2-note interval (E♭5→C5) for AI disconnected."""
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0xB0, 64, 127]) 
        self._ll_midi_out.send_message([0x90, 75, 70])   
        QTimer.singleShot(200, lambda: self._ll_midi_out.send_message([0x90, 72, 70]) if self._ll_midi_out else None)
        QTimer.singleShot(800, lambda: [self._ll_midi_out.send_message([0x80, n, 0]) for n in [75, 72]] if self._ll_midi_out else None)
        QTimer.singleShot(2500, lambda: self._ll_midi_out.send_message([0xB0, 64, 0]) if self._ll_midi_out else None)

    def play_reconnect_ping(self):
        """Soft single note ping used while reconnecting to AI."""
        if not self._ll_midi_out: return
        self._ll_midi_out.send_message([0x90, 72, 40])
        QTimer.singleShot(200, lambda: self._ll_midi_out.send_message([0x80, 72, 0]) if self._ll_midi_out else None)

    @Slot(int)
    def play_metronome_tick(self, beat_num: int):
        """Play a MIDI click for the 4-beat count-in. Beat 1 is accented. Requires General MIDI percussion channel 10."""
        if not self._ll_midi_out: return
        if not hasattr(self._ll_midi_out, '_port_open') or not getattr(self._ll_midi_out, '_port_open', False):
            return
            
        status = 0x99 # Channel 10 Note On
        note = 76 if beat_num == 1 else 77 # High/Low Wood Block
        velocity = 100
        
        self._ll_midi_out.send_message([status, note, velocity])
        QTimer.singleShot(80, lambda: self._ll_midi_out.send_message([0x89, note, 0]) if self._ll_midi_out else None)
        
    @Slot(list)
    def play_chord_preview(self, pitches: list):
        """Play a list of MIDI pitches through the hardware for feedback or preview."""
        if not self._ll_midi_out: return
        
        status = 0x90 
        velocity = 80
        
        for pitch in pitches:
            self._ll_midi_out.send_message([status, pitch, velocity])
            
        QTimer.singleShot(1500, lambda: [self._ll_midi_out.send_message([0x80, p, 0]) for p in pitches] if self._ll_midi_out else None)
