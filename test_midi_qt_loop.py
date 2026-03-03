import sys
import time
from pathlib import Path
import os
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QTimer
from PySide6.QtWebEngineQuick import QtWebEngineQuick

# Add src to path
src_dir = Path(r"C:\Users\scopp\OneDrive\Documents\repos\ChordCoach Companion\src")
sys.path.append(str(src_dir))

import core.bootstrap as bootstrap
bootstrap.setup_env()

import chordcoach_hw
from hardware.midi_hardware_service import LowLevelMidiOutput

count = 0
def test_midi():
    global count
    print(f"[{count}] Testing chordcoach_hw probe inside Qt Timer...")
    handler = chordcoach_hw.MidiHandler()
    ports = handler.getPortNames()
    print(f"[{count}] MidiHandler found {len(ports)} ports:", ports)
    count += 1
    if count >= 10:
        QGuiApplication.quit()
    
if __name__ == "__main__":
    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    
    dll_path = src_dir.parent / "build" / "_deps" / "rtmidi-build" / bootstrap._build_subdir() / bootstrap._native_lib_name("rtmidi")
    ll_out = LowLevelMidiOutput(dll_path)
    
    timer = QTimer()
    timer.timeout.connect(test_midi)
    timer.start(2000)
    
    sys.exit(app.exec())
