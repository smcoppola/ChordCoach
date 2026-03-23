"""
CircleOfFifthsService — Data service for the interactive Circle of Fifths.
Handles chord detection from MIDI, tutorial state management, and
visual state for the QML overlay.
"""
from enum import IntEnum
from PySide6.QtCore import QObject, Property, Signal, Slot # type: ignore


class TutorialStage(IntEnum):
    OFF = 0
    GUIDED_INTRO = 1      # AI narration with synchronized visuals
    FEEL_THE_GRAVITY = 2  # Audio traces with cursor animation
    EXPLORATION = 3       # Open-ended MIDI-reactive mode
    GUIDED_CHALLENGE = 4  # Waypoint progression challenges
    SONG_MAPPING = 5      # Capstone


class CircleOfFifthsService(QObject):
    keyChanged = Signal(str)
    detectedChordChanged = Signal(str)

    # --- Tutorial Visual Signals ---
    tutorialShowBaseChanged = Signal(bool)
    tutorialShowMajorChanged = Signal(bool)
    tutorialShowMinorChanged = Signal(bool)
    tutorialHighlightKeyChanged = Signal(str)
    tutorialRevealedKeysChanged = Signal()
    highlightedChordsChanged = Signal()
    arrowsChanged = Signal()
    pathTraceChanged = Signal()
    waypointsChanged = Signal()
    tutorialStageChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._current_key = "C"
        self._detected_chord = ""

        # Major keys in circle order (sharps clockwise, flats counter-clockwise)
        self._major_order = ["C", "G", "D", "A", "E", "B", "Gb", "Db", "Ab", "Eb", "Bb", "F"]

        # Minor keys in circle order (starting with A)
        self._minor_order = ["A", "E", "B", "F#", "C#", "G#", "Eb", "Bb", "F", "C", "G", "D"]

        # Map each note name to its basic diatonic chords (I, ii, iii, IV, V, vi, vii°)
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

        # Chord detection lookup: interval set → (quality_suffix, quality_name)
        # Suffix is appended to root name for display (e.g. "C" + "m" = "Cm")
        self._interval_to_chord = {
            frozenset({0, 4, 7}): ("", "Major"),
            frozenset({0, 3, 7}): ("m", "Minor"),
            frozenset({0, 3, 6}): ("dim", "Diminished"),
            frozenset({0, 4, 8}): ("aug", "Augmented"),
            frozenset({0, 4, 7, 10}): ("7", "Dominant 7th"),
            frozenset({0, 4, 7, 11}): ("maj7", "Major 7th"),
            frozenset({0, 3, 7, 10}): ("m7", "Minor 7th"),
        }

        # Note names for MIDI pitch resolution
        self._note_names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

        # --- Tutorial State ---
        self._tutorial_show_base = False
        self._tutorial_show_major = False
        self._tutorial_show_minor = False
        self._tutorial_highlight_key = ""
        self._highlighted_chords: list[str] = []
        self._tutorial_revealed_keys: list[str] = []
        self._arrows: list[dict] = []
        self._path_trace: list[str] = []
        self._waypoints: list[str] = []
        self._tutorial_stage = TutorialStage.OFF

    # =====================================================================
    # Tutorial Visual Properties
    # =====================================================================

    @Property(bool, notify=tutorialShowBaseChanged)
    def tutorialShowBase(self):
        return self._tutorial_show_base

    @tutorialShowBase.setter
    def tutorialShowBase(self, val):
        if self._tutorial_show_base != val:
            self._tutorial_show_base = val
            self.tutorialShowBaseChanged.emit(val)

    @Property(bool, notify=tutorialShowMajorChanged)
    def tutorialShowMajor(self):
        return self._tutorial_show_major

    @tutorialShowMajor.setter
    def tutorialShowMajor(self, val):
        if self._tutorial_show_major != val:
            self._tutorial_show_major = val
            self.tutorialShowMajorChanged.emit(val)

    @Property(bool, notify=tutorialShowMinorChanged)
    def tutorialShowMinor(self):
        return self._tutorial_show_minor

    @tutorialShowMinor.setter
    def tutorialShowMinor(self, val):
        if self._tutorial_show_minor != val:
            self._tutorial_show_minor = val
            self.tutorialShowMinorChanged.emit(val)

    @Property(str, notify=tutorialHighlightKeyChanged)
    def tutorialHighlightKey(self):
        return self._tutorial_highlight_key

    @tutorialHighlightKey.setter
    def tutorialHighlightKey(self, val):
        if self._tutorial_highlight_key != val:
            self._tutorial_highlight_key = val
            self.tutorialHighlightKeyChanged.emit(val)

    @Property(list, notify=highlightedChordsChanged)
    def highlightedChords(self):
        return self._highlighted_chords

    @Property(list, notify=tutorialRevealedKeysChanged)
    def tutorialRevealedKeys(self):
        return self._tutorial_revealed_keys

    @Property(list, notify=arrowsChanged)
    def arrows(self):
        return self._arrows

    @Property(list, notify=pathTraceChanged)
    def pathTrace(self):
        return self._path_trace

    @Property(list, notify=waypointsChanged)
    def waypoints(self):
        return self._waypoints

    @Property(int, notify=tutorialStageChanged)
    def tutorialStage(self):
        return self._tutorial_stage

    # =====================================================================
    # Tutorial State Setters (called from AppCoordinator)
    # =====================================================================

    @Slot(bool, bool, bool, str)
    def set_tutorial_state(self, show_base: bool, show_major: bool, show_minor: bool, highlight_key: str):
        """Legacy unified setter for backward compatibility with existing narration scripts."""
        self._tutorial_show_base = show_base
        self._tutorial_show_major = show_major
        self._tutorial_show_minor = show_minor
        self._tutorial_highlight_key = highlight_key
        self.tutorialShowBaseChanged.emit(show_base)
        self.tutorialShowMajorChanged.emit(show_major)
        self.tutorialShowMinorChanged.emit(show_minor)
        self.tutorialHighlightKeyChanged.emit(highlight_key)

    @Slot(dict)
    def set_tutorial_state_v2(self, data: dict):
        """Full-featured setter for the expanded update_theory_visual tool."""
        # Core visibility flags (backward compatible)
        show_base = data.get("show_base", self._tutorial_show_base)
        show_major = data.get("show_major", self._tutorial_show_major)
        show_minor = data.get("show_minor", self._tutorial_show_minor)
        highlight_key = data.get("highlight_key", self._tutorial_highlight_key)

        self._tutorial_show_base = show_base
        self._tutorial_show_major = show_major
        self._tutorial_show_minor = show_minor
        self._tutorial_highlight_key = highlight_key
        self.tutorialShowBaseChanged.emit(show_base)
        self.tutorialShowMajorChanged.emit(show_major)
        self.tutorialShowMinorChanged.emit(show_minor)
        self.tutorialHighlightKeyChanged.emit(highlight_key)

        # Extended properties
        if "highlighted_chords" in data:
            self._highlighted_chords = data["highlighted_chords"]
            self.highlightedChordsChanged.emit()

        if "revealed_keys" in data:
            self._tutorial_revealed_keys = data["revealed_keys"]
            self.tutorialRevealedKeysChanged.emit()

        if "arrows" in data:
            self._arrows = data["arrows"]
            self.arrowsChanged.emit()

        if "path" in data:
            self._path_trace = data["path"]
            self.pathTraceChanged.emit()

        if "waypoints" in data:
            self._waypoints = data["waypoints"]
            self.waypointsChanged.emit()

        if "stage" in data:
            new_stage = int(data["stage"])
            if new_stage != self._tutorial_stage:
                self._tutorial_stage = TutorialStage(new_stage)
                self.tutorialStageChanged.emit(new_stage)

    @Slot()
    def advance_stage(self):
        """Move to the next tutorial stage."""
        next_val = self._tutorial_stage + 1
        if next_val <= TutorialStage.SONG_MAPPING:
            self._tutorial_stage = TutorialStage(next_val)
            self.tutorialStageChanged.emit(next_val)

    @Slot()
    def reset_tutorial(self):
        """Reset all tutorial state to defaults."""
        self._tutorial_show_base = False
        self._tutorial_show_major = False
        self._tutorial_show_minor = False
        self._tutorial_highlight_key = ""
        self._highlighted_chords = []
        self._tutorial_revealed_keys = []
        self._arrows = []
        self._path_trace = []
        self._waypoints = []
        self._tutorial_stage = TutorialStage.OFF
        self._detected_chord = ""

        self.tutorialShowBaseChanged.emit(False)
        self.tutorialShowMajorChanged.emit(False)
        self.tutorialShowMinorChanged.emit(False)
        self.tutorialHighlightKeyChanged.emit("")
        self.highlightedChordsChanged.emit()
        self.tutorialRevealedKeysChanged.emit()
        self.arrowsChanged.emit()
        self.pathTraceChanged.emit()
        self.waypointsChanged.emit()
        self.tutorialStageChanged.emit(0)
        self.detectedChordChanged.emit("")

    # =====================================================================
    # Chord Detection from MIDI
    # =====================================================================

    @Slot(list)
    def handle_midi_chord(self, pitches: list):
        """Resolve a set of simultaneously held MIDI pitches to a chord name.

        Called by the coordinator when the user plays 3+ keys at once.
        Updates detectedChord and currentKey on the circle.
        """
        if len(pitches) < 2:
            return

        # Normalize to pitch classes (0-11) and remove duplicates
        pitch_classes = sorted(set(p % 12 for p in pitches))

        # Try every pitch class as a potential root
        for root in pitch_classes:
            intervals = frozenset((p - root) % 12 for p in pitch_classes)
            match = self._interval_to_chord.get(intervals)
            if match:
                suffix, quality = match
                root_name = self._note_names[root]
                chord_name = f"{root_name}{suffix}"
                if chord_name != self._detected_chord:
                    self._detected_chord = chord_name
                    self.detectedChordChanged.emit(chord_name)
                    # Also update the circle's current key to the root
                    # Map sharps to their flat equivalents for circle lookup
                    circle_key = self._sharp_to_flat(root_name)
                    if circle_key != self._current_key:
                        self._current_key = circle_key
                        self.keyChanged.emit(circle_key)
                    print(f"CircleOfFifthsService: Detected chord: {chord_name} (root: {circle_key})")
                return

    def _sharp_to_flat(self, note: str) -> str:
        """Convert sharp note names to their flat equivalents for circle lookup."""
        mapping = {"C#": "Db", "F#": "Gb", "G#": "Ab"}
        return mapping.get(note, note)

    # =====================================================================
    # Prediction Arrows (Stage 3)
    # =====================================================================

    def generate_prediction_arrows(self, chord: str):
        """Generate 2-3 'suggested next' arrows from the current chord position.

        Uses the circle's geometry: clockwise = add a sharp (V),
        counterclockwise = add a flat (IV), relative minor/major.
        """
        # Strip quality suffix to get the root key
        root = chord.rstrip("m").rstrip("dim").rstrip("aug").rstrip("7").rstrip("maj")
        if not root:
            return

        try:
            idx = self._major_order.index(root)
        except ValueError:
            # Try minor order
            try:
                idx = self._minor_order.index(root)
            except ValueError:
                return

        arrows = []

        # Clockwise neighbor = V (Dominant)
        cw = self._major_order[(idx + 1) % 12]
        arrows.append({"from": root, "to": cw, "label": "V → Add Tension"})

        # Counter-clockwise neighbor = IV (Subdominant)
        ccw = self._major_order[(idx - 1) % 12]
        arrows.append({"from": root, "to": ccw, "label": "IV → Depart Home"})

        # Relative minor/major
        key_data = self._key_data.get(root)
        if key_data:
            rel = key_data["relative"]
            arrows.append({"from": root, "to": rel, "label": "Relative Minor"})

        self._arrows = arrows
        self.arrowsChanged.emit()

    # =====================================================================
    # Core Properties
    # =====================================================================

    @Property(str, notify=keyChanged)
    def currentKey(self): # type: ignore
        return self._current_key

    @currentKey.setter # type: ignore
    def currentKey(self, val):
        if self._current_key != val:
            self._current_key = val
            self.keyChanged.emit(val)

    @Property(str, notify=detectedChordChanged)
    def detectedChord(self):
        return self._detected_chord

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
