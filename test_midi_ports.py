import sys
import time
from pathlib import Path
import os

# Add src to path
src_dir = Path(r"C:\Users\scopp\OneDrive\Documents\repos\ChordCoach Companion\src")
sys.path.append(str(src_dir))

import core.bootstrap as bootstrap
bootstrap.setup_env()

import chordcoach_hw
from hardware.midi_hardware_service import LowLevelMidiOutput

def test_midi():
    dll_path = src_dir.parent / "build" / "_deps" / "rtmidi-build" / bootstrap._build_subdir() / bootstrap._native_lib_name("rtmidi")
    print(f"Creating LowLevelMidiOutput from {dll_path}...")
    ll_out = LowLevelMidiOutput(dll_path)
    print("LowLevel initialized.")

    print("Testing chordcoach_hw probe...")
    handler = chordcoach_hw.MidiHandler()
    ports = handler.getPortNames()
    print(f"MidiHandler found {len(ports)} ports:", ports)
    
if __name__ == "__main__":
    test_midi()
