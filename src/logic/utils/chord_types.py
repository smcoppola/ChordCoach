"""
The chord and scale vocabulary the trainer plays.

Immutable, because the trainer shares these across every exercise: chord
intervals are frozensets of semitones above the root, patterns and names are
tuples.
"""

# Chord qualities by name: semitones above the root.
CHORD_TYPES = {
    "Major": frozenset({0, 4, 7}),
    "Minor": frozenset({0, 3, 7}),
    "Diminished": frozenset({0, 3, 6}),
    "Augmented": frozenset({0, 4, 8}),
    "Dominant 7th": frozenset({0, 4, 7, 10}),
    "Major 7th": frozenset({0, 4, 7, 11}),
    "Minor 7th": frozenset({0, 3, 7, 10}),
    "Single": frozenset({0}),
}

# Shorthand spellings accepted for the names above.
CHORD_TYPE_ALIASES = {
    "Major7": "Major 7th",
    "Minor7": "Minor 7th",
    "Dom7": "Dominant 7th",
    "Dominant7": "Dominant 7th",
    "Dim": "Diminished",
    "Aug": "Augmented",
    "Maj7": "Major 7th",
    "Min7": "Minor 7th",
    "major": "Major",
    "minor": "Minor",
}

# Five-finger scales: semitones above the root.
PENTASCALE_PATTERNS = {
    "Major": (0, 2, 4, 5, 7),      # W-W-H-W (C-D-E-F-G)
    "Minor": (0, 2, 3, 5, 7),      # W-H-W-W (C-D-Eb-F-G)
}

# Pitch-class names as the trainer displays them (index = MIDI pitch % 12).
ROOT_NOTES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
