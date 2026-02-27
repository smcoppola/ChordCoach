import sys
import os
import time
from pathlib import Path

# Add the compiled extension path
project_root = Path(__file__).parent.parent
hw_bin_path = project_root / "build" / "src" / "hardware" / "Release"
sys.path.append(str(hw_bin_path))

# Add the DLL paths for Windows to find pa and rtmidi dlls
dll_paths = [
    project_root / "build" / "_deps" / "rtmidi-build" / "Release",
    project_root / "build" / "_deps" / "portaudio-build" / "Release"
]
for p in dll_paths:
    if p.exists():
        os.add_dll_directory(str(p))

try:
    import chordcoach_hw
except ImportError as e:
    print(f"Failed to import chordcoach_hw: {e}")
    sys.exit(1)

def midi_callback(deltatime, message):
    # Print incoming messages - this verifies our C++ callback is hitting Python
    hex_msg = " ".join([f"{x:02X}" for x in message])
    print(f"MIDI Event [{deltatime:.4f}s]: {hex_msg}")

def audio_callback(pcm_data):
    # Just print the size of the array to verify PortAudio stream is pushing data
    # (Printing every frame would overwhelm the console)
    print(f"RCV Audio Frames: {len(pcm_data)}")

def main():
    print("Testing Hardware Bindings...")
    
    # 1. Test MIDI
    midi = chordcoach_hw.MidiHandler()
    ports = midi.getPortNames()
    print(f"\nAvailable MIDI Ports: {ports}")
    
    if ports:
        print(f"Opening port 0: {ports[0]}")
        midi.openPort(0)
        midi.setCallback(midi_callback)
    
    # 2. Test Audio
    audio = chordcoach_hw.AudioHandler()
    audio.setCallback(audio_callback)
    audio.startCapture()

    print("\nListening for 2.5 seconds...")
    print("Press some keys on your MIDI keyboard or make noise!\n")
    try:
        # We only want to test briefly just to ensure the thread bindings don't crash the interpreter
        time.sleep(2.5) 
    except KeyboardInterrupt:
        pass
        
    print("\nStopping...")
    audio.stopCapture()

if __name__ == "__main__":
    main()
