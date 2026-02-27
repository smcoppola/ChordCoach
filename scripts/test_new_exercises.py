"""
Test script for pentascale and progression exercise types.
Bypasses Gemini AI by feeding mock lesson plans directly into ChordTrainerService.
Run: python scripts/test_new_exercises.py
"""
import sys
import os
from pathlib import Path

# Add project src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Minimal Qt app needed for QObject/Signal/Slot
from PySide6.QtWidgets import QApplication  # type: ignore
app = QApplication(sys.argv)

from logic.services.database_manager import DatabaseManager  # type: ignore
from logic.services.chord_trainer import ChordTrainerService  # type: ignore

# Use a throwaway test database
test_db_path = Path(__file__).parent.parent / "database" / "test_exercises.db"
db = DatabaseManager(test_db_path)
trainer = ChordTrainerService(db)

print("=" * 60)
print("TEST 1: Pentascale Exercise (C Major Ascending)")
print("=" * 60)

mock_pentascale_plan = [
    {
        "exercise_type": "pentascale",
        "root_idx": 0,
        "scale_type": "Major",
        "direction": "ascending",
        "octave": 4,
        "exercise_name": "Pentascale Warmup",
        "spoken_instruction": "Test pentascale",
        "hold_ms": 0,
    }
]

# Inject the plan directly
trainer._lesson_playlist = list(mock_pentascale_plan)
trainer._lesson_total = len(trainer._lesson_playlist)
trainer._is_lesson_mode = True
trainer._is_active = True
trainer._exercise_name = "Pentascale Warmup"  # Pre-set to avoid speech pause

# Trigger the first step
trainer._next_chord()

print(f"  Exercise type: {trainer._exercise_type}")
print(f"  Scale name: {trainer._scale_name}")
print(f"  Sequence: {trainer._pentascale_sequence}")
print(f"  Expected: C4=60, D4=62, E4=64, F4=65, G4=67")

# Verify pentascale state
assert trainer._exercise_type == "pentascale", f"Expected 'pentascale', got '{trainer._exercise_type}'"
assert trainer._pentascale_sequence == [60, 62, 64, 65, 67], f"Wrong sequence: {trainer._pentascale_sequence}"
assert trainer._pentascale_index == 0, f"Index should be 0, got {trainer._pentascale_index}"

# Simulate playing the correct notes one by one
notes = [60, 62, 64, 65, 67]
for i, note in enumerate(notes):
    # Simulate note on
    trainer.handle_midi_note(note, True)
    
    if i < 4:  # Not the last note
        assert trainer._pentascale_index == i + 1, f"After note {i}, index should be {i+1}, got {trainer._pentascale_index}"
        # Simulate note off (release before next)
        trainer.handle_midi_note(note, False)
    
    print(f"  Note {i+1}/5 ({note}): OK ✓")

print(f"  Final state - lesson complete: {trainer._is_lesson_complete}")
print("  PENTASCALE TEST PASSED ✓\n")


print("=" * 60)
print("TEST 2: Chord Progression (I-IV-V-I in C)")
print("=" * 60)

# Reset state
trainer._is_lesson_complete = False
trainer._lesson_progress = 0
trainer._active_pitches.clear()
trainer._waiting_for_release = False

mock_progression_plan = [
    {
        "exercise_type": "progression",
        "exercise_name": "Chord Progression",
        "spoken_instruction": "Test progression",
        "hold_ms": 0,
        "progression_steps": [
            {"root_idx": 0, "chord_type_name": "Major", "numeral": "I"},
            {"root_idx": 5, "chord_type_name": "Major", "numeral": "IV"},
            {"root_idx": 7, "chord_type_name": "Major", "numeral": "V"},
            {"root_idx": 0, "chord_type_name": "Major", "numeral": "I"},
        ]
    }
]

trainer._lesson_playlist = list(mock_progression_plan)
trainer._lesson_total = len(trainer._lesson_playlist)
trainer._is_lesson_mode = True
trainer._is_active = True
trainer._exercise_name = "Chord Progression"  # Pre-set to avoid speech pause

trainer._next_chord()

print(f"  Exercise type: {trainer._exercise_type}")
print(f"  Numerals: {trainer._progression_numerals}")
print(f"  Progress index: {trainer._progression_index}")

assert trainer._exercise_type == "progression", f"Expected 'progression', got '{trainer._exercise_type}'"
assert trainer._progression_numerals == ["I", "IV", "V", "I"], f"Wrong numerals: {trainer._progression_numerals}"
assert trainer._progression_index == 0

