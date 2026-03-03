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

def test_midi():
    print("Testing chordcoach_hw probe inside Qt...")
    handler = chordcoach_hw.MidiHandler()
    ports = handler.getPortNames()
    print(f"MidiHandler found {len(ports)} ports:", ports)
    QGuiApplication.quit()
    
if __name__ == "__main__":
    QtWebEngineQuick.initialize()
    app = QGuiApplication(sys.argv)
    QTimer.singleShot(1000, test_midi)
    sys.exit(app.exec())
