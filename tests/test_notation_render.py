"""
Exercises paint() end to end against a real QImage.

The original outage shipped green because no test ever called paint(): the
suite only covered pure helpers. These tests render actual pixels and assert
notes appear, so a dead draw path fails loudly instead of silently producing a
staff with nothing on it.
"""

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from ui.notation_view import NotationView

PAPER = QColor("#fcfcfc")
WIDTH, HEIGHT = 1200, 500


@pytest.fixture
def view(notation_fonts):
    v = NotationView()
    v.setWidth(WIDTH)
    v.setHeight(HEIGHT)
    return v


def _render(view) -> QImage:
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    image.fill(PAPER)
    painter = QPainter(image)
    try:
        view.paint(painter)
    finally:
        painter.end()
    return image


def _colored_pixel_count(image: QImage, region: QRectF) -> int:
    """
    Counts pixels that are neither paper nor greyscale.

    Staff lines, clefs and ledger lines are all grey, so a non-zero count means
    an actual finger-coloured capsule was drawn.
    """
    count = 0
    for y in range(int(region.top()), int(region.bottom()), 2):
        for x in range(int(region.left()), int(region.right()), 2):
            c = image.pixelColor(x, y)
            if c.red() == c.green() == c.blue():
                continue
            count += 1
    return count


def _ink_count(image: QImage, region: QRectF) -> int:
    """Counts any non-paper pixel in a region."""
    count = 0
    for y in range(int(region.top()), int(region.bottom()), 2):
        for x in range(int(region.left()), int(region.right()), 2):
            if image.pixelColor(x, y) != PAPER:
                count += 1
    return count


def _scrolling_notes():
    return [
        {"pitch": 60, "hand": "R", "finger": 1, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 62, "hand": "R", "finger": 2, "start_beat": 1.0, "duration_beats": 1.0},
        {"pitch": 64, "hand": "R", "finger": 3, "start_beat": 2.0, "duration_beats": 2.0},
        {"pitch": 48, "hand": "L", "finger": 5, "start_beat": 0.0, "duration_beats": 4.0},
    ]


# --- The regression these tests exist for ----------------------------------

@pytest.mark.parametrize("style", ["enhanced", "traditional"])
def test_notes_are_drawn_in_both_styles(view, style):
    view.notationStyle = style
    view.isScrollingMode = True
    view.scrollingNotes = _scrolling_notes()
    view.scrollBeat = 0.5

    image = _render(view)
    note_region = QRectF(WIDTH * 0.28, 0, WIDTH * 0.6, HEIGHT)
    assert _ink_count(image, note_region) > 100, (
        f"{style} style rendered no notes — the staff is empty"
    )


def test_enhanced_notes_are_finger_colored(view):
    view.notationStyle = "enhanced"
    view.isScrollingMode = True
    view.scrollingNotes = _scrolling_notes()
    view.scrollBeat = 0.5

    image = _render(view)
    note_region = QRectF(WIDTH * 0.28, 0, WIDTH * 0.6, HEIGHT)
    assert _colored_pixel_count(image, note_region) > 50, (
        "no coloured pixels found — pedagogical capsules did not render"
    )


def test_static_targets_render(view):
    view.notationStyle = "enhanced"
    view.isScrollingMode = False
    view.targetPitches = [
        {"pitch": 60, "hand": "R", "finger": 1},
        {"pitch": 64, "hand": "R", "finger": 3},
        {"pitch": 67, "hand": "R", "finger": 5},
    ]

    image = _render(view)
    note_region = QRectF(WIDTH * 0.2, 0, WIDTH * 0.4, HEIGHT)
    assert _colored_pixel_count(image, note_region) > 20


def test_monochrome_mode_renders(view):
    view.notationStyle = "enhanced"
    view.notationColorMode = "monochrome"
    view.isScrollingMode = True
    view.scrollingNotes = _scrolling_notes()

    image = _render(view)
    note_region = QRectF(WIDTH * 0.28, 0, WIDTH * 0.6, HEIGHT)
    assert _ink_count(image, note_region) > 100


# --- Robustness -------------------------------------------------------------

def test_malformed_note_does_not_blank_the_staff(view):
    """
    A single bad note must cost only that note.

    Previously one failure inside the draw loop aborted paint() and lost every
    subsequent note in the frame.
    """
    view.notationStyle = "enhanced"
    view.isScrollingMode = True
    view.scrollingNotes = [
        {"pitch": None, "hand": "R", "finger": 1, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 64, "hand": "R", "finger": 3, "start_beat": 1.0, "duration_beats": 1.0},
        {"pitch": 67, "hand": "R", "finger": 5, "start_beat": 2.0, "duration_beats": 1.0},
    ]

    image = _render(view)
    note_region = QRectF(WIDTH * 0.28, 0, WIDTH * 0.6, HEIGHT)
    assert _colored_pixel_count(image, note_region) > 20, (
        "a malformed note wiped out the notes that follow it"
    )


