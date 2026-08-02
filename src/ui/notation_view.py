# =============================================================================
# File: notation_view.py
# Description: Advanced Notation Rendering Engine for ChordCoach Companion.
#              Handles grand staff music engraving with dual styles (Traditional
#              SMuFL/Bravura and Enhanced pedagogical style).
#              Implements strict SMuFL optical layout passes, including grid-based 
#              accidental staggering, unified chord stems, and deduplicated 
#              ledger line rendering.
# =============================================================================

import bisect
import logging
import time
from PySide6.QtCore import Qt, Property, Signal, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QFontDatabase, QBrush, QPolygonF,
    QPainterPath, QFontMetricsF, QLinearGradient, QRawFont,
)
from PySide6.QtQuick import QQuickPaintedItem

from logic.utils.pitch_names import PITCH_CLASS_NAMES

log = logging.getLogger(__name__)

# --- Pedagogical label constants -------------------------------------------
# The note letter must be legible on every note at every pane size. These
# constants are the contract that makes that guarantee provable; see
# tests/test_notation_labels.py.

MIN_LABEL_PX = 10.0         # absolute floor for a legible Inter Bold glyph
LABEL_TARGET_RATIO = 0.92   # preferred label pixel size as a fraction of capsule height
LABEL_PX_QUANTUM = 0.5      # rounding step, bounds the font/metrics cache size
DARK_LABEL = "#14181F"
LIGHT_LABEL = "#FFFFFF"
LUMINANCE_THRESHOLD = 0.179  # WCAG crossover between dark-on-light and light-on-dark
PAPER_COLOR = "#fcfcfc"      # matches EnhancedSheetMusic.qml background
LABEL_FONT_FAMILY = "Inter"
OUTSIDE_LABEL_MAX_ROWS = 4   # after this many collision bumps we draw anyway

# --- Grand staff geometry --------------------------------------------------
# Every dimension in this renderer is a multiple of one staff space, so these
# three numbers scale the entire engraving. EnhancedSheetMusic.qml keeps a
# hand-maintained mirror of them for its overlays (playhead, tap-to-seek,
# pedal marking) — change them together or the overlays desync from the ink.

STAFF_SPACE_RATIO = 0.0525   # one staff space as a fraction of the pane height
CAPSULE_HEIGHT_RATIO = 0.92  # enhanced duration capsule height, in staff spaces

# Treble-to-bass centre distance, deliberately expressed in staff spaces rather
# than as a fraction of the pane height. With fixed fractions the two staves
# stay put while the staff space grows, and past roughly s = 0.045 * height the
# treble's middle C (treble_cy + 3s) drops *below* the bass's (bass_cy - 3s) —
# the grand staff turns inside out. 6.0 is the engraving minimum (treble E4
# exactly two spaces above bass A3); 8.0 keeps a full space of air between the
# two middle-C ledger positions and leaves ~3.5 spaces of ledger headroom
# above and below the system.
STAFF_SEPARATION_SPACES = 8.0


def _srgb_to_linear(c: float) -> float:
    """Linearizes a single 0..1 sRGB channel per the WCAG 2.x definition."""
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: QColor) -> float:
    """WCAG relative luminance of a colour, 0.0 (black) to 1.0 (white)."""
    return (
        0.2126 * _srgb_to_linear(color.redF())
        + 0.7152 * _srgb_to_linear(color.greenF())
        + 0.0722 * _srgb_to_linear(color.blueF())
    )


def contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG contrast ratio between two colours, 1.0 (identical) to 21.0."""
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def label_color_for(fill: QColor) -> QColor:
    """
    Picks the label colour that maximises contrast against a capsule fill.

    Every colour this renderer can produce (the five finger colours, the
    completed/hit grey, and the monochrome grey) clears 4.5:1 under this rule.
    """
    return QColor(DARK_LABEL) if relative_luminance(fill) > LUMINANCE_THRESHOLD else QColor(LIGHT_LABEL)


class NotationView(QQuickPaintedItem):
    """
    Advanced Notation Rendering Engine
    Handles grand staff music engraving with dual styles:
    - Traditional: SMuFL/Bravura compliant standard notation with temporal clustering
    - Enhanced: Color-coded pedagogy style with note names
    """
    targetPitchesChanged = Signal()
    notationStyleChanged = Signal()
    scrollBeatChanged = Signal()
    evalBeatChanged = Signal()
    displayModeChanged = Signal()
    isScrollingModeChanged = Signal()
    evalNotesChanged = Signal()
    scrollingNotesChanged = Signal()
    evalNoteStatesChanged = Signal()
    notationColorModeChanged = Signal()
    songKeySharpsChanged = Signal()
    loopStartBeatChanged = Signal()
    loopEndBeatChanged = Signal()

    def __init__(self, parent=None):
        """
        Initializes the rendering engine, signaling properties, and SMuFL codepoints.
        """
        super().__init__(parent)
        self.setRenderTarget(QQuickPaintedItem.FramebufferObject)
        self._target_pitches = [] 
        self._notation_style = "enhanced" 
        self._notation_color_mode = "pedagogical" 
        self._display_mode = "trainer" 
        self._is_scrolling_mode = False
        self._song_key_sharps = 0
        
        self._scroll_beat = 0.0
        self._eval_beat = 0.0
        self._loop_start_beat = -1.0
        self._loop_end_beat = -1.0
        self._last_scroll_update_ms = 0.0
        
        self._eval_notes = []
        self._scrolling_notes = []
        self._scrolling_beats_index = []
        self._scrolling_beats_only = []
        self._eval_note_states = []

        # Label rendering caches. Metrics construction is expensive relative to
        # a 30fps repaint with hundreds of notes on screen, so fonts, metrics
        # and text advances are all memoised by quantised pixel size.
        self._label_font_cache: dict[float, QFont] = {}
        self._label_metrics_cache: dict[float, QFontMetricsF] = {}
        self._label_advance_cache: dict[tuple[str, float], float] = {}
        self._label_accidentals_ok: bool | None = None
        self._paint_error_count = 0
        self._last_paint_error_log = 0.0

        self._pedagogical_colors = {
            "1": "#4CAF50", 
            "2": "#FFB300", 
            "3": "#9C27B0", 
            "4": "#2196F3", 
            "5": "#F44336"  
        }
        
        # SMuFL Codepoints (Bravura)
        self.GLYPH_TREBLE_CLEF = "\uE050"
        self.GLYPH_BASS_CLEF = "\uE062"
        self.GLYPH_NOTEHEAD_WHOLE = "\uE0A2"
        self.GLYPH_NOTEHEAD_HALF = "\uE0A3"
        self.GLYPH_NOTEHEAD_BLACK = "\uE0A4"
        self.GLYPH_SHARP = "\uE262"
        self.GLYPH_FLAT = "\uE260"
        self.GLYPH_NATURAL = "\uE261"
        self.GLYPH_REST_WHOLE = "\uE4E3"
        self.GLYPH_REST_HALF = "\uE4E4"
        self.GLYPH_REST_QUARTER = "\uE4E5"
        self.GLYPH_REST_8TH = "\uE4E6"
        self.GLYPH_REST_16TH = "\uE4E7"
        self.GLYPH_FLAG_8TH_UP = "\uE240"
        self.GLYPH_FLAG_8TH_DOWN = "\uE241"
        self.GLYPH_FLAG_16TH_UP = "\uE242"
        self.GLYPH_FLAG_16TH_DOWN = "\uE243"
        self.GLYPH_AUGMENTATION_DOT = "\uE1E7"
        
        self.GLYPH_TIME_SIG = [
            "\uE080", "\uE081", "\uE082", "\uE083", "\uE084",
            "\uE085", "\uE086", "\uE087", "\uE088", "\uE089"
        ]
        
        self.GLYPH_DYNAMICS = {
            "p": "\uE520",
            "m": "\uE521",
            "f": "\uE522",
            "r": "\uE523",
            "s": "\uE524",
            "z": "\uE525",
            "n": "\uE526",
            "mf": "\uE52C",
            "mp": "\uE52D",
            "ff": "\uE52B",
            "pp": "\uE528",
            "fp": "\uE52A",
            "sfz": "\uE529",
        }
        
        # Map 12 MIDI notes to 0-6 diatonic steps
        self._diatonic_map = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
        # Shared with the song-note editor so both name a pitch the same way.
        self._pitch_names = PITCH_CLASS_NAMES
        self._smufl_family_cached = None

    def _get_smufl_family(self) -> str:
        """
        Discovers and caches the exact music font family name from QFontDatabase.
        Filters out 'Text' variants to maintain accurate optical spacing.
        
        Returns:
            str: Resolved font family name.
        """
        if self._smufl_family_cached:
            return self._smufl_family_cached
            
        families = QFontDatabase.families()
        for f in families:
            if "Bravura" in f and "Text" not in f:
                self._smufl_family_cached = f
                return f
        
        self._smufl_family_cached = "Bravura"
        return "Bravura"

    # --- QML Properties ---
    @Property(list, notify=targetPitchesChanged)
    def targetPitches(self):  # type: ignore[reportRedeclaration]
        return self._target_pitches

    @targetPitches.setter
    def targetPitches(self, value):  # type: ignore[reportRedeclaration]
        if self._target_pitches != value:
            self._target_pitches = value
            self.targetPitchesChanged.emit()
            self.update()

    @Property(str, notify=notationStyleChanged)
    def notationStyle(self):  # type: ignore[reportRedeclaration]
        return self._notation_style

    @notationStyle.setter
    def notationStyle(self, value):  # type: ignore[reportRedeclaration]
        safe_val = str(value).lower()
        if self._notation_style != safe_val:
            self._notation_style = safe_val
            self.notationStyleChanged.emit()
            self.update()
            
    @Property(float, notify=scrollBeatChanged)
    def scrollBeat(self):  # type: ignore[reportRedeclaration]
        return self._scroll_beat

    @scrollBeat.setter
    def scrollBeat(self, value):  # type: ignore[reportRedeclaration]
        if self._scroll_beat != value:
            old_val = self._scroll_beat
            self._scroll_beat = value
            self.scrollBeatChanged.emit()
            now = time.time() * 1000.0
            if (now - self._last_scroll_update_ms >= 33.0) or abs(value - old_val) > 0.1:
                self._last_scroll_update_ms = now
                self.update()

    @Property(float, notify=evalBeatChanged)
    def evalBeat(self):  # type: ignore[reportRedeclaration]
        return self._eval_beat

    @evalBeat.setter
    def evalBeat(self, value):  # type: ignore[reportRedeclaration]
        if self._eval_beat != value:
            self._eval_beat = value
            self.evalBeatChanged.emit()
            self.update()

    @Property(int, notify=songKeySharpsChanged)
    def songKeySharps(self):  # type: ignore[reportRedeclaration]
        return self._song_key_sharps

    @songKeySharps.setter
    def songKeySharps(self, value):  # type: ignore[reportRedeclaration]
        if self._song_key_sharps != value:
            self._song_key_sharps = value
            self.songKeySharpsChanged.emit()
            self.update()

    @Property(str, notify=displayModeChanged)
    def displayMode(self):  # type: ignore[reportRedeclaration]
        return self._display_mode

    @displayMode.setter
    def displayMode(self, value):  # type: ignore[reportRedeclaration]
        if self._display_mode != value:
            self._display_mode = value
            self.displayModeChanged.emit()
            self.update()

    @Property(bool, notify=isScrollingModeChanged)
    def isScrollingMode(self):  # type: ignore[reportRedeclaration]
        return self._is_scrolling_mode

    @isScrollingMode.setter
    def isScrollingMode(self, value):  # type: ignore[reportRedeclaration]
        if self._is_scrolling_mode != value:
            self._is_scrolling_mode = value
            self.isScrollingModeChanged.emit()
            self.update()

    @Property(list, notify=evalNotesChanged)
    def evalNotes(self):  # type: ignore[reportRedeclaration]
        return self._eval_notes

    @evalNotes.setter
    def evalNotes(self, value):  # type: ignore[reportRedeclaration]
        if self._eval_notes != value:
            self._eval_notes = value
            self.evalNotesChanged.emit()
            self.update()

    @Property(list, notify=scrollingNotesChanged)
    def scrollingNotes(self):  # type: ignore[reportRedeclaration]
        return self._scrolling_notes

    @scrollingNotes.setter
    def scrollingNotes(self, value):  # type: ignore[reportRedeclaration]
        if self._scrolling_notes != value:
            self._scrolling_notes = value
            notes_list = value or []
            self._scrolling_beats_index = [
                (float(item.get('start_beat', item.get('startBeat', 0.0))), i)
                for i, item in enumerate(notes_list)
            ]
            self._scrolling_beats_index.sort(key=lambda x: x[0])
            # Cached once here rather than rebuilt on every paint.
            self._scrolling_beats_only = [b for b, _i in self._scrolling_beats_index]
            self.scrollingNotesChanged.emit()
            self.update()

    @Property(list, notify=evalNoteStatesChanged)
    def evalNoteStates(self):  # type: ignore[reportRedeclaration]
        return self._eval_note_states

    @evalNoteStates.setter
    def evalNoteStates(self, value):  # type: ignore[reportRedeclaration]
        if self._eval_note_states != value:
            self._eval_note_states = value
            self.evalNoteStatesChanged.emit()
            self.update()

    @Property(str, notify=notationColorModeChanged)
    def notationColorMode(self):  # type: ignore[reportRedeclaration]
        return self._notation_color_mode

    @notationColorMode.setter
    def notationColorMode(self, value):  # type: ignore[reportRedeclaration]
        if self._notation_color_mode != value:
            self._notation_color_mode = value
            self.notationColorModeChanged.emit()
            self.update()

    @Property(float, notify=loopStartBeatChanged)
    def loopStartBeat(self):  # type: ignore[reportRedeclaration]
        return self._loop_start_beat

    @loopStartBeat.setter
    def loopStartBeat(self, value):  # type: ignore[reportRedeclaration]
        val = float(value)
        if abs(self._loop_start_beat - val) > 1e-4:
            self._loop_start_beat = val
            self.loopStartBeatChanged.emit()
            self.update()

    @Property(float, notify=loopEndBeatChanged)
    def loopEndBeat(self):  # type: ignore[reportRedeclaration]
        return self._loop_end_beat

    @loopEndBeat.setter
    def loopEndBeat(self, value):  # type: ignore[reportRedeclaration]
        val = float(value)
        if abs(self._loop_end_beat - val) > 1e-4:
            self._loop_end_beat = val
            self.loopEndBeatChanged.emit()
            self.update()

    # --- Engine Helpers ---

    def _get_diatonic_abs(self, pitch: int) -> int:
        """Calculates absolute diatonic scale degree for vertical positioning."""
        octave = pitch // 12
        note = pitch % 12
        return (octave * 7) + self._diatonic_map[note]

    # Step letters A-G map to diatonic offsets within an octave (C=0)
    _STEP_TO_DIA = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}

    def _get_diatonic_abs_spelled(self, pitch: int, spelling) -> int:
        """Like _get_diatonic_abs but uses music21 spelling (step, alter) for the diatonic
        step so that enharmonics like F♭ (MIDI 64) resolve to the F diatonic line rather
        than the E line.  Falls back to MIDI mapping when spelling is None."""
        if spelling is None:
            return self._get_diatonic_abs(pitch)
        step_letter, _alter = spelling
        octave = pitch // 12
        # Adjust octave boundary: C starts each MIDI octave, but e.g. B♭ in octave 4
        # has MIDI 70 which is octave 5 in integer division — compensate.
        dia_in_oct = self._STEP_TO_DIA.get(step_letter, self._diatonic_map[pitch % 12])
        # Re-derive the correct octave from MIDI and the diatonic letter
        # MIDI octave and diatonic letter occasionally disagree for cross-boundary sharps/flats
        midi_dia = self._diatonic_map[pitch % 12]
        if dia_in_oct == 0 and midi_dia == 6:  # C spelled, MIDI is B-ish region
            octave += 1
        elif dia_in_oct == 6 and midi_dia == 0:  # B spelled, MIDI is C-ish region
            octave -= 1
        return (octave * 7) + dia_in_oct

    def _get_accidental_from_spelling(self, pitch: int, spelling) -> tuple[bool, str]:
        """Returns (needs_accidental, glyph_type) using the note's own alter value.
        alter: 0 = natural (only needs natural sign if the key sig would force accidental),
               1/-1 = sharp/flat, 2/-2 = double sharp/flat.
        Falls back to key-based logic when spelling is None."""
        if spelling is None:
            return self._requires_accidental_for_key(pitch)
        step_letter, alter = spelling
        note_norm = pitch % 12
        white_keys = {0, 2, 4, 5, 7, 9, 11}
        sharps_order = [5, 0, 7, 2, 9, 4, 11]
        flats_order  = [11, 4, 9, 2, 7, 0, 5]
        s = self._song_key_sharps
        active_sharps = set(sharps_order[:s]) if s > 0 else set()
        active_flats  = set(flats_order[:-s]) if s < 0 else set()
        if alter == 0:
            # Natural — only needs a natural sign if the key would otherwise alter this note
            if note_norm in white_keys:
                if note_norm in active_sharps or note_norm in active_flats:
                    return (True, "natural")
            return (False, "")
        elif alter > 0:
            # Sharp/double-sharp — hide if already in key sig
            if note_norm in active_sharps:
                return (False, "")
            glyph = "sharp"
            return (True, glyph)
        else:
            # Flat/double-flat — hide if already in key sig
            if note_norm in active_flats:
                return (False, "")
            return (True, "flat")

    def _get_note_name(self, pitch: int) -> str:
        """Returns the formatted pitch name string."""
        return self._pitch_names[pitch % 12]

    def _coerce_pitch(self, value, default: int = 60) -> int:
        """
        Normalises a note's pitch to an int.

        Note dicts arrive from several producers (song import, pentascale,
        progression, steady pulse, evaluation), so a missing or malformed pitch
        must degrade to a placeholder rather than propagate a TypeError into
        layout and cost the whole frame.
        """
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def _requires_accidental_for_key(self, pitch: int) -> tuple[bool, str]:
        note_norm = pitch % 12
        white_keys = [0, 2, 4, 5, 7, 9, 11]
        sharps_order = [5, 0, 7, 2, 9, 4, 11]
        flats_order = [11, 4, 9, 2, 7, 0, 5]
        
        s = self._song_key_sharps
        active_sharps = set(sharps_order[:s]) if s > 0 else set()
        active_flats = set(flats_order[:-s]) if s < 0 else set()
        
        if note_norm in white_keys:
            if note_norm in active_sharps or note_norm in active_flats:
                return (True, "natural")
            return (False, "")
            
        black_key_map = {1: (0, 2), 3: (2, 4), 6: (5, 7), 8: (7, 9), 10: (9, 11)}
        sharp_base, flat_base = black_key_map[note_norm]
        
        if sharp_base in active_sharps: return (False, "")
        if flat_base in active_flats: return (False, "")
            
        if s > 0: return (True, "sharp")
        elif s < 0: return (True, "flat")
        else:
            if note_norm in [1, 6]: return (True, "sharp")
            return (True, "flat")

    def _duration_to_glyph(self, duration: float, tuplet: dict | None = None) -> tuple:
        """
        Maps a duration (in quarterLength beats) and optional tuplet spec to SMuFL base notehead,
        flag type, and augmentation dot count.
        """
        eff_dur = float(duration)
        if isinstance(tuplet, dict):
            actual = float(tuplet.get("actual", 1))
            normal = float(tuplet.get("normal", 1))
            if normal > 0:
                eff_dur = eff_dur * (actual / normal)

        table = [
            (6.0,   self.GLYPH_NOTEHEAD_WHOLE, None,   1),
            (4.0,   self.GLYPH_NOTEHEAD_WHOLE, None,   0),
            (3.0,   self.GLYPH_NOTEHEAD_HALF,  None,   1),
            (2.0,   self.GLYPH_NOTEHEAD_HALF,  None,   0),
            (1.5,   self.GLYPH_NOTEHEAD_BLACK, None,   1),
            (1.0,   self.GLYPH_NOTEHEAD_BLACK, None,   0),
            (0.75,  self.GLYPH_NOTEHEAD_BLACK, "8th",  1),
            (0.5,   self.GLYPH_NOTEHEAD_BLACK, "8th",  0),
            (0.375, self.GLYPH_NOTEHEAD_BLACK, "16th", 1),
            (0.25,  self.GLYPH_NOTEHEAD_BLACK, "16th", 0),
        ]

        best_match = table[0]
        min_diff = abs(eff_dur - table[0][0])
        for entry in table:
            diff = abs(eff_dur - entry[0])
            if diff < min_diff:
                min_diff = diff
                best_match = entry

        return best_match[1], best_match[2], best_match[3]

    def _draw_time_signature(self, painter: QPainter, x: float, num: int, den: int, treble_y: float, bass_y: float, s: float, color: QColor):
        """Draws stacked SMuFL time signature digits centered on middle lines of treble and bass staves."""
        old_pen = painter.pen()
        painter.setPen(color)
        old_font = painter.font()

        font_family = self._get_smufl_family()
        ts_font = QFont(font_family)
        # Pixels, not points, like every other SMuFL font here: a point size is
        # resolved against the paint device's DPI, so on a scaled display the
        # time signature would stop tracking the staff it is drawn on. SMuFL
        # sets 1 em = 4 staff spaces, which makes the digits 2 spaces tall.
        ts_font.setPixelSize(max(1, int(s * 4.0)))
        painter.setFont(ts_font)

        num_glyph = "".join(self.GLYPH_TIME_SIG[int(d)] if d.isdigit() else d for d in str(num))
        den_glyph = "".join(self.GLYPH_TIME_SIG[int(d)] if d.isdigit() else d for d in str(den))

        # Centred on the glyph ink rather than by aligning inside a box: the
        # SMuFL em box is twice the height of the two-space slot each digit
        # occupies, so a box-aligned digit is positioned by the font's
        # ascent/descent and drifts off the staff whenever the size changes.
        fm = QFontMetricsF(ts_font)
        for ref_y in (treble_y, bass_y):
            # Numerator fills the upper half of the staff, denominator the lower.
            for glyph, cy in ((num_glyph, ref_y - s), (den_glyph, ref_y + s)):
                tight = fm.tightBoundingRect(glyph)
                painter.drawText(QPointF(
                    x - tight.width() / 2.0 - tight.x(),
                    cy - tight.height() / 2.0 - tight.y(),
                ), glyph)

        painter.setFont(old_font)
        painter.setPen(old_pen)

    def _get_finger_color(self, finger: int) -> QColor:
        if self._notation_color_mode == "monochrome":
            return QColor("#555555")

        color_hex = self._pedagogical_colors.get(str(finger), "#111111")
        return QColor(color_hex)

    # --- Pedagogical label engine -------------------------------------------
    # Requirement: every note shows its letter, always. Five mechanisms combine
    # to guarantee that:
    #   1. _capsule_width never returns a capsule narrower than its own label
    #   2. sizing is in pixels (not points), so it holds at any DPI
    #   3. label_color_for guarantees >= 4.5:1 contrast on every fill
    #   4. when the pane is too short for an inside label, _plan_note_label
    #      falls back to outside placement rather than giving up
    #   5. accidental glyphs degrade to ASCII if the font lacks them

    def _label_pad_x(self, s: float) -> float:
        """Horizontal breathing room between the label and the capsule rim."""
        return max(2.0, s * 0.20)

    def _capsule_gap(self, s: float) -> float:
        """Gap subtracted from a note's full duration so adjacent notes read as separate."""
        return max(2.0, s * 0.25)

    def _quantize_px(self, px: float) -> float:
        """Snaps a pixel size to the cache quantum, never below the legibility floor."""
        snapped = round(px / LABEL_PX_QUANTUM) * LABEL_PX_QUANTUM
        return max(MIN_LABEL_PX, snapped)

    def _label_font(self, px: float) -> QFont:
        """Returns a cached bold label font at the given pixel size."""
        font = self._label_font_cache.get(px)
        if font is None:
            font = QFont(LABEL_FONT_FAMILY)
            font.setPixelSize(max(1, round(px)))
            font.setWeight(QFont.Weight.Bold)
            self._label_font_cache[px] = font
        return font

    def _label_metrics(self, px: float) -> QFontMetricsF:
        """Returns cached font metrics at the given pixel size."""
        fm = self._label_metrics_cache.get(px)
        if fm is None:
            fm = QFontMetricsF(self._label_font(px))
            self._label_metrics_cache[px] = fm
        return fm

    def _text_advance(self, text: str, px: float) -> float:
        """Cached horizontal advance of a label string at a given pixel size."""
        key = (text, px)
        adv = self._label_advance_cache.get(key)
        if adv is None:
            adv = self._label_metrics(px).horizontalAdvance(text)
            self._label_advance_cache[key] = adv
        return adv

    def _accidentals_renderable(self) -> bool:
        """
        Probes once whether the label font actually contains U+266F/U+266D.

        Inter's coverage of these codepoints is version dependent. Without this
        check Qt silently font-merges from an arbitrary system font, which
        renders inconsistently across machines.

        Uses QRawFont rather than QFontMetrics.inFont(), which reports False
        even for fonts that do contain the glyph (Bravura included).
        """
        if self._label_accidentals_ok is None:
            try:
                raw = QRawFont.fromFont(self._label_font(self._quantize_px(16.0)))
                self._label_accidentals_ok = bool(
                    raw.supportsCharacter(0x266F) and raw.supportsCharacter(0x266D)
                )
            except Exception:
                self._label_accidentals_ok = False
        return self._label_accidentals_ok

    def _note_label_text(self, pitch) -> str:
        """The letter shown on a note, with an ASCII fallback for missing accidental glyphs."""
        name = self._get_note_name(self._coerce_pitch(pitch))
        if not self._accidentals_renderable():
            name = name.replace("♯", "#").replace("♭", "b")
        return name

    def _capsule_width(self, note: dict, ppb: float, s: float, label_text: str | None = None) -> float:
        """
        The single source of truth for how wide an enhanced capsule is.

        Width encodes duration, floored so that a note is never narrower than
        its own label needs at MIN_LABEL_PX. Only notes shorter than roughly a
        32nd reach that floor, where the width difference is imperceptible
        anyway. Culling and drawing both call this, so they can never disagree.
        """
        raw = note.get('duration_beats', note.get('durationBeats', 1))
        try:
            duration = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            duration = 1.0

        natural = duration * ppb - self._capsule_gap(s)
        floor_w = s * 0.9
        if label_text:
            floor_w = max(floor_w, self._text_advance(label_text, MIN_LABEL_PX) + 2 * self._label_pad_x(s))
        return max(natural, floor_w)

    def _plan_note_label(self, text: str, cap_w: float, h: float, s: float) -> dict:
        """
        Decides how a note's letter is drawn. Never returns "don't draw it".

        Returns {'text', 'px', 'inside'}. `inside` False means the caller must
        place the label outside the capsule (see _draw_outside_label), which
        happens when the pane is too short for a legible glyph to fit within
        the capsule height. That is a pane-global condition, so all labels flip
        together and the result reads as deliberate rather than scattered.
        """
        if not text:
            return {'text': text, 'px': MIN_LABEL_PX, 'inside': False}

        avail_w = cap_w - 2 * self._label_pad_x(s)
        avail_h = h - 2 * max(1.0, s * 0.08)
        if avail_w <= 0 or avail_h <= 0:
            return {'text': text, 'px': MIN_LABEL_PX, 'inside': False}

        def fits(px: float) -> bool:
            # Height is measured from the actual glyph box rather than inferred
            # from the pixel size: note names are all caps with no descenders,
            # so an em-based estimate rejects sizes that would fit comfortably.
            if self._text_advance(text, px) > avail_w:
                return False
            return self._label_metrics(px).tightBoundingRect(text).height() <= avail_h

        px = self._quantize_px(h * LABEL_TARGET_RATIO)
        if not fits(px):
            # Advance scales very nearly linearly with pixel size, so one
            # proportional correction lands within a quantum or two; the loop
            # then walks down to the legibility floor.
            adv = self._text_advance(text, px)
            if adv > avail_w:
                px = self._quantize_px(px * (avail_w / adv))
            while px > MIN_LABEL_PX and not fits(px):
                px = self._quantize_px(px - LABEL_PX_QUANTUM)

        if fits(px):
            return {'text': text, 'px': px, 'inside': True}
        return {'text': text, 'px': MIN_LABEL_PX, 'inside': False}

    def _draw_label_centered(self, painter: QPainter, text: str, px: float, cx: float, cy: float, color: QColor):
        """
        Draws a label optically centred on (cx, cy).

        Uses tightBoundingRect rather than Qt.AlignCenter: note names are all
        caps with no descenders, so alignment based on ascent/descent sits them
        visibly low inside the capsule.
        """
        font = self._label_font(px)
        fm = self._label_metrics(px)
        painter.setFont(font)
        painter.setPen(QPen(color))

        tight = fm.tightBoundingRect(text)
        tx = cx - tight.width() / 2.0 - tight.x()
        ty = cy - tight.height() / 2.0 - tight.y()
        painter.drawText(QPointF(tx, ty), text)

    def _draw_outside_label(self, painter: QPainter, text: str, px: float, cx: float, cy: float, color: QColor):
        """
        Draws a label outside the capsule with a paper-coloured halo so it stays
        readable over staff lines, ledger lines and neighbouring capsules.
        """
        font = self._label_font(px)
        fm = self._label_metrics(px)
        painter.setFont(font)

        tight = fm.tightBoundingRect(text)
        tx = cx - tight.width() / 2.0 - tight.x()
        ty = cy - tight.height() / 2.0 - tight.y()

        halo = QColor(PAPER_COLOR)
        painter.setPen(QPen(halo))
        for dx, dy in ((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)):
            painter.drawText(QPointF(tx + dx, ty + dy), text)

        painter.setPen(QPen(color))
        painter.drawText(QPointF(tx, ty), text)

    def _place_outside_label(self, placed: list, cx: float, cy: float, w: float, h: float, above: bool) -> float:
        """
        Resolves outside-label collisions by stacking rows away from the staff.

        Mirrors the accidental-column algorithm used for note spacing. Rows are
        capped: past OUTSIDE_LABEL_MAX_ROWS the label is drawn anyway. Mild
        overlap under a halo is acceptable; a missing letter is not.
        """
        step = (h + 2.0) * (-1.0 if above else 1.0)
        y = cy
        for _row in range(OUTSIDE_LABEL_MAX_ROWS):
            rect = QRectF(cx - w / 2.0, y - h / 2.0, w, h)
            if not any(rect.intersects(r) for r in placed):
                break
            y += step
        placed.append(QRectF(cx - w / 2.0, y - h / 2.0, w, h))
        return y

    def _get_layout_for_notes(self, note_array: list, current_beat: float, start_x: float, ppb: float, treble_y: float, bass_y: float, s: float) -> list:
        """
        Computes spatial layout, interval staggering, and accidental collision grids for a sequence of notes.
        """
        groups = {}
        for i, note in enumerate(note_array):
            start_beat = note.get('start_beat', note.get('startBeat', 0))
            if start_beat not in groups:
                groups[start_beat] = []
            groups[start_beat].append((i, note))

        layout_results: list[dict | None] = [None] * len(note_array)

        for start_beat, group in groups.items():
            group.sort(key=lambda item: self._coerce_pitch(item[1].get('pitch')))

            accidental_positions = []
            base_x = start_x + ((start_beat - current_beat) * ppb)
            notehead_offsets = {}

            for index_in_group, (original_index, note) in enumerate(group):
                # Fail-soft per note: layout runs before the draw loop, so an
                # unlayoutable note here would otherwise cost the whole frame.
                try:
                    base_x = start_x + ((start_beat - current_beat) * ppb)

                    if note.get("is_barline") or note.get("is_rest") or note.get("is_time_sig") or note.get("is_dynamic"):
                        hand = note.get('hand', 'R')
                        is_treble = (hand in ["R", "right"])
                        ref_y = treble_y if is_treble else bass_y
                        y = ref_y
                        if note.get("is_rest") and note.get("duration_beats", 1) >= 4.0:
                            y = ref_y - (s / 2.0)
                        elif note.get("is_dynamic"):
                            # 1.5 spaces below the bottom staff line. Was 4.5,
                            # which at the current staff space lands within a
                            # few pixels of the pane's bottom edge.
                            y = ref_y + (s * 3.5)

                        bar_offset = -s * 1.5 if note.get('is_barline') else 0.0

                        layout_results[original_index] = {
                            'note': note,
                            'x': base_x + bar_offset,
                            'y': y,
                            'notehead_offset_x': 0.0,
                            'accidental_offset_x': 0.0,
                            'steps_from_ref': 0,
                            'ref_y': ref_y
                        }
                        continue

                    pitch = self._coerce_pitch(note.get('pitch'))
                    hand = note.get('hand', 'R')

                    # Step 4: Map pitch to target staff plane
                    is_treble = True if hand in ["R", "right"] else False if hand in ["L", "left"] else pitch >= 60
                    ref_pitch = 71 if is_treble else 50
                    ref_y = treble_y if is_treble else bass_y

                    spelling = note.get('spelling')  # (step_letter, alter) from music21, or None
                    steps_from_ref = self._get_diatonic_abs_spelled(pitch, spelling) - self._get_diatonic_abs(ref_pitch)
                    y = ref_y - (steps_from_ref * (s / 2))

                    notehead_offset_x = 0.0
                    accidental_offset_x = 0.0

                    # Step 5: Detect interval of a second and apply alternating cluster shift
                    if index_in_group > 0:
                        prev = group[index_in_group - 1][1]
                        prev_pitch = self._coerce_pitch(prev.get('pitch'))
                        # Compare on the spelled diatonic step, matching the value
                        # used for y placement — otherwise the stagger decision and
                        # the vertical position disagree for enharmonics like F♭.
                        prev_steps = self._get_diatonic_abs_spelled(prev_pitch, prev.get('spelling'))
                        if abs(self._get_diatonic_abs_spelled(pitch, spelling) - prev_steps) < 2:
                            if notehead_offsets.get(index_in_group - 1, 0.0) == 0.0:
                                notehead_offset_x = s * 1.15
                    notehead_offsets[index_in_group] = notehead_offset_x

                    # Step 6: Grid-based Accidental collision resolution
                    is_acc, _acc_type = self._get_accidental_from_spelling(pitch, spelling)
                    if is_acc:
                        column = 0
                        while True:
                            collision = False
                            for prev_y, prev_col in accidental_positions:
                                if prev_col == column and abs(y - prev_y) < (s * 2.5):
                                    collision = True
                                    break
                            if not collision:
                                break
                            column += 1

                        accidental_offset_x -= (column * s * 1.2)
                        accidental_positions.append((y, column))

                    # Step 7: Push computed payload
                    layout_results[original_index] = {
                        'note': note,
                        'x': base_x,
                        'y': y,
                        'notehead_offset_x': notehead_offset_x,
                        'accidental_offset_x': accidental_offset_x,
                        'steps_from_ref': steps_from_ref,
                        'ref_y': ref_y
                    }
                except Exception:
                    layout_results[original_index] = None
                    self._log_paint_error("note layout")

        return layout_results

    # --- Render Engine ---

    def paint(self, painter: QPainter):
        """
        Executes the main render loop, configuring core optical constraints and routing drawing paths.
        
        Args:
            painter (QPainter): The PySide6 drawing context.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        rect = self.boundingRect()
        width = rect.width()
        height = rect.height()

        # Step 1: Initialize optical constants matching standard screen proportions.
        # The staves are placed a fixed number of staff spaces apart rather than
        # at fixed height fractions, so the system stays a valid grand staff at
        # any STAFF_SPACE_RATIO (see the constant's note on middle C).
        s = height * STAFF_SPACE_RATIO
        half_sep = (s * STAFF_SEPARATION_SPACES) / 2.0
        treble_cy = (height * 0.5) - half_sep
        bass_cy = (height * 0.5) + half_sep
        note_start_x = width * 0.28
        ppb = width * 0.10
        
        # Step 2: Establish the 5-line staff foundations
        self._draw_staff_lines(painter, width, treble_cy, s)
        self._draw_staff_lines(painter, width, bass_cy, s)
        
        # Step 3: Instantiate Clefs using strictly scaled QFont metrics
        clef_font = QFont(self._get_smufl_family())
        clef_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        clef_font.setPixelSize(int(s * 4.0))  # SMuFL: 1 em = 4 staff spaces
        painter.setFont(clef_font)
        painter.setPen(QPen(QColor("#222222")))
        g4_y = treble_cy + s 
        painter.drawText(int(width * 0.04), int(g4_y), self.GLYPH_TREBLE_CLEF)
        f3_y = bass_cy - s 
        painter.drawText(int(width * 0.04), int(f3_y), self.GLYPH_BASS_CLEF)

        # Step 4: Contextual routing based on simulation phase
        painter.save()
        content_rect = QRectF(width * 0.15, 0, width * 0.85, height)
        painter.setClipRect(content_rect)

        # Draw static time signature header next to key signature
        header_ts = (4, 4)
        for item in self._scrolling_notes:
            if item.get("is_time_sig"):
                header_ts = (item.get("numerator", 4), item.get("denominator", 4))
                break
        key_count = abs(self._song_key_sharps) if (self._song_key_sharps != 0 and self._notation_style == "traditional") else 0
        # The signature block hangs a fixed number of staff spaces left of the
        # first note. On a tall, narrow pane that offset outgrows the gap and
        # would put the signature on top of the clef and outside content_rect,
        # so it is floored just right of both.
        sig_x = max(width * 0.16, note_start_x - (s * 5.0))
        ts_x = sig_x + (key_count * s * 0.8) + (s * 1.5 if key_count > 0 else 0)
        self._draw_time_signature(painter, ts_x, header_ts[0], header_ts[1], treble_cy, bass_cy, s, QColor("#222222"))

        # Draw translucent loop shading behind staff/notes if A/B loop bounds are active
        if self._loop_start_beat >= 0 and self._loop_end_beat > self._loop_start_beat:
            curr_beat = self._eval_beat if self._display_mode == "evaluation" else self._scroll_beat
            x1 = note_start_x + (self._loop_start_beat - curr_beat) * ppb
            x2 = note_start_x + (self._loop_end_beat - curr_beat) * ppb
            if x2 > x1:
                loop_top = treble_cy - (s * 3.5)
                loop_height = (bass_cy - treble_cy) + (s * 7.0)
                loop_rect = QRectF(x1, loop_top, x2 - x1, loop_height)
                painter.setBrush(QBrush(QColor(33, 150, 243, 40)))  # Translucent blue fill
                painter.setPen(QPen(QColor(33, 150, 243, 160), 1.5, Qt.PenStyle.DashLine))
                painter.drawRect(loop_rect)

        if self._display_mode == "evaluation":
            self._render_scrolling_array(
                painter, self._eval_notes, self._eval_beat, 
                note_start_x, ppb, treble_cy, bass_cy, s
            )
        elif self._is_scrolling_mode:
            self._draw_key_signature(painter, sig_x, treble_cy, bass_cy, s)
            self._render_scrolling_array(
                painter, self._scrolling_notes, self._scroll_beat, 
                note_start_x, ppb, treble_cy, bass_cy, s
            )
        else:
            self._draw_key_signature(painter, sig_x, treble_cy, bass_cy, s)
            self._render_static_targets(
                painter, note_start_x, treble_cy, bass_cy, s
            )
        
        painter.restore()

    def _group_beam_runs(self, all_stems: list) -> list:
        """
        Partitions stems into beam groups, honouring the beam state stream.

        A group never spans both staves. all_stems is ordered by beat across
        both hands, so grouping on beam state alone let a right-hand "start"
        pair with the following left-hand "continue" and draw a beam polygon
        from a treble stem tip down to a bass stem tip.
        """
        groups: list[list] = []
        curr: list = []
        curr_staff = None

        for stem in all_stems:
            if curr and stem['is_treble'] != curr_staff:
                groups.append(curr)
                curr = []
                curr_staff = None

            bstate = stem['beam_state']
            if bstate in ('start', 'begin'):
                if curr:
                    groups.append(curr)
                curr = [stem]
                curr_staff = stem['is_treble']
            elif bstate == 'continue':
                curr.append(stem)
                curr_staff = stem['is_treble']
            elif bstate in ('end', 'stop'):
                curr.append(stem)
                groups.append(curr)
                curr = []
                curr_staff = None
            else:
                if curr:
                    groups.append(curr)
                    curr = []
                    curr_staff = None

        if curr:
            groups.append(curr)
        return groups

    def _render_tuplet_brackets(self, painter: QPainter, layout_data: list, s: float):
        """
        Draws thin tuplet brackets with centered actual digit over tuplet note groups in traditional mode.
        """
        old_pen = painter.pen()
        old_font = painter.font()

        # Like beams, a tuplet bracket must stay on one staff — layout_data
        # interleaves both hands, so grouping without a staff check produced
        # brackets spanning from the treble staff down to the bass staff.
        tuplet_groups = []
        curr_group = []
        curr_ref_y = None
        for layout in layout_data:
            if layout is None: continue
            n = layout['note']
            t_spec = n.get('tuplet')
            if isinstance(t_spec, dict):
                pos = str(t_spec.get('pos', '')).lower()
                if curr_group and layout['ref_y'] != curr_ref_y:
                    tuplet_groups.append(curr_group)
                    curr_group = []

                if pos == 'start' or not curr_group:
                    if curr_group:
                        tuplet_groups.append(curr_group)
                    curr_group = [layout]
                else:
                    curr_group.append(layout)
                curr_ref_y = layout['ref_y']

                if pos in ('stop', 'end'):
                    tuplet_groups.append(curr_group)
                    curr_group = []
                    curr_ref_y = None
            else:
                if curr_group:
                    tuplet_groups.append(curr_group)
                    curr_group = []
                    curr_ref_y = None
        if curr_group:
            tuplet_groups.append(curr_group)

        for group in tuplet_groups:
            if len(group) < 2:
                continue
            first_n = group[0]['note']
            t_spec = first_n.get('tuplet', {})
            actual = int(t_spec.get('actual', 3))

            min_x = min(l['x'] for l in group)
            max_x = max(l['x'] for l in group) + s * 1.0
            min_y = min(l['y'] for l in group)

            bracket_y = min_y - s * 2.5
            bracket_pen = QPen(QColor("#111111"), max(1.0, s * 0.12), Qt.PenStyle.SolidLine)
            painter.setPen(bracket_pen)

            hook_h = s * 0.4
            mid_x = (min_x + max_x) / 2.0
            gap_w = s * 1.2

            painter.drawLine(int(min_x), int(bracket_y + hook_h), int(min_x), int(bracket_y))
            painter.drawLine(int(min_x), int(bracket_y), int(mid_x - gap_w / 2), int(bracket_y))

            painter.drawLine(int(mid_x + gap_w / 2), int(bracket_y), int(max_x), int(bracket_y))
            painter.drawLine(int(max_x), int(bracket_y), int(max_x), int(bracket_y + hook_h))

            dig_font = QFont("Inter", int(s * 1.1), QFont.Weight.Bold)
            painter.setFont(dig_font)
            painter.setPen(QPen(QColor("#111111")))
            rect = QRectF(mid_x - gap_w / 2, bracket_y - s * 0.8, gap_w, s * 1.6)
            painter.drawText(rect, Qt.AlignCenter, str(actual))

        painter.setPen(old_pen)
        painter.setFont(old_font)

    def _render_stems(self, painter: QPainter, clusters: dict, s: float, current_beat: float = 0.0):
        """
        Three-pass beam-aware stem renderer.

        Pass 1 — collect unclamped stem geometry for every non-whole cluster.
        Pass 2 — for each beam group: anchor the beam at the most-extreme natural
                  stem tip, apply a slope clamped to ±0.5 staff spaces, then assign
                  each beamed stem a tip_y on that line so every stem reaches the beam.
        Pass 3 — draw stems (to tip_y), flags for isolated notes, then filled
                  QPolygonF beam rectangles.

        Args:
            painter (QPainter): The PySide6 drawing context.
            clusters (dict): Layout elements grouped by (start_beat, is_treble).
            s (float): Fundamental staff space unit (pixels).
        """
        stem_weight  = max(1.0, s * 0.08)
        beam_thick   = max(2.0, s * 0.35)
        beam_gap     = s * 0.45
        half         = beam_thick / 2.0

        # ── PASS 1: collect geometry ──────────────────────────────────────────
        all_stems = []
        for key, cluster in sorted(clusters.items(), key=lambda kv: kv[0][0]):
            start_beat, is_treble = key
            dur = cluster[0]['note'].get('duration_beats', cluster[0]['note'].get('durationBeats', 1))
            if dur >= 4.0:
                continue

            min_pitch   = min(l['note'].get('pitch', 60) for l in cluster)
            max_pitch   = max(l['note'].get('pitch', 60) for l in cluster)
            ref_mid     = 71 if is_treble else 50
            mid_dia     = self._get_diatonic_abs(ref_mid)
            stem_up     = (mid_dia - self._get_diatonic_abs(min_pitch)) > \
                          (self._get_diatonic_abs(max_pitch) - mid_dia)

            ref_y  = cluster[0]['ref_y']
            min_y  = min(l['y'] for l in cluster)
            max_y  = max(l['y'] for l in cluster)
            base_x = cluster[0]['x']

            if stem_up:
                max_off      = max(l['notehead_offset_x'] for l in cluster)
                stem_x       = base_x + max_off + s * 0.6 + s * 1.18
                notehead_y   = max_y
                unclamped    = min_y - s * 3.5          # natural tip, no ref_y clamp
            else:
                min_off      = min(l['notehead_offset_x'] for l in cluster)
                stem_x       = base_x + min_off + s * 0.6
                notehead_y   = min_y
                unclamped    = max_y + s * 3.5

            beam_state = cluster[0]['note'].get('beam') if dur < 1.0 else None

            all_stems.append({
                'beat':        start_beat,
                'is_treble':   is_treble,
                'stem_up':     stem_up,
                'stem_x':      stem_x,
                'notehead_y':  notehead_y,
                'unclamped':   unclamped,
                'ref_y':       ref_y,
                'dur':         dur,
                'beam_state':  beam_state,
                'tip_y':       None,    # filled in pass 2
            })

        # ── PASS 2: compute beam lines; assign tip_y to beamed stems ─────────
        beam_groups = self._group_beam_runs(all_stems)

        beamed_stems_set = set()
        for group in beam_groups:
            if len(group) < 2:
                continue

            for st in group:
                beamed_stems_set.add(id(st))

            stem_up = group[0]['stem_up']
            if stem_up:
                anchor_stem = min(group, key=lambda st: st['unclamped'])
            else:
                anchor_stem = max(group, key=lambda st: st['unclamped'])

            anchor_x = anchor_stem['stem_x']
            anchor_y = anchor_stem['unclamped']

            x_first = group[0]['stem_x']
            x_last  = group[-1]['stem_x']
            dx_total = max(1.0, x_last - x_first)

            y_first_nat = group[0]['unclamped']
            y_last_nat  = group[-1]['unclamped']
            raw_slope   = (y_last_nat - y_first_nat) / dx_total
            clamped_slope = max(-0.5, min(0.5, raw_slope))

            for st in group:
                dx = st['stem_x'] - anchor_x
                st['tip_y'] = anchor_y + (dx * clamped_slope)

        for st in all_stems:
            if id(st) not in beamed_stems_set:
                ref_y = st['ref_y']
                if st['stem_up']:
                    st['tip_y'] = min(st['unclamped'], ref_y - s * 2.0)
                else:
                    st['tip_y'] = max(st['unclamped'], ref_y + s * 2.0)

        # ── PASS 3: draw stems and flags ──────────────────────────────────────
        def _stem_done(beat: float, dur: float, current: float) -> bool:
            return current >= beat + dur

        for st in all_stems:
            stem_x     = st['stem_x']
            notehead_y = st['notehead_y']
            tip_y      = st['tip_y']
            stem_up    = st['stem_up']
            dur        = st['dur']

            is_done = _stem_done(st['beat'], dur, current_beat)
            stem_color = QColor("#888888") if is_done else QColor("#111111")
            painter.setPen(QPen(stem_color, stem_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawLine(int(stem_x), int(notehead_y), int(stem_x), int(tip_y))

            if id(st) not in beamed_stems_set:
                if dur < 1.0:
                    flag_glyph = self.GLYPH_FLAG_8TH_UP if stem_up else self.GLYPH_FLAG_8TH_DOWN
                    if dur <= 0.25:
                        flag_glyph = self.GLYPH_FLAG_16TH_UP if stem_up else self.GLYPH_FLAG_16TH_DOWN

                    flag_font = QFont(self._get_smufl_family())
                    flag_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
                    flag_font.setPixelSize(int(s * 4.0))
                    painter.setFont(flag_font)
                    painter.setPen(QPen(stem_color))
                    painter.drawText(int(stem_x), int(tip_y), flag_glyph)

        # ── PASS 4: draw beam polygons ────────────────────────────────────────
        for group in beam_groups:
            if len(group) < 2:
                continue

            stem_up  = group[0]['stem_up']
            x_first  = group[0]['stem_x']
            y_first  = group[0]['tip_y']
            x_last   = group[-1]['stem_x']
            y_last   = group[-1]['tip_y']

            group_done = all(_stem_done(st['beat'], st['dur'], current_beat) for st in group)
            beam_color = QColor("#888888") if group_done else QColor("#111111")

            beam_poly = QPolygonF()
            if stem_up:
                beam_poly.append(QPointF(x_first, y_first - half))
                beam_poly.append(QPointF(x_last,  y_last  - half))
                beam_poly.append(QPointF(x_last,  y_last  + half + beam_thick))
                beam_poly.append(QPointF(x_first, y_first + half + beam_thick))
            else:
                beam_poly.append(QPointF(x_first, y_first - half - beam_thick))
                beam_poly.append(QPointF(x_last,  y_last  - half - beam_thick))
                beam_poly.append(QPointF(x_last,  y_last  + half))
                beam_poly.append(QPointF(x_first, y_first + half))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(beam_color))
            painter.drawPolygon(beam_poly)

            has_16th = any(st['dur'] <= 0.25 for st in group)
            if has_16th:
                sec_poly = QPolygonF()
                sec_off  = (beam_thick + beam_gap) if stem_up else -(beam_thick + beam_gap)
                if stem_up:
                    sec_poly.append(QPointF(x_first, y_first - half + sec_off))
                    sec_poly.append(QPointF(x_last,  y_last  - half + sec_off))
                    sec_poly.append(QPointF(x_last,  y_last  + half + beam_thick + sec_off))
                    sec_poly.append(QPointF(x_first, y_first + half + beam_thick + sec_off))
                else:
                    sec_poly.append(QPointF(x_first, y_first - half - beam_thick + sec_off))
                    sec_poly.append(QPointF(x_last,  y_last  - half - beam_thick + sec_off))
                    sec_poly.append(QPointF(x_last,  y_last  + half + sec_off))
                    sec_poly.append(QPointF(x_first, y_first + half + sec_off))
                painter.drawPolygon(sec_poly)

    def _render_ledgers(self, painter: QPainter, clusters: dict, s: float):
        """
        Consolidates and draws ledger lines for temporal note clusters, preventing double-drawing.
        
        Args:
            painter (QPainter): The PySide6 drawing context.
            clusters (dict): Layout elements grouped by temporal location and staff.
            s (float): Fundamental staff space unit.
        """
        ledger_weight = max(1.0, s * 0.16)
        # A softer ledger in enhanced mode: the line runs behind a wide coloured
        # capsule and only its ends show, so near-black reads as a stray nub
        # rather than a staff-line extension.
        ledger_color = QColor("#111111") if self._notation_style == "traditional" else QColor("#6E6E6E")
        painter.setPen(QPen(ledger_color, ledger_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        
        # Step 1: Isolate temporal cluster requirements
        for key, cluster in clusters.items():
            start_beat, is_treble = key
            ref_y = cluster[0]['ref_y']
            
            # Step 2: Establish the opposite-staff clipping frustum
            # Dynamically compute step positions of the opposite staff's 5 lines
            other_ref = 50 if is_treble else 71  # center pitch of opposite staff
            this_ref = 71 if is_treble else 50    # center pitch of this staff
            delta = self._get_diatonic_abs(other_ref) - self._get_diatonic_abs(this_ref)
            forbidden = {delta + (i * 2) for i in range(-2, 3)}
            ledger_steps = set()
            
            # Step 3: Accumulate unique ledger levels mandated by the chord
            for l in cluster:
                steps = l['steps_from_ref']
                if steps >= 6:
                    for step in range(6, steps + 1, 2): ledger_steps.add(step)
                elif steps <= -6:
                    for step in range(-6, steps - 1, -2): ledger_steps.add(step)
                    
            if not ledger_steps:
                continue
                
            # Step 4: Reject geometry colliding with the opposite staff
            valid_steps = [step for step in ledger_steps if step not in forbidden]
            
            # Step 5: Define single ledger bar width encompassing maximum horizontal cluster shift
            base_x = cluster[0]['x']
            max_offset = max(l['notehead_offset_x'] for l in cluster)
            ledger_center_x = base_x + (max_offset / 2.0) + s * 0.6
            ledger_w = s * 1.8 + max_offset

            # Enhanced capsules can be far wider than a SMuFL notehead, so the
            # ledger has to span the block or a long low note ends up sitting on
            # a 22px stub. Traditional keeps the notehead-sized ledger.
            caps = [l for l in cluster if l.get('cap_w')]
            if self._notation_style != "traditional" and caps:
                left = min(l['x'] + l['notehead_offset_x'] for l in caps) - s * 0.5
                right = max(l['x'] + l['notehead_offset_x'] + l['cap_w'] for l in caps) + s * 0.5
                if right - left > ledger_w:
                    ledger_center_x = (left + right) / 2.0
                    ledger_w = right - left

            # Step 6: Render unified ledgers
            for step in valid_steps:
                ly = ref_y - (step * s / 2.0)
                painter.drawLine(QPointF(ledger_center_x - ledger_w / 2, ly),
                                 QPointF(ledger_center_x + ledger_w / 2, ly))

    def _blend_to_black(self, base_color: QColor, dist: float, threshold: float = 2.0) -> QColor:
        """
        Interpolates between the base color and standard black as distance approaches 0.
        
        Args:
            base_color: The starting QColor.
            dist: Current distance from the playhead in beats.
            threshold: The temporal distance at which the fade begins.
        """
        if dist >= threshold:
            return base_color
        if dist <= 0.0:
            return QColor("#111111")
            
        blend = 1.0 - (dist / threshold)
        # #111111 is RGB(17, 17, 17)
        r = int(base_color.red() * (1 - blend) + 17 * blend)
        g = int(base_color.green() * (1 - blend) + 17 * blend)
        b = int(base_color.blue() * (1 - blend) + 17 * blend)
        
        return QColor(r, g, b)                

    def _render_scrolling_array(self, painter: QPainter, note_array: list, current_beat: float, start_x: float, ppb: float, treble_y: float, bass_y: float, s: float):
        """
        Engine pipeline for dynamic/scrolling notation layouts with bisect window culling.
        """
        window_right_beats = (self.width() - start_x) / ppb if ppb > 0 else 20.0
        min_beat = current_beat - 8.0
        max_beat = current_beat + window_right_beats + 8.0

        # The bisect index is built from _scrolling_notes, so it may only be used
        # when that is the array being drawn. Matching on length alone let
        # evaluation mode (which draws _eval_notes) borrow the wrong index and
        # land hit/miss colours on the wrong notes.
        if note_array is self._scrolling_notes and self._scrolling_beats_index:
            beats_only = self._scrolling_beats_only
            left_idx = bisect.bisect_left(beats_only, min_beat)
            right_idx = bisect.bisect_right(beats_only, max_beat)
            sliced_indices = [orig_i for b, orig_i in self._scrolling_beats_index[left_idx:right_idx]]
            sliced_indices.sort()
            sliced_notes = []
            for orig_i in sliced_indices:
                item = dict(note_array[orig_i])
                item['orig_i'] = orig_i
                sliced_notes.append(item)
        else:
            sliced_notes = []
            for orig_i, item in enumerate(note_array):
                sb = float(item.get('start_beat', item.get('startBeat', 0.0)))
                if min_beat <= sb <= max_beat:
                    item_copy = dict(item)
                    item_copy['orig_i'] = orig_i
                    sliced_notes.append(item_copy)

        layout_data = self._get_layout_for_notes(sliced_notes, current_beat, start_x, ppb, treble_y, bass_y, s)

        clusters = {}
        for layout in layout_data:
            if layout is None: continue
            note = layout['note']
            # One shared width helper for culling and drawing, so the two can
            # never disagree. Previously the cull clamped to s*3.5 while the
            # draw did not, making long notes vanish early on the left edge.
            if self._notation_style == "traditional":
                cap_w = s * 1.1
            else:
                label = None if note.get('is_rest') else self._note_label_text(note.get('pitch', 60))
                cap_w = self._capsule_width(note, ppb, s, label)
            layout['cap_w'] = cap_w

            if layout['x'] + cap_w < -100 or layout['x'] > self.width() + 100:
                continue

            start_beat = note.get('start_beat', note.get('startBeat', 0))
            is_treble = layout['ref_y'] == treble_y

            key = (start_beat, is_treble)
            if key not in clusters: clusters[key] = []
            clusters[key].append(layout)

        if self._notation_style == "traditional":
            self._render_stems(painter, clusters, s, current_beat)
            self._render_tuplet_brackets(painter, layout_data, s)

        painter.setOpacity(1.0)
        self._render_ledgers(painter, clusters, s)

        outside_labels: list = []

        for i, layout in enumerate(layout_data):
            if layout is None: continue

            note_data = layout['note']
            orig_i = note_data.get('orig_i', i)
            duration = note_data.get('duration_beats', note_data.get('durationBeats', 1))
            start_beat = note_data.get('start_beat', note_data.get('startBeat', 0))

            cap_w = layout.get('cap_w', s * 1.1)
            if layout['x'] + cap_w < -100 or layout['x'] > self.width() + 100:
                continue

            color = self._get_finger_color(note_data.get('finger', 0))
            opacity = 1.0
            is_active = start_beat <= current_beat < (start_beat + duration)
            is_miss = False
            is_done = False

            # Per-note state colouring. Onboarding drives it via displayMode
            # "evaluation"; song practice in rhythm mode drives it by supplying a
            # non-empty states array. Self-paced play supplies an empty array and
            # so keeps the original trainer colouring, unchanged.
            state = self._eval_note_states[orig_i] if orig_i < len(self._eval_note_states) else ""
            use_note_states = self._display_mode == "evaluation" or state != ""

            if use_note_states:
                if state == "":
                    state = "pending"

                if state == "hit":
                    color = QColor("#888888")
                    is_done = True
                elif state == "miss":
                    color = QColor("#F44336")
                    opacity = 0.4
                    is_miss = True
                else:
                    dist = start_beat - current_beat
                    opacity = 1.0 if dist < 4 else (0.8 if dist < 8 else 0.5)

                    if dist > 0 and self._notation_color_mode == "monochrome":
                        color = self._blend_to_black(color, dist, threshold=2.0)
            else:
                is_completed = current_beat >= (start_beat + duration)
                is_done      = is_completed

                if is_completed:
                    color = QColor("#888888")
                elif is_active:
                    if self._notation_color_mode == "monochrome":
                        color = QColor("#111111")
                else:
                    if self._notation_color_mode == "monochrome":
                        dist = start_beat - current_beat
                        color = self._blend_to_black(color, dist, threshold=2.0)

            painter.setOpacity(opacity)

            # Fail-soft: a single malformed note must never blank the frame.
            # A missing draw method here previously killed paint() on the first
            # note, leaving only staff lines and orphaned ledger lines.
            try:
                self._draw_scrolling_item(
                    painter, layout, note_data, color, duration, start_beat, current_beat,
                    cap_w, s, ppb, treble_y, bass_y, is_active, is_miss, is_done, outside_labels,
                )
            except Exception:
                self._log_paint_error("scrolling item")

        painter.setOpacity(1.0)

    def _log_paint_error(self, where: str):
        """Rate-limited paint error logging so a per-frame fault cannot flood the log."""
        self._paint_error_count += 1
        now = time.monotonic()
        if now - self._last_paint_error_log > 5.0:
            self._last_paint_error_log = now
            log.exception("NotationView paint failure in %s (%d total)", where, self._paint_error_count)

    def _draw_scrolling_item(self, painter: QPainter, layout: dict, note_data: dict, color: QColor,
                             duration: float, start_beat: float, current_beat: float, cap_w: float,
                             s: float, ppb: float, treble_y: float, bass_y: float,
                             is_active: bool, is_miss: bool, is_done: bool, outside_labels: list):
        """Draws one item of the scrolling array in the active notation style."""
        if self._notation_style == "traditional":
            if note_data.get("is_barline"):
                painter.setPen(QPen(QColor("#888888"), max(1.0, s * 0.1), Qt.PenStyle.SolidLine))
                painter.drawLine(int(layout['x']), int(treble_y - s*2), int(layout['x']), int(bass_y + s*2))
            elif note_data.get("is_time_sig"):
                if start_beat > 0.0:
                    self._draw_time_signature(painter, layout['x'], note_data.get("numerator", 4), note_data.get("denominator", 4), treble_y, bass_y, s, color)
            elif note_data.get("is_dynamic"):
                d_mark = note_data.get("mark", "p")
                d_glyph = self.GLYPH_DYNAMICS.get(d_mark)
                d_color = QColor("#888888") if current_beat >= start_beat else color
                painter.setPen(QPen(d_color))
                if d_glyph:
                    smufl_font = QFont(self._get_smufl_family())
                    smufl_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
                    smufl_font.setPixelSize(int(s * 3.0))
                    painter.setFont(smufl_font)
                    painter.drawText(int(layout['x']), int(layout['y']), d_glyph)
                else:
                    d_font = QFont("Inter", int(s * 1.2), QFont.Weight.Bold, italic=True)
                    painter.setFont(d_font)
                    painter.drawText(int(layout['x']), int(layout['y']), d_mark)
            elif note_data.get("is_rest"):
                # The dot count from _duration_to_glyph was previously computed
                # and discarded, so dotted rests never rendered their dot.
                _base_g, _flag_g, dots = self._duration_to_glyph(duration, tuplet=note_data.get("tuplet"))
                if duration >= 4.0: r_glyph = self.GLYPH_REST_WHOLE
                elif duration >= 2.0: r_glyph = self.GLYPH_REST_HALF
                elif duration >= 1.0: r_glyph = self.GLYPH_REST_QUARTER
                elif duration >= 0.5: r_glyph = self.GLYPH_REST_8TH
                else: r_glyph = self.GLYPH_REST_16TH

                smufl_font = QFont(self._get_smufl_family())
                smufl_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
                smufl_font.setPixelSize(int(s * 4.0))
                painter.setFont(smufl_font)
                painter.setPen(QPen(color))
                painter.drawText(int(layout['x']), int(layout['y']), r_glyph)

                if dots > 0:
                    painter.setBrush(QBrush(color))
                    r = s * 0.18
                    painter.drawEllipse(QPointF(layout['x'] + s * 1.5, layout['y'] - s * 0.5), r, r)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
            else:
                self._draw_traditional_note(
                    painter, layout['x'], layout['y'], note_data.get('pitch', 60), s, color, duration,
                    layout['notehead_offset_x'], layout['accidental_offset_x'], note_data.get('tie'), ppb,
                    spelling=note_data.get('spelling'), tuplet=note_data.get('tuplet'),
                    steps_from_ref=layout.get('steps_from_ref', 0)
                )
        else:
            if note_data.get("is_time_sig"):
                if start_beat > 0.0:
                    self._draw_time_signature(painter, layout['x'], note_data.get("numerator", 4), note_data.get("denominator", 4), treble_y, bass_y, s, color)
            elif note_data.get("is_dynamic"):
                d_mark = note_data.get("mark", "p")
                d_color = QColor("#888888") if current_beat >= start_beat else color
                painter.setPen(QPen(d_color))
                d_font = QFont("Inter", int(s * 1.2), QFont.Weight.Bold, italic=True)
                painter.setFont(d_font)
                painter.drawText(int(layout['x']), int(layout['y']), d_mark)
            elif not note_data.get("is_barline"):
                x = layout['x'] + layout['notehead_offset_x']
                if note_data.get("is_rest"):
                    self._draw_enhanced_rest(painter, x, layout['y'], cap_w, s)
                else:
                    self._draw_enhanced_note(
                        painter, x, layout['y'], self._coerce_pitch(note_data.get('pitch')), cap_w, s, color,
                        is_active=is_active, is_miss=is_miss, is_done=is_done,
                        outside_labels=outside_labels,
                        above=layout['ref_y'] == treble_y,
                    )

    def _draw_enhanced_note(self, painter: QPainter, x: float, y: float, pitch: int, width: float,
                            spacing: float, color: QColor, is_active: bool = False,
                            is_miss: bool = False, is_done: bool = False,
                            outside_labels: list | None = None, above: bool = True):
        """
        Draws a pedagogical duration capsule: position encodes pitch, width
        encodes duration, fill encodes fingering, and the letter names the note.

        Geometry is float throughout so the rounded ends stay smooth under the
        antialiasing enabled in paint(); the previous implementation cast to int
        and produced visibly jagged caps.
        """
        h = spacing * CAPSULE_HEIGHT_RATIO
        rect = QRectF(x, y - h / 2.0, width, h)
        radius = min(h / 2.0, width / 2.0)

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        # Fill: a subtle vertical gradient reads as a physical block without
        # looking glossy. Completed notes stay flat so they recede.
        if is_done:
            painter.setBrush(QBrush(color))
        else:
            grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            grad.setColorAt(0.0, color.lighter(112))
            grad.setColorAt(1.0, color.darker(108))
            painter.setBrush(QBrush(grad))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

        # Onset accent: a brighter band on the leading edge marks the moment to
        # strike, clipped to the capsule so it follows the rounded cap.
        if not is_done and width > spacing * 0.6:
            painter.save()
            # IntersectClip, not the default ReplaceClip: replacing would discard
            # the content clip paint() installed and let the accent draw over the
            # clef and key signature when a note scrolls off the left edge.
            painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
            accent_w = max(2.0, min(width * 0.15, spacing * 0.7))
            painter.setBrush(QBrush(color.lighter(126)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(rect.left(), rect.top(), accent_w, rect.height()))
            painter.restore()

        # Rim: separates neighbouring capsules and defines the edge against
        # staff lines showing through.
        rim_color = QColor("#F44336") if is_miss else color.darker(135)
        rim_weight = 1.5 if is_miss else 1.0
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(rim_color, rim_weight))
        painter.drawPath(path)

        # Active ring: the note under the playhead reads instantly.
        if is_active:
            ring = QColor(color.lighter(140))
            ring.setAlpha(128)
            inset = QRectF(rect.adjusted(-2.0, -2.0, 2.0, 2.0))
            painter.setPen(QPen(ring, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(inset, radius + 2.0, radius + 2.0)

        # Label. Drawn at full opacity even on missed notes, whose capsule is
        # deliberately faded — the letter must never fade with it.
        text = self._note_label_text(pitch)
        plan = self._plan_note_label(text, width, h, spacing)
        prev_opacity = painter.opacity()
        painter.setOpacity(1.0)

        if plan['inside']:
            fill_for_contrast = color if not is_miss else QColor("#F44336")
            self._draw_label_centered(
                painter, plan['text'], plan['px'],
                rect.center().x(), rect.center().y(),
                label_color_for(fill_for_contrast),
            )
        else:
            fm = self._label_metrics(plan['px'])
            tight = fm.tightBoundingRect(plan['text'])
            gap = h / 2.0 + tight.height() / 2.0 + 2.0
            cy = y - gap if above else y + gap
            if outside_labels is not None:
                cy = self._place_outside_label(
                    outside_labels, rect.left() + tight.width() / 2.0, cy,
                    tight.width(), tight.height(), above,
                )
            self._draw_outside_label(
                painter, plan['text'], plan['px'],
                rect.left() + tight.width() / 2.0, cy,
                QColor(DARK_LABEL) if is_done else color.darker(125),
            )

        painter.setOpacity(prev_opacity)

    def _draw_enhanced_rest(self, painter: QPainter, x: float, y: float, width: float, spacing: float):
        """
        Draws a rest as a low translucent bar on the staff centre line.

        Deliberately subordinate to notes: the previous dashed capsule with
        "REST"/"Z" text read as noise at ~11px and competed with the notes for
        attention.
        """
        h = spacing * CAPSULE_HEIGHT_RATIO
        bar_h = max(2.5, h * 0.38)
        rect = QRectF(x, y - bar_h / 2.0, width, bar_h)
        radius = min(bar_h / 2.0, width / 2.0)

        # Visible enough to read as a deliberate silence, quiet enough that it
        # never competes with the notes around it.
        painter.setBrush(QBrush(QColor(0, 0, 0, 46)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, radius, radius)

    def _draw_traditional_note(self, painter: QPainter, x: float, y: float, pitch: int, spacing: float, color: QColor, text_duration: float = 1.0, notehead_offset_x: float = 0.0, accidental_offset_x: float = 0.0, tie_state: str | None = None, ppb: float = 50.0, spelling: tuple | None = None, tuplet: dict | None = None, steps_from_ref: int = 0):
        glyph, _flag_type, dots = self._duration_to_glyph(text_duration, tuplet=tuplet)

        smufl_font = QFont(self._get_smufl_family())
        smufl_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        smufl_font.setPixelSize(int(spacing * 4.0))

        painter.setFont(smufl_font)
        painter.setPen(QPen(color))

        notehead_x = x + notehead_offset_x + spacing * 0.6
        painter.drawText(int(notehead_x), int(y), glyph)

        if dots > 0:
            dot_x = notehead_x + spacing * 1.5
            dot_y = y
            if steps_from_ref % 2 == 0:
                dot_y = y - spacing * 0.5
            painter.setPen(QPen(color))
            painter.setBrush(QBrush(color))
            r = spacing * 0.18
            painter.drawEllipse(QPointF(dot_x, dot_y), r, r)

        is_acc, acc_type = self._get_accidental_from_spelling(pitch, spelling)
        if is_acc:
            acc_glyph = self.GLYPH_SHARP if acc_type == "sharp" else (self.GLYPH_FLAT if acc_type == "flat" else self.GLYPH_NATURAL)
            painter.setFont(smufl_font)
            painter.setPen(QPen(QColor("#111111")))
            acc_x = notehead_x + accidental_offset_x - spacing * 1.5
            painter.drawText(int(acc_x), int(y), acc_glyph)

        if tie_state in ["start", "continue"]:
            tie_dir = 1.0 if pitch < 60 else -1.0
            tie_x = notehead_x + spacing * 0.5
            tie_y = y + (tie_dir * spacing * 0.8)
            tie_w = (text_duration * ppb) - (spacing * 1.5)
            if tie_w > 0:
                path = QPainterPath()
                path.moveTo(tie_x, tie_y)
                path.quadTo(tie_x + tie_w/2, tie_y + (tie_dir * spacing * 0.8), tie_x + tie_w, tie_y)
                painter.setPen(QPen(color, max(1.0, spacing * 0.15), Qt.PenStyle.SolidLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            
        # Render pipeline complete

    def _render_static_targets(self, painter: QPainter, note_start_x: float, treble_cy: float, bass_cy: float, s: float):
        """
        Engine pipeline for stationary evaluation targets, pushing virtual 
        simulations into the cluster algorithms.

        Args:
            painter (QPainter): The PySide6 drawing context.
            note_start_x (float): Target render column.
            treble_cy (float): Center Y coordinate of treble staff.
            bass_cy (float): Center Y coordinate of bass staff.
            s (float): Fundamental staff space unit.
        """
        # Step 1: Normalize incoming raw pitches
        notes_to_draw = []
        for i, item in enumerate(self._target_pitches):
            if isinstance(item, int):
                notes_to_draw.append({'pitch': item, 'finger': 0, 'is_current': True})
            elif isinstance(item, dict):
                notes_to_draw.append(item)

        is_pentascale = self._notation_style.lower() == "pentascale"
        if not is_pentascale:
            notes_to_draw.sort(key=lambda n: n['pitch'])

        # Step 2: Execute spatial and collision simulation mapping
        layout_data = []
        accidental_positions = []
        notehead_offsets = {}
        
        for i, note_data in enumerate(notes_to_draw):
            pitch = note_data['pitch']
            is_treble = pitch >= 60
            ref_pitch = 71 if is_treble else 50
            ref_y = treble_cy if is_treble else bass_cy

            # Use the spelled helpers for parity with the scrolling path, so a
            # target chord places and spells enharmonics (F♭, E♯) correctly.
            spelling = note_data.get('spelling')
            steps_from_ref = self._get_diatonic_abs_spelled(pitch, spelling) - self._get_diatonic_abs(ref_pitch)
            y = ref_y - (steps_from_ref * (s / 2))
            
            notehead_offset_x = 0.0
            accidental_offset_x = 0.0

            if is_pentascale:
                x = note_start_x + (i * s * 3.0)
            else:
                if i > 0:
                    prev_diatonic = self._get_diatonic_abs(notes_to_draw[i-1]['pitch'])
                    if abs(self._get_diatonic_abs(pitch) - prev_diatonic) < 2:
                        if notehead_offsets.get(i - 1, 0.0) == 0.0:
                            notehead_offset_x = s * 1.15
                x = note_start_x
            notehead_offsets[i] = notehead_offset_x

            # Resolve Accidental Constraints
            is_acc, _ = self._get_accidental_from_spelling(pitch, spelling)
            if is_acc and not is_pentascale:
                column = 0
                while True:
                    collision = False
                    for prev_y, prev_col in accidental_positions:
                        if prev_col == column and abs(y - prev_y) < (s * 2.5):
                            collision = True
                            break
                    if not collision:
                        break
                    column += 1
                accidental_offset_x -= (column * s * 1.2)
                accidental_positions.append((y, column))

            # Static targets have no duration, so the capsule is a fixed width —
            # but still never narrower than its own label needs.
            base_cap_w = s * 3.0 if is_pentascale else (s * 2.5)
            label = self._note_label_text(pitch)
            cap_w = max(base_cap_w, self._text_advance(label, MIN_LABEL_PX) + 2 * self._label_pad_x(s))

            layout_data.append({
                'note': note_data,
                'x': x,
                'y': y,
                'notehead_offset_x': notehead_offset_x,
                'accidental_offset_x': accidental_offset_x,
                'steps_from_ref': steps_from_ref,
                'ref_y': ref_y,
                'cap_w': cap_w,
                'opacity': 1.0 if note_data.get('is_current', True) else 0.4,
                'color': self._get_finger_color(note_data.get('finger', 0))
            })

        # Step 3: Bundle to temporal clusters based on pentascale state
        clusters = {}
        for i, layout in enumerate(layout_data):
            group_key = i if is_pentascale else (0, layout['ref_y'] == treble_cy)
            if group_key not in clusters: clusters[group_key] = []
            clusters[group_key].append(layout)
            
        # Step 4: Render Background Stems
        if self._notation_style == "traditional" and not is_pentascale:
            self._render_stems(painter, clusters, s)
            
        # Background ledgers apply to all styles and belong behind notes
        painter.setOpacity(1.0)
        self._render_ledgers(painter, clusters, s)
            
        # Step 5: Render Foreground Nodes
        outside_labels: list = []
        for layout in layout_data:
            painter.setOpacity(layout['opacity'])
            try:
                if self._notation_style == "traditional":
                    self._draw_traditional_note(
                        painter, layout['x'], layout['y'], layout['note']['pitch'], s, layout['color'],
                        1.0, layout['notehead_offset_x'], layout['accidental_offset_x'],
                        spelling=layout['note'].get('spelling'),
                        steps_from_ref=layout.get('steps_from_ref', 0),
                    )
                else:
                    self._draw_enhanced_note(
                        painter, layout['x'] + layout['notehead_offset_x'], layout['y'],
                        layout['note']['pitch'], layout['cap_w'], s, layout['color'],
                        is_active=bool(layout['note'].get('is_current', True)),
                        outside_labels=outside_labels,
                        above=layout['ref_y'] == treble_cy,
                    )
            except Exception:
                self._log_paint_error("static target")

        painter.setOpacity(1.0)
        # Render pipeline complete

    def _draw_staff_lines(self, painter: QPainter, width: float, center_y: float, spacing: float):
        """Renders the core 5 horizontal paths for the target staff block."""
        weight = max(1.0, spacing * 0.10)
        painter.setPen(QPen(QColor("#222222"), weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for i in range(-2, 3):
            y = center_y + (i * spacing)
            painter.drawLine(0, int(y), int(width), int(y))

    def _draw_key_signature(self, painter: QPainter, start_x: float, treble_cy: float, bass_cy: float, s: float):
        if self._song_key_sharps == 0 or self._notation_style != "traditional":
            return
            
        smufl_font = QFont(self._get_smufl_family())
        smufl_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        smufl_font.setPixelSize(int(s * 4.0))  
        painter.setFont(smufl_font)
        painter.setPen(QPen(QColor("#222222")))
        
        treble_sharps = [77, 72, 79, 74, 69, 76, 71]
        treble_flats = [71, 76, 69, 74, 67, 72, 65]
        bass_sharps = [53, 48, 55, 50, 45, 52, 47]
        bass_flats = [47, 52, 45, 50, 43, 48, 41]
        
        count = abs(self._song_key_sharps)
        is_sharp = self._song_key_sharps > 0
        glyph = self.GLYPH_SHARP if is_sharp else self.GLYPH_FLAT
        
        t_pitches = treble_sharps if is_sharp else treble_flats
        b_pitches = bass_sharps if is_sharp else bass_flats
        
        for i in range(count):
            if i >= len(t_pitches): break
            x_pos = start_x + (i * s * 0.8)
            
            steps_t = self._get_diatonic_abs(t_pitches[i]) - self._get_diatonic_abs(71)
            ty = treble_cy - (steps_t * (s / 2))
            painter.drawText(int(x_pos), int(ty), glyph)
            
            steps_b = self._get_diatonic_abs(b_pitches[i]) - self._get_diatonic_abs(50)
            by = bass_cy - (steps_b * (s / 2))
            painter.drawText(int(x_pos), int(by), glyph)


