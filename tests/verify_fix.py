
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

# Mock out external dependencies that are hard to load in a headless environment
sys.modules['PySide6'] = MagicMock()
sys.modules['PySide6.QtGui'] = MagicMock()
sys.modules['PySide6.QtQml'] = MagicMock()
sys.modules['PySide6.QtCore'] = MagicMock()

# Mock the local services
sys.modules['logic.services.gemini_service'] = MagicMock()
sys.modules['logic.services.midi_ingestor'] = MagicMock()
sys.modules['logic.services.repertoire_crawler'] = MagicMock()
sys.modules['logic.services.database_manager'] = MagicMock()
sys.modules['logic.services.chord_trainer'] = MagicMock()
sys.modules['logic.services.evaluation_service'] = MagicMock()
sys.modules['logic.services.adaptive_engine'] = MagicMock()
sys.modules['logic.services.settings_service'] = MagicMock()

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

import app

def test_app_state_init_no_dll():
    print("Testing AppState initialization without rtmidi.dll...")
    # Mock chordcoach_hw to trigger the problematic block
    app.chordcoach_hw = MagicMock()
    mock_handler = MagicMock()
    mock_handler.getPortNames.return_value = ["Mock MIDI Input"]
    app.chordcoach_hw.MidiHandler.return_value = mock_handler
    
    # Ensure _ll_midi_out is None as if the DLL search failed
    try:
        state = app.AppState()
        state._ll_midi_out = None
        print("Success: AppState initialized without crash.")
    except Exception as e:
        print(f"FAILED: AppState crashed during initialization: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_app_state_init_no_dll()