@pytest.mark.parametrize("size", [(600, 300), (900, 450), (1920, 800)])
def test_renders_at_varied_pane_sizes(notation_fonts, size):
    width, height = size
    v = NotationView()
    v.setWidth(width)
    v.setHeight(height)
    v.notationStyle = "enhanced"
    v.isScrollingMode = True
    v.scrollingNotes = _scrolling_notes()

    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(PAPER)
    painter = QPainter(image)
    try:
        v.paint(painter)
    finally:
        painter.end()

    region = QRectF(width * 0.28, 0, width * 0.6, height)
    assert _ink_count(image, region) > 30, f"nothing rendered at {width}x{height}"


def test_notes_stay_inside_the_content_clip(view):
    """
    Notes scrolling off the left must not paint over the clef and key signature.

    paint() installs a content clip at 15% of the width. The capsule's onset
    accent clips to the capsule shape, and doing that with Qt's default
    ReplaceClip discarded the outer clip and let the accent escape.
    """
    view.notationStyle = "enhanced"
    view.isScrollingMode = True
    view.scrollingNotes = _scrolling_notes()
    # Scrolled far enough that the first notes are partway off the left edge.
    view.scrollBeat = 1.6

    image = _render(view)
    boundary = WIDTH * 0.15

    leftmost = None
    for y in range(0, HEIGHT, 2):
        for x in range(0, int(boundary)):
            c = image.pixelColor(x, y)
            if c.red() != c.green() or c.green() != c.blue():
                leftmost = x if leftmost is None else min(leftmost, x)
                break

    assert leftmost is None, (
        f"a coloured capsule painted at x={leftmost}, left of the content clip "
        f"at x={boundary:.0f}"
    )


def _stem(beat, is_treble, beam):
    return {"beat": beat, "is_treble": is_treble, "beam_state": beam}


def test_beam_groups_never_span_both_staves(view):
    """
    A beam group must stay on one staff.

    all_stems is ordered by beat across both hands, so grouping purely on beam
    state let a right-hand "start" pair with the next left-hand "continue" and
    draw a beam polygon from a treble stem tip down to a bass stem tip.
    """
    stems = [
        _stem(0.0, True, "start"),
        _stem(0.5, False, "continue"),   # left hand interleaved by beat
        _stem(1.0, True, "stop"),
    ]
    for group in view._group_beam_runs(stems):
        staves = {st["is_treble"] for st in group}
        assert len(staves) == 1, f"beam group mixes staves: {group}"


def test_beam_groups_still_form_on_a_single_staff(view):
    """The staff split must not break ordinary same-hand beaming."""
    stems = [
        _stem(0.0, True, "start"),
        _stem(0.5, True, "continue"),
        _stem(1.0, True, "stop"),
    ]
    groups = [g for g in view._group_beam_runs(stems) if len(g) > 1]
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_unbeamed_stems_do_not_group(view):
    stems = [_stem(0.0, True, None), _stem(0.5, True, None)]
    assert all(len(g) == 1 for g in view._group_beam_runs(stems))


def test_beams_do_not_span_the_two_staves_on_screen(view):
    """End-to-end companion: the interleaved case still renders."""
    view.notationStyle = "traditional"
    view.isScrollingMode = True
    view.scrollingNotes = [
        {"pitch": 71, "hand": "R", "finger": 1, "start_beat": 0.0,
         "duration_beats": 0.5, "beam": "start"},
        {"pitch": 50, "hand": "L", "finger": 1, "start_beat": 0.5,
         "duration_beats": 0.5, "beam": "continue"},
        {"pitch": 71, "hand": "R", "finger": 1, "start_beat": 1.0,
         "duration_beats": 0.5, "beam": "stop"},
    ]
    image = _render(view)
    assert _ink_count(image, QRectF(WIDTH * 0.25, 0, WIDTH * 0.5, HEIGHT)) > 20


def test_rests_render_without_error(view):
    view.notationStyle = "enhanced"
    view.isScrollingMode = True
    view.scrollingNotes = [
        {"is_rest": True, "hand": "R", "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 64, "hand": "R", "finger": 3, "start_beat": 1.0, "duration_beats": 1.0},
    ]
    image = _render(view)
    region = QRectF(WIDTH * 0.28, 0, WIDTH * 0.6, HEIGHT)
    assert _colored_pixel_count(image, region) > 10


def test_eval_mode_does_not_borrow_the_scrolling_index(view):
    """
    Guards the index-provenance fix: the bisect index is built from
    scrollingNotes, so evaluation mode (which draws evalNotes) must not use it
    just because the two arrays happen to be the same length.
    """
    view.notationStyle = "enhanced"
    view.scrollingNotes = _scrolling_notes()
    view.displayMode = "evaluation"
    view.evalNotes = [
        {"pitch": 72, "hand": "R", "finger": 1, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 74, "hand": "R", "finger": 2, "start_beat": 1.0, "duration_beats": 1.0},
        {"pitch": 76, "hand": "R", "finger": 3, "start_beat": 2.0, "duration_beats": 1.0},
        {"pitch": 77, "hand": "R", "finger": 4, "start_beat": 3.0, "duration_beats": 1.0},
    ]
    assert len(view.evalNotes) == len(view.scrollingNotes)

    image = _render(view)
    region = QRectF(WIDTH * 0.28, 0, WIDTH * 0.6, HEIGHT)
    assert _colored_pixel_count(image, region) > 20
