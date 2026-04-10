import sys
import os
from pathlib import Path
import music21

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.music21_service import Music21Service

def run_stress_test():
    print("=== STARTING FINGERING STRESS TEST ===")
    service = Music21Service()
    
    # 1. Test Melodic Variety (Schlaf Kindlein Schlaf style)
    print("\n[TEST 1] Melodic Variety (Schlaf Kindlein Schlaf)...")
    res_melody = service.load_song_as_steps('oneills1850/0051-0100.abc') # Simple monophonic
    steps_melody = res_melody['steps']
    first_10_fingers = [s['fingers'][0] for s in steps_melody[:10]]
    print(f"First 10 melodic fingers: {first_10_fingers}")
    unique_fingers = len(set(first_10_fingers))
    if unique_fingers > 1:
        print(f"PASSED: Melodic variety detected ({unique_fingers} distinct fingers).")
    else:
        print(f"FAILED: No melodic variety (all notes use finger {first_10_fingers[0]}).")

    # 2. Test Unison Deduplication (Dichterliebe style)
    # We'll simulate a unison by checking a song known to have them, 
    # or just verifying the step format doesn't have duplicate pitches.
    print("\n[TEST 2] Unison Deduplication (Schumann style)...")
    res_schumann = service.load_song_as_steps('schumann_robert/dichterliebe_no2.xml')
    steps_schumann = res_schumann['steps']
    # Step at offset 0.25 historically has pitches [69, 69, 73]
    test_step = None
    for s in steps_schumann:
        if s['offset'] == 0.25:
            test_step = s
            break
    
    if test_step:
        print(f"Pitches at offset 0.25: {test_step['pitches']}")
        if len(test_step['pitches']) == len(set(test_step['pitches'])):
             print("PASSED: Unisons deduplicated (No duplicate pitches at same offset).")
        else:
             print("FAILED: Duplicates found at offset 0.25.")
    else:
        print("Test skipped: Could not find target offset in Schumann.")

    # 3. Test Anatomical Rebalancing (Beethoven style)
    print("\n[TEST 3] Anatomical Rebalancing (Große Fuge style)...")
    # Grosse Fuge has some massive chords.
    res_beethoven = service.load_song_as_steps('beethoven/opus133.mxl')
    steps_beethoven = res_beethoven['steps']
    
    found_rebalanced = False
    for s in steps_beethoven:
        # Check if we have a split across clefs/hands for a previous "Impossible" span
        rh_pitches = [s['pitches'][i] for i, h in enumerate(s['hands']) if h == "right"]
        if rh_pitches:
            span = max(rh_pitches) - min(rh_pitches)
            if span > 13:
                 print(f"FAILED: Found impossible RH span of {span} semitones at offset {s['offset']}.")
                 break
        
        # Look for the triple-G split (G3 moved to LH)
        # G3=55, G4=67, G5=79
        if 55 in s['pitches'] and 67 in s['pitches'] and 79 in s['pitches']:
            idx_55 = s['pitches'].index(55)
            idx_67 = s['pitches'].index(67)
            idx_79 = s['pitches'].index(79)
            if s['hands'][idx_55] == 'left' and s['hands'][idx_67] == 'right' and s['hands'][idx_79] == 'right':
                print(f"PASSED: Triple-G chord rebalanced! G3(55) moved to Left Hand.")
                found_rebalanced = True
                
                # Check Unique Fingers in RH
                f67 = s['fingers'][idx_67]
                f79 = s['fingers'][idx_79]
                print(f"RH Fingers for G4, G5: {f67}, {f79}")
                if f67 != f79:
                    print("PASSED: Unique fingers assigned to rebalanced RH group.")
                else:
                    print("FAILED: Duplicate fingers in rebalanced RH group.")
                break
    
    if not found_rebalanced:
        print("Note: Triple-G pattern not found in the first few measures of Op. 133.")

    print("\n=== STRESS TEST COMPLETE ===")

if __name__ == "__main__":
    try:
        run_stress_test()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
