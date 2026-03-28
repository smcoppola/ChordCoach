import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.append(project_root)

# Mock DB
class MockDB:
    pass

try:
    from logic.services.evaluation_service import EvaluationService
    import music21

    service = EvaluationService(MockDB(), Path(os.path.join(os.path.dirname(__file__), "..")))
    
    # Check level 1 (Ode to Joy)
    service._start_level(1)
    notes = service.sequenceNotes
    print(f"\nLevel 1 (Ode to Joy) - All Unique Pitches:")
    found_fingers = {}
    for n in notes:
        p = n['pitch']
        f = n.get('finger')
        if f not in found_fingers:
            found_fingers[f] = p
            print(f"  Finger {f} assigned to Pitch {p}")

except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
