import ctypes
import os
from pathlib import Path

project_root = Path(r"c:\Users\scopp\OneDrive\Documents\repos\ChordCoach Companion")
dll_path = project_root / "build" / "_deps" / "rtmidi-build" / "Release" / "rtmidi.dll"

if not dll_path.exists():
    print(f"DLL not found at {dll_path}")
    exit(1)

try:
    rtmidi = ctypes.CDLL(str(dll_path))
    print("Successfully loaded rtmidi.dll")
    
    # Try to list output ports
    # rtmidi_out_create_default() -> RtMidiPtr
    rtmidi.rtmidi_out_create_default.restype = ctypes.c_void_p
    midi_out = rtmidi.rtmidi_out_create_default()
    
    # rtmidi_get_port_count(RtMidiPtr) -> int
    rtmidi.rtmidi_get_port_count.argtypes = [ctypes.c_void_p]
    rtmidi.rtmidi_get_port_count.restype = ctypes.c_int
    count = rtmidi.rtmidi_get_port_count(midi_out)
    print(f"Found {count} MIDI Output ports:")
    
    # rtmidi_get_port_name(RtMidiPtr, int, char*, int*) -> int
    # This one is tricky with strings, let's just see if we get a count > 1
    for i in range(count):
        print(f"Port {i}")
        
except Exception as e:
    print(f"Error: {e}")
