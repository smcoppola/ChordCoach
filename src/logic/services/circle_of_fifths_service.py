"""
CircleOfFifthsService — Data service for the interactive Circle of Fifths.
"""
from PySide6.QtCore import QObject, Property, Signal, Slot # type: ignore

class CircleOfFifthsService(QObject):
    keyChanged = Signal(str)
    noteActive = Signal(int) # MIDI pitch

    def __init__(self):
        super().__init__()
        self._current_key = "C"
        
        # Major keys in circle order (sharps clockwise, flats counter-clockwise)
        self._major_order = ["C", "G", "D", "A", "E", "B", "Gb", "Db", "Ab", "Eb", "Bb", "F"]
        
        # Minor keys in circle order (starting with A)
        self._minor_order = ["A", "E", "B", "F#", "C#", "G#", "Eb", "Bb", "F", "C", "G", "D"]

        # Map each note name to its basic diatonic chords (I, ii, iii, IV, V, vi, vii°)
        # Simplified for now, will be enriched in Phase 6 with music21
        self._key_data = {
            "C": {"sharps": 0, "relative": "A", "diatonic": ["C", "Dm", "Em", "F", "G", "Am", "Bdim"]},
            "G": {"sharps": 1, "relative": "E", "diatonic": ["G", "Am", "Bm", "C", "D", "Em", "F#dim"]},
            "D": {"sharps": 2, "relative": "B", "diatonic": ["D", "Em", "F#m", "G", "A", "Bm", "C#dim"]},
            "A": {"sharps": 3, "relative": "F#", "diatonic": ["A", "Bm", "C#m", "D", "E", "F#m", "G#dim"]},
            "E": {"sharps": 4, "relative": "C#", "diatonic": ["E", "F#m", "G#m", "A", "B", "C#m", "D#dim"]},
            "B": {"sharps": 5, "relative": "G#", "diatonic": ["B", "C#m", "D#m", "E", "F#", "G#m", "A#dim"]},
            "Gb": {"sharps": 6, "relative": "Eb", "diatonic": ["Gb", "Abm", "Bbm", "Cb", "Db", "Ebm", "Fdim"]},
            "Db": {"sharps": -5, "relative": "Bb", "diatonic": ["Db", "Ebm", "Fm", "Gb", "Ab", "Bbm", "Cdim"]},
            "Ab": {"sharps": -4, "relative": "F", "diatonic": ["Ab", "Bbm", "Cm", "Db", "Eb", "Fm", "Gdim"]},
            "Eb": {"sharps": -3, "relative": "C", "diatonic": ["Eb", "Fm", "Gm", "Ab", "Bb", "Cm", "Ddim"]},
            "Bb": {"sharps": -2, "relative": "G", "diatonic": ["Bb", "Cm", "Dm", "Eb", "F", "Gm", "Adim"]},
            "F": {"sharps": -1, "relative": "D", "diatonic": ["F", "Gm", "Am", "Bb", "C", "Dm", "Edim"]},
        }

    @Property(str, notify=keyChanged)
    def currentKey(self): # type: ignore
        return self._current_key

    @currentKey.setter # type: ignore
    def currentKey(self, val):
        if self._current_key != val:
            self._current_key = val
            self.keyChanged.emit(val)

    @Slot(int)
    def handle_midi_note(self, pitch: int):
        """Called when a MIDI note is received."""
        self.noteActive.emit(pitch)

    @Slot(str, result="QVariantMap")
    def getKeyData(self, key_name: str) -> dict:
        """Returns metadata for a specific key."""
        return self._key_data.get(key_name, {})

    @Property(list, constant=True)
    def majorOrder(self):
        return self._major_order

    @Property(list, constant=True)
    def minorOrder(self):
        return self._minor_order