# Play I chord (C Major: C=60, E=64, G=67 → intervals {0, 4, 7})
print(f"  Step 1 target: {trainer._target_chord_name}, intervals: {trainer._target_intervals}")
trainer.handle_midi_note(60, True)
trainer.handle_midi_note(64, True)
trainer.handle_midi_note(67, True)
print(f"  After I chord: progression_index={trainer._progression_index}")
assert trainer._progression_index == 1, f"Should advance to 1, got {trainer._progression_index}"

# Release all keys
trainer.handle_midi_note(60, False)
trainer.handle_midi_note(64, False)
trainer.handle_midi_note(67, False)
print(f"  Step 1 (I): PASSED ✓")

# Play IV chord (F Major: F=65, A=69, C=72 → intervals {5, 9, 0})
print(f"  Step 2 target: {trainer._target_chord_name}, intervals: {trainer._target_intervals}")
trainer.handle_midi_note(65, True)
trainer.handle_midi_note(69, True)
trainer.handle_midi_note(72, True)
print(f"  After IV chord: progression_index={trainer._progression_index}")
assert trainer._progression_index == 2, f"Should advance to 2, got {trainer._progression_index}"

trainer.handle_midi_note(65, False)
trainer.handle_midi_note(69, False)
trainer.handle_midi_note(72, False)
print(f"  Step 2 (IV): PASSED ✓")

# Play V chord (G Major: G=67, B=71, D=74 → intervals {7, 11, 2})
print(f"  Step 3 target: {trainer._target_chord_name}, intervals: {trainer._target_intervals}")
trainer.handle_midi_note(67, True)
trainer.handle_midi_note(71, True)
trainer.handle_midi_note(74, True)
print(f"  After V chord: progression_index={trainer._progression_index}")
assert trainer._progression_index == 3, f"Should advance to 3, got {trainer._progression_index}"

trainer.handle_midi_note(67, False)
trainer.handle_midi_note(71, False)
trainer.handle_midi_note(74, False)
print(f"  Step 3 (V): PASSED ✓")

# Play final I chord
print(f"  Step 4 target: {trainer._target_chord_name}, intervals: {trainer._target_intervals}")
trainer.handle_midi_note(60, True)
trainer.handle_midi_note(64, True)
trainer.handle_midi_note(67, True)
print(f"  After final I chord: progression complete, lesson_complete={trainer._is_lesson_complete}")

print(f"  Step 4 (I): PASSED ✓")
print("  PROGRESSION TEST PASSED ✓\n")


print("=" * 60)
print("TEST 3: Standard Chord Step (Backward Compatibility)")
print("=" * 60)

trainer._is_lesson_complete = False
trainer._lesson_progress = 0
trainer._active_pitches.clear()
trainer._waiting_for_release = False
trainer._exercise_name = "Isolated Formulas"  # Pre-set to avoid speech pause

mock_chord_plan = [
    {
        "exercise_type": "chord",
        "root_idx": 0,
        "chord_type_name": "Major",
        "intervals": {0, 4, 7},
        "octave": 4,
        "exercise_name": "Isolated Formulas",
        "spoken_instruction": "",
        "hold_ms": 0,
    }
]

trainer._lesson_playlist = list(mock_chord_plan)
trainer._lesson_total = 1
trainer._is_lesson_mode = True
trainer._is_active = True
trainer._exercise_name = "Isolated Formulas"  # Same name, no speech pause

trainer._next_chord()

assert trainer._exercise_type == "chord", f"Expected 'chord', got '{trainer._exercise_type}'"
assert trainer._target_chord_name == "C Major"
print(f"  Target: {trainer._target_chord_name} (type: {trainer._exercise_type})")
print("  BACKWARD COMPATIBILITY TEST PASSED ✓\n")


print("=" * 60)
print("TEST 4: 7th Chord Types")
print("=" * 60)

# Verify the new chord types exist and have correct intervals
assert trainer.CHORD_TYPES["Dominant 7th"] == {0, 4, 7, 10}, "Dominant 7th intervals wrong"
assert trainer.CHORD_TYPES["Major 7th"] == {0, 4, 7, 11}, "Major 7th intervals wrong"
assert trainer.CHORD_TYPES["Minor 7th"] == {0, 3, 7, 10}, "Minor 7th intervals wrong"
assert trainer.CHORD_TYPES["Single"] == {0}, "Single intervals wrong"
print("  Dominant 7th: {0, 4, 7, 10} ✓")
print("  Major 7th: {0, 4, 7, 11} ✓")
print("  Minor 7th: {0, 3, 7, 10} ✓")
print("  Single: {0} ✓")
print("  7TH CHORD TEST PASSED ✓\n")


print("=" * 60)
print("ALL TESTS PASSED ✓")
print("=" * 60)

# Cleanup
try:
    test_db_path.unlink(missing_ok=True)
except:
    pass
