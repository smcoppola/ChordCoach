# =============================================================================
# File: notation_view.py
# Description: Advanced Notation Rendering Engine for ChordCoach Companion.
#              Handles grand staff music engraving with dual styles (Traditional
#              SMuFL/Bravura and Enhanced pedagogical style).
#              Implements strict SMuFL optical layout passes, including grid-based 
#              accidental staggering, unified chord stems, and deduplicated 
#              ledger line rendering.
# =============================================================================

from PySide6.QtCore import Qt, Property, Signal, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QBrush, QPolygonF, QPainterPath
from PySide6.QtQuick import QQuickPaintedItem

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

    def __init__(self, parent=None):
        """
        Initializes the rendering engine, signaling properties, and SMuFL codepoints.
        """
        super().__init__(parent)
        self._target_pitches = [] 
        self._notation_style = "enhanced" 
        self._notation_color_mode = "pedagogical" 
        self._display_mode = "trainer" 
        self._is_scrolling_mode = False
        self._song_key_sharps = 0
        
        self._scroll_beat = 0.0
        self._eval_beat = 0.0
        
        self._eval_notes = []
        self._scrolling_notes = []
        self._eval_note_states = []
        
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
        
        # Map 12 MIDI notes to 0-6 diatonic steps
        self._diatonic_map = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
        self._pitch_names = [
            "C", "C♯", "D", "E♭", 
            "E", "F", "F♯", "G", "A♭", 
            "A", "B♭", "B"
        ]
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
            self._scroll_beat = value
            self.scrollBeatChanged.emit()
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

    def _get_finger_color(self, finger: int) -> QColor:
        if self._notation_color_mode == "monochrome":
            # Darkened to #555555 so future notes maintain structural visibility
            # when combined with the distance opacity fade.
            return QColor("#555555")
            
        color_hex = self._pedagogical_colors.get(str(finger), "#111111")
        return QColor(color_hex)

    def _get_layout_for_notes(self, note_array: list, current_beat: float, start_x: float, ppb: float, treble_y: float, bass_y: float, s: float) -> list:
        """
        Computes spatial layout, interval staggering, and accidental collision grids for a sequence of notes.

        Args:
            note_array (list): Dictionaries defining pitch, beat, and duration.
            current_beat (float): Current playhead position.
            start_x (float): Origin X coordinate of playhead.
            ppb (float): Pixels per beat horizontal scale.
            treble_y (float): Center Y coordinate of treble staff.
            bass_y (float): Center Y coordinate of bass staff.
            s (float): Fundamental staff space unit.

        Returns:
            list: Analyzed layout dictionary mapping for each index in note_array.
        """
        # Step 1: Temporal quantization into simultaneity groups
        groups = {}
        for i, note in enumerate(note_array):
            start_beat = note.get('start_beat', note.get('startBeat', 0))
            if start_beat not in groups:
                groups[start_beat] = []
            groups[start_beat].append((i, note))

        layout_results: list[dict | None] = [None] * len(note_array)

        # Step 2: Resolve spatial metrics per temporal cluster
        for start_beat, group in groups.items():
            # Step 3: Sort geometrically bottom-up for consistent collision detection
            group.sort(key=lambda item: item[1].get('pitch', 60))

            accidental_positions = [] # List of tuples: (y_coordinate, column_index)
            base_x = start_x + ((start_beat - current_beat) * ppb)
            notehead_offsets = {} 

            for index_in_group, (original_index, note) in enumerate(group):
                base_x = start_x + ((start_beat - current_beat) * ppb)

                if note.get("is_barline") or note.get("is_rest"):
                    hand = note.get('hand', 'R')
                    is_treble = (hand in ["R", "right"])
                    ref_y = treble_y if is_treble else bass_y
                    y = ref_y
                    if note.get("is_rest") and note.get("duration_beats", 1) >= 4.0:
                        y = ref_y - (s / 2.0)

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

                pitch = note.get('pitch', 60)
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
                    prev_pitch = group[index_in_group - 1][1].get('pitch', 60)
                    if abs(self._get_diatonic_abs(pitch) - self._get_diatonic_abs(prev_pitch)) < 2:
                        if notehead_offsets.get(index_in_group - 1, 0.0) == 0.0:
                            notehead_offset_x = s * 1.15
                notehead_offsets[index_in_group] = notehead_offset_x

                # Step 6: Grid-based Accidental collision resolution
                is_acc, acc_type = self._get_accidental_from_spelling(pitch, note.get('spelling'))
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

        # Step 1: Initialize optical constants matching standard screen proportions
        s = height * 0.035
        treble_cy = height * 0.35
        bass_cy = height * 0.65
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

        if self._display_mode == "evaluation":
            self._render_scrolling_array(
                painter, self._eval_notes, self._eval_beat, 
                note_start_x, ppb, treble_cy, bass_cy, s
            )
        elif self._is_scrolling_mode:
            self._draw_key_signature(painter, note_start_x - (s*5), treble_cy, bass_cy, s)
            self._render_scrolling_array(
                painter, self._scrolling_notes, self._scroll_beat, 
                note_start_x, ppb, treble_cy, bass_cy, s
            )
        else:
            self._draw_key_signature(painter, note_start_x - (s*5), treble_cy, bass_cy, s)
            self._render_static_targets(
                painter, note_start_x, treble_cy, bass_cy, s
            )
        
        painter.restore()

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
                'beam':        beam_state,
                'tip_y':       None,    # filled in pass 2
            })

        # ── PASS 2: compute beam lines; assign tip_y to beamed stems ─────────
        beam_groups = []
        for is_treble in (True, False):
            staff = [r for r in all_stems if r['is_treble'] == is_treble]

            i = 0
            while i < len(staff):
                if staff[i]['beam'] != 'start':
                    i += 1
                    continue

                grp = [staff[i]]
                j   = i + 1
                while j < len(staff) and staff[j]['beam'] in ('continue', 'stop'):
                    grp.append(staff[j])
                    if staff[j]['beam'] == 'stop':
                        j += 1
                        break
                    j += 1

                if len(grp) >= 2:
                    stem_up = grp[0]['stem_up']
                    bx0 = grp[0]['stem_x']
                    bx1 = grp[-1]['stem_x']

                    # Anchor: beam passes through the most-extreme natural stem tip
                    tips  = [r['unclamped'] for r in grp]
                    ext_y = min(tips) if stem_up else max(tips)
                    ext_x = grp[tips.index(ext_y)]['stem_x']

                    # Slope from first→last unclamped tips, clamped to ±0.5 staff spaces
                    raw_slope = grp[-1]['unclamped'] - grp[0]['unclamped']
                    clamped   = max(-s * 0.5, min(s * 0.5, raw_slope))

                    if bx1 != bx0:
                        slope_pp = clamped / (bx1 - bx0)      # pixels per pixel
                        by0 = ext_y - slope_pp * (ext_x - bx0)
                        by1 = ext_y + slope_pp * (bx1 - ext_x)
                    else:
                        by0 = by1 = ext_y

                    # Pin each beamed stem's tip to the interpolated beam line
                    for r in grp:
                        t = (r['stem_x'] - bx0) / (bx1 - bx0) if bx1 != bx0 else 0.0
                        r['tip_y'] = by0 + t * (by1 - by0)

                    beam_groups.append({
                        'grp': grp, 'x0': bx0, 'y0': by0,
                        'x1': bx1, 'y1': by1, 'up': stem_up,
                    })

                i = j

        # Unbeamed stems: clamp natural tip at middle line (standard rule)
        for r in all_stems:
            if r['tip_y'] is None:
                r['tip_y'] = min(r['unclamped'], r['ref_y']) if r['stem_up'] \
                             else max(r['unclamped'], r['ref_y'])

        def _stem_done(beat: float, dur: float) -> bool:
            return current_beat >= beat + dur

        # ── PASS 3: draw stems and flags ──────────────────────────────────────
        for r in all_stems:
            stem_color = QColor("#888888") if _stem_done(r['beat'], r['dur']) else QColor("#111111")
            painter.setPen(QPen(stem_color, stem_weight,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawLine(int(r['stem_x']), int(r['notehead_y']),
                             int(r['stem_x']), int(r['tip_y']))

            if r['dur'] < 1.0 and r['beam'] is None:
                if r['stem_up']:
                    fg = self.GLYPH_FLAG_16TH_UP if r['dur'] <= 0.25 else self.GLYPH_FLAG_8TH_UP
                else:
                    fg = self.GLYPH_FLAG_16TH_DOWN if r['dur'] <= 0.25 else self.GLYPH_FLAG_8TH_DOWN
                sf = QFont(self._get_smufl_family())
                sf.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
                sf.setPixelSize(int(s * 4.0))
                painter.setFont(sf)
                painter.drawText(int(r['stem_x']), int(r['tip_y']), fg)

        # ── PASS 4: draw beam polygons ────────────────────────────────────────
        painter.setPen(Qt.PenStyle.NoPen)

        for info in beam_groups:
            grp, bx0, by0, bx1, by1 = \
                info['grp'], info['x0'], info['y0'], info['x1'], info['y1']
            direction = 1.0 if info['up'] else -1.0

            beam_color = QColor("#888888") if _stem_done(grp[-1]['beat'], grp[-1]['dur']) else QColor("#111111")
            painter.setBrush(QBrush(beam_color))

            def _by(x, lvl, _y0=by0, _y1=by1, _x0=bx0, _x1=bx1, _d=direction):
                base = _y0 + (_y1 - _y0) * (x - _x0) / (_x1 - _x0) \
                       if _x1 != _x0 else _y0
                return base + lvl * (beam_thick + beam_gap) * _d

            painter.drawPolygon(QPolygonF([
                QPointF(bx0, _by(bx0, 0) - half), QPointF(bx1, _by(bx1, 0) - half),
                QPointF(bx1, _by(bx1, 0) + half), QPointF(bx0, _by(bx0, 0) + half),
            ]))

            k = 0
            while k < len(grp) - 1:
                if grp[k]['dur'] <= 0.25 and grp[k + 1]['dur'] <= 0.25:
                    run_start = k
                    while k + 1 < len(grp) and grp[k + 1]['dur'] <= 0.25:
                        k += 1
                    sx0, sx1 = grp[run_start]['stem_x'], grp[k]['stem_x']
                    painter.drawPolygon(QPolygonF([
                        QPointF(sx0, _by(sx0, 1) - half), QPointF(sx1, _by(sx1, 1) - half),
                        QPointF(sx1, _by(sx1, 1) + half), QPointF(sx0, _by(sx0, 1) + half),
                    ]))
                k += 1

        painter.setOpacity(1.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _render_ledgers(self, painter: QPainter, clusters: dict, s: float):
        """
        Consolidates and draws ledger lines for temporal note clusters, preventing double-drawing.
        
        Args:
            painter (QPainter): The PySide6 drawing context.
            clusters (dict): Layout elements grouped by temporal location and staff.
            s (float): Fundamental staff space unit.
        """
        ledger_weight = max(1.0, s * 0.16)
        painter.setPen(QPen(QColor("#111111"), ledger_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        
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
            
            # Step 6: Render unified ledgers
            for step in valid_steps:
                ly = ref_y - (step * s / 2.0)
                painter.drawLine(int(ledger_center_x - ledger_w / 2), int(ly), int(ledger_center_x + ledger_w / 2), int(ly))

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
        Engine pipeline for dynamic/scrolling notation layouts.

        Args:
            painter (QPainter): The PySide6 drawing context.
            note_array (list): Sequential notes to render.
            current_beat (float): Transport timeline position.
            start_x (float): Temporal target line position.
            ppb (float): Timeline zoom scale.
            treble_y (float): Center Y coordinate of treble staff.
            bass_y (float): Center Y coordinate of bass staff.
            s (float): Fundamental staff space unit.
        """
        # Step 1: Pre-compute collision-free coordinates
        layout_data = self._get_layout_for_notes(note_array, current_beat, start_x, ppb, treble_y, bass_y, s)

        # Step 2: Group layouts by temporal and spatial anchor for unified stemming
        clusters = {}
        for layout in layout_data:
            if layout is None: continue
            duration = layout['note'].get('duration_beats', layout['note'].get('durationBeats', 1))
            cap_w = min(max(duration * ppb - 4, 12), s * 3.5) if self._notation_style == "enhanced" else s * 1.1
            if layout['x'] + cap_w < -100 or layout['x'] > self.width() + 100:
                continue
                
            start_beat = layout['note'].get('start_beat', layout['note'].get('startBeat', 0))
            is_treble = layout['ref_y'] == treble_y
            
            key = (start_beat, is_treble)
            if key not in clusters: clusters[key] = []
            clusters[key].append(layout)

        # Step 3: Execute Background Render Passes
        if self._notation_style == "traditional":
            self._render_stems(painter, clusters, s, current_beat)

        # Background ledgers apply to all styles and belong behind notes
        painter.setOpacity(1.0)
        self._render_ledgers(painter, clusters, s)

        # Step 4: Execute Foreground Node/Accidental Render Pass
        for i, layout in enumerate(layout_data):
            if layout is None: continue
            
            note_data = layout['note']
            duration = note_data.get('duration_beats', note_data.get('durationBeats', 1))
            start_beat = note_data.get('start_beat', note_data.get('startBeat', 0))
            
            cap_w = max(duration * ppb - 4, 12) if self._notation_style == "enhanced" else s * 1.1
            if layout['x'] + cap_w < -100 or layout['x'] > self.width() + 100:
                continue

            color = self._get_finger_color(note_data.get('finger', 0))
            opacity = 1.0

            # Compute interactive fade/feedback states
            if self._display_mode == "evaluation":
                state = "pending"
                if i < len(self._eval_note_states):
                    state = self._eval_note_states[i]
                
                if state == "hit": 
                    color = QColor("#888888")
                elif state == "miss": 
                    color = QColor("#F44336")
                    opacity = 0.4
                else: 
                    dist = start_beat - current_beat
                    # Boosted baseline opacity for evaluation mode visibility
                    opacity = 1.0 if dist < 4 else (0.8 if dist < 8 else 0.5)
                    
                    if dist > 0 and self._notation_color_mode == "monochrome":
                        color = self._blend_to_black(color, dist, threshold=2.0)
                        
            else:
                is_completed = current_beat >= (start_beat + duration)
                is_active    = start_beat <= current_beat < (start_beat + duration)

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
            
            if self._notation_style == "traditional":
                if note_data.get("is_barline"):
                    painter.setPen(QPen(QColor("#888888"), max(1.0, s * 0.1), Qt.PenStyle.SolidLine))
                    painter.drawLine(int(layout['x']), int(treble_y - s*2), int(layout['x']), int(bass_y + s*2))
                elif note_data.get("is_rest"):
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
                else:
                    self._draw_traditional_note(painter, layout['x'], layout['y'], note_data.get('pitch', 60), s, color, duration, layout['notehead_offset_x'], layout['accidental_offset_x'], note_data.get('tie'), ppb)
            else:
                if not note_data.get("is_barline"):
                    if note_data.get("is_rest"):
                        self._draw_enhanced_rest(painter, layout['x'] + layout['notehead_offset_x'], layout['y'], cap_w, s)
                    else:
                        self._draw_enhanced_note(painter, layout['x'] + layout['notehead_offset_x'], layout['y'], note_data.get('pitch', 60), cap_w, s, color)
            
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
            
            steps_from_ref = self._get_diatonic_abs(pitch) - self._get_diatonic_abs(ref_pitch)
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
            is_acc, _ = self._requires_accidental_for_key(pitch)
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

            layout_data.append({
                'note': note_data,
                'x': x,
                'y': y,
                'notehead_offset_x': notehead_offset_x,
                'accidental_offset_x': accidental_offset_x,
                'steps_from_ref': steps_from_ref,
                'ref_y': ref_y,
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
        for layout in layout_data:
            painter.setOpacity(layout['opacity'])
            if self._notation_style == "traditional":
                self._draw_traditional_note(painter, layout['x'], layout['y'], layout['note']['pitch'], s, layout['color'], 1.0, layout['notehead_offset_x'], layout['accidental_offset_x'])
            else:
                cap_w = s * 3.0 if is_pentascale else (s * 2.5)
                self._draw_enhanced_note(painter, layout['x'] + layout['notehead_offset_x'], layout['y'], layout['note']['pitch'], cap_w, s, layout['color'])
                
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

    def _draw_traditional_note(self, painter: QPainter, x: float, y: float, pitch: int, spacing: float, color: QColor, text_duration: float = 1.0, notehead_offset_x: float = 0.0, accidental_offset_x: float = 0.0, tie_state: str | None = None, ppb: float = 50.0):
        if text_duration >= 4.0:
            glyph = self.GLYPH_NOTEHEAD_WHOLE
        elif text_duration >= 2.0:
            glyph = self.GLYPH_NOTEHEAD_HALF
        else:
            glyph = self.GLYPH_NOTEHEAD_BLACK

        smufl_font = QFont(self._get_smufl_family())
        smufl_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        smufl_font.setPixelSize(int(spacing * 4.0))
        
        painter.setFont(smufl_font)
        painter.setPen(QPen(color))
        
        notehead_x = x + notehead_offset_x + spacing * 0.6
        painter.drawText(int(notehead_x), int(y), glyph)
            
        is_acc, acc_type = self._get_accidental_from_spelling(pitch, None)  # static targets have no spelling
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


    def _draw_enhanced_note(self, painter: QPainter, x: float, y: float, pitch: int, width: float, spacing: float, color: QColor):
        """
        Draws a modern pedagogical capsule with fixed interior text metrics.
        """
        h = spacing * 0.9 
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(x, y - h/2, width, h), h/2, h/2)
        
        stem_weight = max(1.0, spacing * 0.06)
        painter.setPen(QPen(QColor("#111111"), stem_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        stem_h = spacing * 1.8
        is_treble = pitch >= 60
        stem_up = pitch < (71 if is_treble else 50)
        
        if stem_up:
            painter.drawLine(int(x), int(y - h/2), int(x), int(y - h/2 - stem_h))
        else:
            painter.drawLine(int(x), int(y + h/2), int(x), int(y + h/2 + stem_h))

        f = QFont("Inter", int(h * 0.85), QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(f)
        
        text = self._get_note_name(pitch)
        rect = QRectF(x, y - h / 2, width, h)
        
        # Draw text shadow for contrast against bright finger colors
        painter.setPen(QPen(QColor(0, 0, 0, 160)))
        painter.drawText(QRectF(rect.x() + 1.5, rect.y() + 1.5, rect.width(), rect.height()), Qt.AlignmentFlag.AlignCenter, text)
        
        painter.setPen(QPen(QColor(255, 255, 255, 250)))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_enhanced_rest(self, painter: QPainter, x: float, y: float, width: float, spacing: float):
        """
        Draws a modern pedagogical rest capsule (ghosted).
        """
        h = spacing * 0.9 
        painter.setBrush(QBrush(QColor(150, 150, 150, 60)))
        painter.setPen(QPen(QColor(150, 150, 150, 200), 1.0, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(QRectF(x, y - h/2, width, h), h/2, h/2)
        
        painter.setPen(QPen(QColor(150, 150, 150, 200)))
        f = QFont("Inter", int(h * 0.75), QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(f)
        
        text = "REST" if width > spacing * 3.0 else ("Z" if width > spacing * 1.5 else "")
        if text:
            oblique_font = QFont(f)
            oblique_font.setItalic(True)
            painter.setFont(oblique_font)
            painter.drawText(QRectF(x, y - h / 2, width, h), 
                             Qt.AlignmentFlag.AlignCenter, 
                             text)