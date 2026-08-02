"""
Shared MIDI pitch-number → name formatting.

The renderer and the song-note editor must agree on what a pitch is called, so
the table lives here rather than being restated in each. Spelling is fixed
(sharps for C♯/F♯, flats for E♭/A♭/B♭) — this is display naming for a
pedagogical label, not key-aware engraving spelling. Where a note carries a
music21 `spelling` tuple, the renderer's accidental logic uses that instead.
"""

# Index by `pitch % 12`.
PITCH_CLASS_NAMES = [
    "C", "C♯", "D", "E♭",
    "E", "F", "F♯", "G", "A♭",
    "A", "B♭", "B",
]


def pitch_class_name(pitch: int) -> str:
    """The bare letter name of a pitch, with no octave. MIDI 60 -> "C"."""
    return PITCH_CLASS_NAMES[int(pitch) % 12]


def pitch_name_with_octave(pitch: int) -> str:
    """
    Scientific pitch notation. MIDI 60 -> "C4" (middle C), 21 -> "A0".

    Octave numbering starts at -1 so that MIDI 0 is C-1, which is the
    convention every DAW and the MIDI spec itself use.
    """
    p = int(pitch)
    return f"{PITCH_CLASS_NAMES[p % 12]}{p // 12 - 1}"
