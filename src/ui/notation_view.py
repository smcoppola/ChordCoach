# =============================================================================
# File: notation_view.py
# Description: Advanced Notation Rendering Engine for ChordCoach Companion.
#              Handles grand staff music engraving with dual styles (Traditional
#              SMuFL/Bravura and Enhanced pedagogical style).
#              Implements strict SMuFL optical layout passes, including grid-based 
#              accidental staggering, unified chord stems, and deduplicated 
#              ledger line rendering.
# =============================================================================

import os
from pathlib import Path
from PySide6.QtCore import Qt, Property, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QBrush
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
    pedagogicalColorsChanged = Signal()
    notationColorModeChanged = Signal()

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
        
        # Map 12 MIDI notes to 0-6 diatonic steps
        self._diatonic_map = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
        self._pitch_names = [
            "C", f"C{self.GLYPH_SHARP}", "D", f"E{self.GLYPH_FLAT}", 
            "E", "F", f"F{self.GLYPH_SHARP}", "G", f"A{self.GLYPH_FLAT}", 
            "A", f"B{self.GLYPH_FLAT}", "B"
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
    def targetPitches(self): return self._target_pitches

    @targetPitches.setter
    def targetPitches(self, value):
        if self._target_pitches != value:
            self._target_pitches = value
            self.targetPitchesChanged.emit()
            self.update()

    @Property(str, notify=notationStyleChanged)
    def notationStyle(self): return self._notation_style

    @notationStyle.setter
    def notationStyle(self, value):
        safe_val = str(value).lower()
        if self._notation_style != safe_val:
            self._notation_style = safe_val
            self.notationStyleChanged.emit()
            self.update()
            
    @Property(float, notify=scrollBeatChanged)
    def scrollBeat(self): return self._scroll_beat

    @scrollBeat.setter
    def scrollBeat(self, value):
        if self._scroll_beat != value:
            self._scroll_beat = value
            self.scrollBeatChanged.emit()
            self.update()

    @Property(float, notify=evalBeatChanged)
    def evalBeat(self): return self._eval_beat

    @evalBeat.setter
    def evalBeat(self, value):
        if self._eval_beat != value:
            self._eval_beat = value
            self.evalBeatChanged.emit()
            self.update()

    @Property(str, notify=displayModeChanged)
    def displayMode(self): return self._display_mode

    @displayMode.setter
    def displayMode(self, value):
        if self._display_mode != value:
            self._display_mode = value
            self.displayModeChanged.emit()
            self.update()

    @Property(bool, notify=isScrollingModeChanged)
    def isScrollingMode(self): return self._is_scrolling_mode

    @isScrollingMode.setter
    def isScrollingMode(self, value):
        if self._is_scrolling_mode != value:
            self._is_scrolling_mode = value
            self.isScrollingModeChanged.emit()
            self.update()

    @Property(list, notify=evalNotesChanged)
    def evalNotes(self): return self._eval_notes

    @evalNotes.setter
    def evalNotes(self, value):
        if self._eval_notes != value:
            self._eval_notes = value
            self.evalNotesChanged.emit()
            self.update()

    @Property(list, notify=scrollingNotesChanged)
    def scrollingNotes(self): return self._scrolling_notes

    @scrollingNotes.setter
    def scrollingNotes(self, value):
        if self._scrolling_notes != value:
            self._scrolling_notes = value
            self.scrollingNotesChanged.emit()
            self.update()

    @Property(list, notify=evalNoteStatesChanged)
    def evalNoteStates(self): return self._eval_note_states

    @evalNoteStates.setter
    def evalNoteStates(self, value):
        if self._eval_note_states != value:
            self._eval_note_states = value
            self.evalNoteStatesChanged.emit()
            self.update()

    @Property(str, notify=notationColorModeChanged)
    def notationColorMode(self): return self._notation_color_mode

    @notationColorMode.setter
    def notationColorMode(self, value):
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

    def _get_note_name(self, pitch: int) -> str:
        """Returns the formatted pitch name string."""
        return self._pitch_names[pitch % 12]

    def _is_accidental(self, pitch: int) -> bool:
        """Evaluates if the MIDI pitch requires an accidental."""
        note = pitch % 12
        return note in [1, 3, 6, 8, 10]

    def _get_accidental_type(self, pitch: int) -> str:
        """Resolves sharp vs flat orientation for the given pitch."""
        note = pitch % 12
        if note in [1, 6]: return "sharp"
        if note in [3, 8, 10]: return "flat"
        return ""

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

        layout_results = [None] * len(note_array)

        # Step 2: Resolve spatial metrics per temporal cluster
        for start_beat, group in groups.items():
            # Step 3: Sort geometrically bottom-up for consistent collision detection
            group.sort(key=lambda item: item[1].get('pitch', 60))

            accidental_positions = [] # List of tuples: (y_coordinate, column_index)
            base_x = start_x + ((start_beat - current_beat) * ppb)
            notehead_offsets = {} 

            for index_in_group, (original_index, note) in enumerate(group):
                pitch = note.get('pitch', 60)
                hand = note.get('hand', 'R')

                # Step 4: Map pitch to target staff plane
                is_treble = True if hand in ["R", "right"] else False if hand in ["L", "left"] else pitch >= 60
                ref_pitch = 71 if is_treble else 50
                ref_y = treble_y if is_treble else bass_y

                steps_from_ref = self._get_diatonic_abs(pitch) - self._get_diatonic_abs(ref_pitch)
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
                if self._is_accidental(pitch):
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
        clef_font.setPixelSize(int(s * 3.6))
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
            self._render_scrolling_array(
                painter, self._scrolling_notes, self._scroll_beat, 
                note_start_x, ppb, treble_cy, bass_cy, s
            )
        else:
            self._render_static_targets(
                painter, note_start_x, treble_cy, bass_cy, s
            )
        
        painter.restore()

    def _render_stems(self, painter: QPainter, clusters: dict, s: float):
        """
        Calculates and draws unified chord stems spanning temporal note clusters.
        
        Args:
            painter (QPainter): The PySide6 drawing context.
            clusters (dict): Layout elements grouped by temporal location and staff.
            s (float): Fundamental staff space unit.
        """
        stem_weight = max(1.0, s * 0.08)
        painter.setPen(QPen(QColor("#111111"), stem_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        
        # Step 1: Iterate unified geometric groups
        for key, cluster in clusters.items():
            start_beat, is_treble = key
            duration = cluster[0]['note'].get('duration_beats', cluster[0]['note'].get('durationBeats', 1))
            
            # Step 2: Cull stemming for whole notes
            if duration >= 4.0:
                continue 
                
            # Step 3: Determine aggregate stem direction based on extreme cluster bounds
            min_pitch = min(l['note'].get('pitch', 60) for l in cluster)
            max_pitch = max(l['note'].get('pitch', 60) for l in cluster)
            ref_mid = 71 if is_treble else 50
            stem_up = ((min_pitch + max_pitch) / 2.0) < ref_mid
            
            # Step 4: Extract physical constraints
            min_y = min(l['y'] for l in cluster)
            max_y = max(l['y'] for l in cluster)
            base_x = cluster[0]['x']
            
            # Step 5: Render vector based on phase alignment rules
            if stem_up:
                max_offset = max(l['notehead_offset_x'] for l in cluster)
                stem_x = base_x + max_offset + s * 0.6 + s * 1.12
                painter.drawLine(int(stem_x), int(max_y), int(stem_x), int(min_y - s * 3.5))
            else:
                min_offset = min(l['notehead_offset_x'] for l in cluster)
                stem_x = base_x + min_offset + s * 0.6
                painter.drawLine(int(stem_x), int(min_y), int(stem_x), int(max_y + s * 3.5))

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
            forbidden = {-12, -14, -16, -18, -20} if is_treble else {12, 14, 16, 18, 20}
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
            self._render_stems(painter, clusters, s)

        # Step 4: Execute Foreground Node/Accidental Render Pass
        for i, layout in enumerate(layout_data):
            if layout is None: continue
            
            note_data = layout['note']
            duration = note_data.get('duration_beats', note_data.get('durationBeats', 1))
            start_beat = note_data.get('start_beat', note_data.get('startBeat', 0))
            
            cap_w = min(max(duration * ppb - 4, 12), s * 3.5) if self._notation_style == "enhanced" else s * 1.1
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
                if self._notation_style == "traditional":
                    played_dist = current_beat - start_beat
                    if played_dist >= 0:
                        # Lock to black in monochrome mode so it doesn't snap back to gray
                        if self._notation_color_mode == "monochrome":
                            color = QColor("#111111")
                        else:
                            color = QColor("#888888")
                            
                        opacity = max(0.0, 1.0 - (played_dist / 1.0)) 
                    else:
                        dist = abs(played_dist)
                        # Lock future notes to 100% opacity to maintain pedagogical color saturation
                        opacity = 1.0 
                        
                        if self._notation_color_mode == "monochrome":
                            color = self._blend_to_black(color, dist, threshold=2.0)
                else:
                    is_completed = current_beat >= (start_beat + duration)
                    is_active = current_beat >= start_beat and current_beat < (start_beat + duration)
                    
                    if is_completed: 
                        color = QColor("#888888")
                        finish_dist = current_beat - (start_beat + duration)
                        opacity = max(0.0, 0.35 - (finish_dist / 0.5))
                    elif is_active:
                        if self._notation_color_mode == "monochrome":
                            color = QColor("#111111")
                    else:
                        dist = abs(start_beat - current_beat)
                        # Lock future notes to 100% opacity to maintain pedagogical color saturation
                        opacity = 1.0 
                        
                        if self._notation_color_mode == "monochrome":
                            color = self._blend_to_black(color, dist, threshold=2.0)

            painter.setOpacity(opacity)
            
            if self._notation_style == "traditional":
                self._draw_traditional_note(painter, layout['x'], layout['y'], note_data.get('pitch', 60), s, color, duration, layout['notehead_offset_x'], layout['accidental_offset_x'])
            else:
                self._draw_enhanced_note(painter, layout['x'] + layout['notehead_offset_x'], layout['y'], note_data.get('pitch', 60), cap_w, s, color)
            
        # Step 5: Render deduplicated ledgers
        painter.setOpacity(1.0)
        self._render_ledgers(painter, clusters, s)

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
            if self._is_accidental(pitch) and not is_pentascale:
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
            
        # Step 5: Render Foreground Nodes
        for layout in layout_data:
            painter.setOpacity(layout['opacity'])
            if self._notation_style == "traditional":
                self._draw_traditional_note(painter, layout['x'], layout['y'], layout['note']['pitch'], s, layout['color'], 1.0, layout['notehead_offset_x'], layout['accidental_offset_x'])
            else:
                cap_w = s * 3.0 if is_pentascale else (s * 2.5)
                self._draw_enhanced_note(painter, layout['x'] + layout['notehead_offset_x'], layout['y'], layout['note']['pitch'], cap_w, s, layout['color'])
                
        # Step 6: Render Background Ledgers
        painter.setOpacity(1.0)
        self._render_ledgers(painter, clusters, s)

    def _draw_staff_lines(self, painter: QPainter, width: float, center_y: float, spacing: float):
        """Renders the core 5 horizontal paths for the target staff block."""
        weight = max(1.0, spacing * 0.10)
        painter.setPen(QPen(QColor("#222222"), weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for i in range(-2, 3):
            y = center_y + (i * spacing)
            painter.drawLine(0, int(y), int(width), int(y))

    def _draw_traditional_note(self, painter: QPainter, x: float, y: float, pitch: int, spacing: float, color: QColor, duration: float = 1.0, notehead_offset_x: float = 0.0, accidental_offset_x: float = 0.0):
        if duration >= 4.0:
            glyph = self.GLYPH_NOTEHEAD_WHOLE
        elif duration >= 2.0:
            glyph = self.GLYPH_NOTEHEAD_HALF
        else:
            glyph = self.GLYPH_NOTEHEAD_BLACK

        smufl_font = QFont(self._get_smufl_family())
        smufl_font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
        smufl_font.setPixelSize(int(spacing * 3.6))
        
        painter.setFont(smufl_font)
        painter.setPen(QPen(color))
        
        notehead_x = x + notehead_offset_x + spacing * 0.6
        painter.drawText(int(notehead_x), int(y), glyph)
            
        if self._is_accidental(pitch):
            acc_type = self._get_accidental_type(pitch)
            smufl_sharp = "\uE262"
            smufl_flat = "\uE260"
            acc_glyph = smufl_sharp if acc_type == "sharp" else smufl_flat
            
            painter.setFont(smufl_font)
            painter.setPen(QPen(QColor("#111111")))
            
            # Revert vertical hack: SMuFL guarantees perfectly shared baselines. 
            # Tighten horizontal clearance to -0.25s to kiss the notehead.
            acc_x = x + accidental_offset_x - spacing * 0.25
            painter.drawText(int(acc_x), int(y), acc_glyph)

    def _draw_enhanced_note(self, painter: QPainter, x: float, y: float, pitch: int, width: float, spacing: float, color: QColor):
        """
        Draws a modern pedagogical capsule with fixed interior text metrics.
        """
        h = spacing * 0.7 
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

        painter.setPen(QPen(QColor("white")))
        f = QFont("Outfit", int(h * 0.65), QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(f)
        
        painter.drawText(QRectF(x, y - h / 2, width, h), 
                         Qt.AlignmentFlag.AlignCenter, 
                         self._get_note_name(pitch))