import inspect
import pytest
from ui.notation_view import NotationView


def test_duration_to_glyph_standard():
    nv = NotationView()
    # Whole
    base, flag, dots = nv._duration_to_glyph(4.0)
    assert base == nv.GLYPH_NOTEHEAD_WHOLE
    assert flag is None
    assert dots == 0

    # Half
    base, flag, dots = nv._duration_to_glyph(2.0)
    assert base == nv.GLYPH_NOTEHEAD_HALF
    assert flag is None
    assert dots == 0

    # Quarter
    base, flag, dots = nv._duration_to_glyph(1.0)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert flag is None
    assert dots == 0

    # 8th
    base, flag, dots = nv._duration_to_glyph(0.5)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert flag == "8th"
    assert dots == 0

    # 16th
    base, flag, dots = nv._duration_to_glyph(0.25)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert flag == "16th"
    assert dots == 0


def test_duration_to_glyph_dotted():
    nv = NotationView()
    # Dotted Whole (6.0)
    base, flag, dots = nv._duration_to_glyph(6.0)
    assert base == nv.GLYPH_NOTEHEAD_WHOLE
    assert dots == 1

    # Dotted Half (3.0)
    base, flag, dots = nv._duration_to_glyph(3.0)
    assert base == nv.GLYPH_NOTEHEAD_HALF
    assert dots == 1

    # Dotted Quarter (1.5)
    base, flag, dots = nv._duration_to_glyph(1.5)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert dots == 1

    # Dotted Eighth (0.75)
    base, flag, dots = nv._duration_to_glyph(0.75)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert flag == "8th"
    assert dots == 1

    # Dotted Sixteenth (0.375)
    base, flag, dots = nv._duration_to_glyph(0.375)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert flag == "16th"
    assert dots == 1


def test_duration_to_glyph_tuplet():
    nv = NotationView()
    # Triplet Eighth: raw duration 0.33333, tuplet actual=3, normal=2
    # Effective duration = 0.33333 * 3 / 2 = 0.5 (8th note)
    tuplet = {"actual": 3, "normal": 2, "pos": "start"}
    base, flag, dots = nv._duration_to_glyph(1.0 / 3.0, tuplet=tuplet)
    assert base == nv.GLYPH_NOTEHEAD_BLACK
    assert flag == "8th"
    assert dots == 0


def test_duration_to_glyph_fallback():
    nv = NotationView()
    # Odd MIDI duration 0.8 -> closest to 0.75 (dotted 8th) or 1.0 (quarter)
    base, flag, dots = nv._duration_to_glyph(0.8)
    assert base is not None


def test_draw_traditional_note_signature():
    sig = inspect.signature(NotationView._draw_traditional_note)
    params = sig.parameters
    assert "spelling" in params
    assert "tuplet" in params
    assert "steps_from_ref" in params
