import os
from pathlib import Path
from PySide6.QtCore import Qt, Property, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontDatabase, QBrush
from PySide6.QtQuick import QQuickPaintedItem

class NotationView(QQuickPaintedItem):
    """
    Advanced Notation Rendering Engine
    Handles grand staff music engraving with dual styles:
    - Traditional: SMuFL/Bravura compliant standard notation
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_pitches = [] # List of MIDI integers or dicts
        self._notation_style = "enhanced" # "traditional" or "enhanced"
        self._display_mode = "trainer" # "trainer" or "evaluation"
        self._is_scrolling_mode = False
        
        self._scroll_beat = 0.0
        self._eval_beat = 0.0
        
        self._eval_notes = []
        self._scrolling_notes = []
        self._eval_note_states = []
        
        self._pedagogical_colors = {
            "1": "#4CAF50", # Green
            "2": "#FFB300", # Yellow
            "3": "#9C27B0", # Purple
            "4": "#2196F3", # Blue
            "5": "#F44336"  # Red
        }
        
        # SMuFL Codepoints (Bravura)
        self.GLYPH_TREBLE_CLEF = "\uE050"
        self.GLYPH_BASS_CLEF = "\uE062"
        self.GLYPH_NOTEHEAD = "\uE0A4"
        self.GLYPH_SHARP = "\uE262"
        self.GLYPH_FLAT = "\uE260"
        
        # Map 12 MIDI notes to 0-6 diatonic steps
        self._diatonic_map = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
        self._pitch_names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

        # Initialization logic for font loading
        self._init_fonts()

    def _init_fonts(self):
        # Resolve path to Bravura. If frozen, it's relative to executable. 
        # If dev, it's in src/resources/fonts.
        try:
            # We assume the file structure src/ui/notation_view.py
            # Resources are at src/resources/fonts
            base_path = Path(__file__).parents[1] / "resources" / "fonts"
            font_path = base_path / "Bravura.otf"
            
            if not font_path.exists():
                # Fallback for frozen/different layouts
                font_path = Path(os.getcwd()) / "resources" / "fonts" / "Bravura.otf"

            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                family = QFontDatabase.applicationFontFamilies(font_id)[0]
                self.smufl_font = QFont(family)
                print(f"NotationView: Loaded font {family} from {font_path}")
            else:
                print(f"NotationView Warning: Could not load Bravura from {font_path}")
                self.smufl_font = QFont("serif")
        except Exception as e:
            print(f"NotationView: Font loading error: {e}")
            self.smufl_font = QFont("serif")

    # --- QML Properties ---
    @Property(list, notify=targetPitchesChanged)
    def targetPitches(self):
        return self._target_pitches

    @targetPitches.setter
    def targetPitches(self, value):
        if self._target_pitches != value:
            self._target_pitches = value
            self.targetPitchesChanged.emit()
            self.update()

    @Property(str, notify=notationStyleChanged)
    def notationStyle(self):
        return self._notation_style

    @notationStyle.setter
    def notationStyle(self, value):
        if self._notation_style != value:
            self._notation_style = value
            self.notationStyleChanged.emit()
            self.update()

    @Property(float, notify=scrollBeatChanged)
    def scrollBeat(self):
        return self._scroll_beat

    @scrollBeat.setter
    def scrollBeat(self, value):
        if self._scroll_beat != value:
            self._scroll_beat = value
            self.scrollBeatChanged.emit()
            self.update()

    @Property(float, notify=evalBeatChanged)
    def evalBeat(self):
        return self._eval_beat

    @evalBeat.setter
    def evalBeat(self, value):
        if self._eval_beat != value:
            self._eval_beat = value
            self.evalBeatChanged.emit()
            self.update()

    @Property(str, notify=displayModeChanged)
    def displayMode(self):
        return self._display_mode

    @displayMode.setter
    def displayMode(self, value):
        if self._display_mode != value:
            self._display_mode = value
            self.displayModeChanged.emit()
            self.update()

    @Property(bool, notify=isScrollingModeChanged)
    def isScrollingMode(self):
        return self._is_scrolling_mode

    @isScrollingMode.setter
    def isScrollingMode(self, value):
        if self._is_scrolling_mode != value:
            self._is_scrolling_mode = value
            self.isScrollingModeChanged.emit()
            self.update()

    @Property(list, notify=evalNotesChanged)
    def evalNotes(self):
        return self._eval_notes

    @evalNotes.setter
    def evalNotes(self, value):
        if self._eval_notes != value:
            self._eval_notes = value
            self.evalNotesChanged.emit()
            self.update()

    @Property(list, notify=scrollingNotesChanged)
    def scrollingNotes(self):
        return self._scrolling_notes

    @scrollingNotes.setter
    def scrollingNotes(self, value):
        if self._scrolling_notes != value:
            self._scrolling_notes = value
            self.scrollingNotesChanged.emit()
            self.update()

    @Property(list, notify=evalNoteStatesChanged)
    def evalNoteStates(self):
        return self._eval_note_states

    @evalNoteStates.setter
    def evalNoteStates(self, value):
        if self._eval_note_states != value:
            self._eval_note_states = value
            self.evalNoteStatesChanged.emit()
            self.update()

    # --- Render Engine ---

    def _get_diatonic_abs(self, pitch: int) -> int:
        octave = pitch // 12
        note = pitch % 12
        return (octave * 7) + self._diatonic_map[note]

    def _get_note_name(self, pitch: int) -> str:
        return self._pitch_names[pitch % 12]

    def _is_accidental(self, pitch: int) -> bool:
        note = pitch % 12
        return note in [1, 3, 6, 8, 10]

    def _get_accidental_type(self, pitch: int) -> str:
        note = pitch % 12
        if note in [1, 6]: return "sharp"
        if note in [3, 8, 10]: return "flat"
        return ""

    def paint(self, painter: QPainter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        rect = self.boundingRect()
        width = rect.width()
        height = rect.height()

        # Geometry Constants (Professional S-system)
        s = height * 0.05
        treble_cy = height * 0.30
        bass_cy = height * 0.70
        note_start_x = width * 0.28
        ppb = width * 0.10 # Pixels Per Beat
        
        # 1. Baseline: Draw Staves
        self._draw_staff_lines(painter, width, treble_cy, s)
        self._draw_staff_lines(painter, width, bass_cy, s)
        
        # 2. Draw Clefs
        self.smufl_font.setPixelSize(int(s * 4))
        painter.setFont(self.smufl_font)
        painter.setPen(QPen(QColor("#222222")))
        g4_y = treble_cy + s 
        painter.drawText(int(width * 0.04), int(g4_y), self.GLYPH_TREBLE_CLEF)
        f3_y = bass_cy - s 
        painter.drawText(int(width * 0.04), int(f3_y), self.GLYPH_BASS_CLEF)

        # 3. Route Rendering
        # Clef Area Protection: Clipping notes so they don't overlap symbols
        painter.save()
        # Content area starts at 15% width to clear clefs
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
        
        painter.restore() # Remove clip for any future global UI draws

    def _render_scrolling_array(self, painter, note_array, current_beat, start_x, ppb, treble_y, bass_y, s):
        """Native loop replacing QML Repeaters for scrolling items."""
        for i, note_data in enumerate(note_array):
            pitch = note_data.get('pitch', 60)
            # Support multiple key names from different services
            start_beat = note_data.get('start_beat', note_data.get('startBeat', 0))
            duration = note_data.get('duration_beats', note_data.get('durationBeats', 1))
            hand = note_data.get('hand', 'R')
            
            # Horizontal calculation
            x = start_x + ((start_beat - current_beat) * ppb)
            
            # Culling optimization (Crucial for performance)
            cap_w = max(duration * ppb - 4, 8) if self._notation_style == "enhanced" else (s * 1.1)
            if x + cap_w < -100 or x > self.width() + 100:
                continue

            # Diatonic Vertical Mapping
            is_treble = True if hand in ["R", "right"] else False if hand in ["L", "left"] else pitch >= 60
            ref_pitch = 71 if is_treble else 50
            ref_y = treble_y if is_treble else bass_y
            
            steps_from_ref = self._get_diatonic_abs(pitch) - self._get_diatonic_abs(ref_pitch)
            y = ref_y - (steps_from_ref * (s / 2))

            # Opacity & Color Logic
            opacity = 1.0
            if self._display_mode == "evaluation":
                state = "pending"
                if i < len(self._eval_note_states):
                    state = self._eval_note_states[i]
                
                if state == "hit": color = QColor("#4CAF50")
                elif state == "miss": 
                    color = QColor("#F44336")
                    opacity = 0.4
                else: 
                    color = self._get_finger_color(note_data.get('finger', 0))
                    # Distance fading for evaluation
                    dist = start_beat - current_beat
                    opacity = 1.0 if dist < 4 else (0.6 if dist < 8 else 0.3)
            else:
                # Trainer mode completion coloring (Green for successful play)
                is_completed = current_beat >= (start_beat + duration)
                is_active = current_beat >= start_beat and current_beat < (start_beat + duration)
                
                if is_completed: 
                    color = QColor("#4CAF50")
                    # Ghostly fade away after being played (0.35 -> 0.0 very rapidly)
                    finish_dist = current_beat - (start_beat + duration)
                    opacity = max(0.0, 0.35 - (finish_dist / 0.5))
                else: 
                    color = self._get_finger_color(note_data.get('finger', 0))
                    if not is_active:
                        # Future notes fade in
                        dist = abs(start_beat - current_beat)
                        opacity = max(0.15, 0.8 - (dist / 10.0))

            painter.setOpacity(opacity)
            
            # Draw
            if self._notation_style == "traditional":
                self._draw_traditional_note(painter, x, y, pitch, s, color)
            else:
                self._draw_enhanced_note(painter, x, y, pitch, cap_w, s, color)
            
            # Ledger lines
            ledger_center_x = x + (s * 0.6 if self._notation_style == "traditional" else cap_w / 2)
            self._draw_ledger_lines(painter, ledger_center_x, steps_from_ref, ref_y, s)
            
        painter.setOpacity(1.0) # Reset

    def _render_static_targets(self, painter, note_start_x, treble_cy, bass_cy, s):
        """Draws stationary targets (chords/pentascales) at the playhead."""
        notes_to_draw = []
        for i, item in enumerate(self._target_pitches):
            if isinstance(item, int):
                notes_to_draw.append({'pitch': item, 'finger': 0, 'is_current': True})
            elif isinstance(item, dict):
                notes_to_draw.append(item)

        is_pentascale = self._notation_style.lower() == "pentascale"
        if not is_pentascale:
            notes_to_draw.sort(key=lambda n: n['pitch'])

        for i, note_data in enumerate(notes_to_draw):
            pitch = note_data['pitch']
            is_current = note_data.get('is_current', True)
            is_treble = pitch >= 60 
            ref_pitch = 71 if is_treble else 50
            ref_y = treble_cy if is_treble else bass_cy
            
            steps_from_ref = self._get_diatonic_abs(pitch) - self._get_diatonic_abs(ref_pitch)
            y = ref_y - (steps_from_ref * (s / 2))
            
            if is_pentascale:
                x = note_start_x + (i * s * 3.0)
                opacity = 1.0 if is_current else 0.4
            else:
                stagger_x = 0
                if i > 0:
                    prev_diatonic = self._get_diatonic_abs(notes_to_draw[i-1]['pitch'])
                    if abs(self._get_diatonic_abs(pitch) - prev_diatonic) < 2:
                        stagger_x = s * 1.0
                x = note_start_x + stagger_x
                opacity = 1.0

            color = self._get_finger_color(note_data.get('finger', 0))
            painter.setOpacity(opacity)
            
            if self._notation_style == "traditional":
                self._draw_traditional_note(painter, x, y, pitch, s, color)
            else:
                cap_w = s * 4.0 if is_pentascale else (s * 3.0)
                self._draw_enhanced_note(painter, x, y, pitch, cap_w, s, color)
                
            ledger_center_x = x + (s * 0.6 if self._notation_style == "traditional" else cap_w / 2)
            self._draw_ledger_lines(painter, ledger_center_x, steps_from_ref, ref_y, s)
            
        painter.setOpacity(1.0)

    def _get_finger_color(self, finger):
        color_hex = self._pedagogical_colors.get(str(finger), "#111111")
        return QColor(color_hex)

    def _draw_staff_lines(self, painter: QPainter, width: float, center_y: float, spacing: float):
        # Professional standard: 0.10 staff space
        weight = max(1.0, spacing * 0.10)
        painter.setPen(QPen(QColor("#222222"), weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for i in range(-2, 3):
            y = center_y + (i * spacing)
            painter.drawLine(0, int(y), int(width), int(y))

    def _draw_traditional_note(self, painter: QPainter, x: float, y: float, pitch: int, spacing: float, color: QColor):
        # Notehead: Pixel-perfect scaling
        # SMuFL noteheads are centered on the origin, so we shift x right by ~0.6s 
        # to align the left edge with the playhead.
        self.smufl_font.setPixelSize(int(spacing * 4))
        painter.setFont(self.smufl_font)
        painter.setPen(QPen(color))
        painter.drawText(int(x + spacing * 0.6), int(y), self.GLYPH_NOTEHEAD)
        
        # Stem
        # Corrected stem position to align with the shifted notehead center (x + 0.6s)
        stem_weight = max(1.0, spacing * 0.11)
        painter.setPen(QPen(QColor("#111111"), stem_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        is_treble = pitch >= 60
        ref_mid = 71 if is_treble else 50
        stem_up = pitch < ref_mid
        
        stem_length = spacing * 3.5 
        # Standard offset from notehead origin is ~0.44s. 
        # Origin is shifted +0.6s, so we use that as the new baseline.
        note_center_x = x + spacing * 0.6
        stem_x = note_center_x + (spacing * 0.44 if stem_up else -spacing * 0.44)
        if stem_up:
            painter.drawLine(int(stem_x), int(y), int(stem_x), int(y - stem_length))
        else:
            painter.drawLine(int(stem_x), int(y), int(stem_x), int(y + stem_length))
            
        # Accidental: Positioned to the left
        if self._is_accidental(pitch):
            acc_type = self._get_accidental_type(pitch)
            glyph = self.GLYPH_SHARP if acc_type == "sharp" else self.GLYPH_FLAT
            painter.setPen(QPen(QColor("#111111")))
            painter.drawText(int(x - spacing * 1.5), int(y), glyph)

    def _draw_enhanced_note(self, painter: QPainter, x: float, y: float, pitch: int, width: float, spacing: float, color: QColor):
        h = spacing * 0.8
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        # Standard alignment: Capsule starts exactly at x and extends right.
        painter.drawRoundedRect(QRectF(x, y - h/2, width, h), h/2, h/2)
        
        # Note name
        painter.setPen(QPen(QColor("white")))
        # Use a standard, high-readability sans-serif font
        f = QFont("Outfit", int(h * 0.65), QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(f)
        
        # Center the text both horizontally and vertically within the capsule
        painter.drawText(QRectF(x, y - h / 2, width, h), 
                         Qt.AlignmentFlag.AlignCenter, 
                         self._get_note_name(pitch))

    def _draw_ledger_lines(self, painter: QPainter, x: float, steps_from_ref: int, ref_y: float, spacing: float):
        # Ledger lines appear when steps_from_ref is >= 6 or <= -6
        # Professional standard: 0.16 staff space weight
        ledger_weight = max(1.0, spacing * 0.16)
        painter.setPen(QPen(QColor("#111111"), ledger_weight, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        ledger_w = spacing * 1.6 # Width: approx 1.6 spaces (wider than notehead)
        if steps_from_ref >= 6:
            for s in range(6, steps_from_ref + 1, 2):
                ly = ref_y - (s * spacing/2)
                painter.drawLine(int(x - ledger_w/2), int(ly), int(x + ledger_w/2), int(ly))
        elif steps_from_ref <= -6:
            for s in range(-6, steps_from_ref - 1, -2):
                ly = ref_y - (s * spacing/2)
                painter.drawLine(int(x - ledger_w/2), int(ly), int(x + ledger_w/2), int(ly))
