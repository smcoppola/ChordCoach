import sys
import time
from pathlib import Path
import os
import ctypes

# Add src to path
src_dir = Path(r"C:\Users\scopp\OneDrive\Documents\repos\ChordCoach Companion\src")
sys.path.append(str(src_dir))

import core.bootstrap as bootstrap
bootstrap.setup_env()

import chordcoach_hw
from hardware.midi_hardware_service import LowLevelMidiOutput

def test_hotplug():
    dll_path = src_dir.parent / "build" / "_deps" / "rtmidi-build" / bootstrap._build_subdir() / bootstrap._native_lib_name("rtmidi")
    print(f"Creating LowLevelMidiOutput from {dll_path}...")
    ll_out = LowLevelMidiOutput(dll_path)
    print("LowLevel initialized. Starting polling loop...")

    for i in range(10):
        handler = chordcoach_hw.MidiHandler()
        ports = handler.getPortNames()
        print(f"[{i}] MidiHandler found {len(ports)} ports:", ports)
        del handler
        time.sleep(2)
        
    print("Test complete.")
    
if __name__ == "__main__":
    test_hotplug()
