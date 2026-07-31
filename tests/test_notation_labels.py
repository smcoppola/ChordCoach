"""
Turns "every note always shows its letter" from an intention into an invariant.

The pedagogical display encodes pitch by staff position, duration by capsule
width, fingering by colour, and the note name by a letter drawn on the capsule.
The letter is the part users read first, so these tests assert it is always
placed and always legible, across pane sizes and note durations.
"""

import pytest

from ui.notation_view import (
    MIN_LABEL_PX,
    NotationView,
    contrast_ratio,
    label_color_for,
    relative_luminance,
)
from PySide6.QtGui import QColor

# WCAG AA for normal text. Every capsule fill the renderer can produce must
# clear this against its chosen label colour.
MIN_CONTRAST = 4.5

# Pane sizes span a small windowed pane through a 4K-ish full screen.
PANE_WIDTHS = [600, 900, 1400, 2400]
PANE_HEIGHTS = [300, 450, 700]
# 32nd through whole note.
DURATIONS = [0.125, 0.25, 0.5, 1.0, 2.0, 4.0]
# One- and two-character names, covering the accidental glyphs.
LABELS = ["C", "F♯", "E♭", "B"]


@pytest.fixture
def view(notation_fonts):
    return NotationView()


def _geometry(width, height):
    """Mirrors the optical constants paint() derives from the item's size."""
    s = height * 0.035
    ppb = width * 0.10
    return s, ppb


# --- The core invariant ----------------------------------------------------

@pytest.mark.parametrize("width", PANE_WIDTHS)
@pytest.mark.parametrize("height", PANE_HEIGHTS)
@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("text", LABELS)
def test_label_is_always_placed(view, width, height, duration, text):
    """No combination of pane size and duration may yield an unlabelled note."""
    s, ppb = _geometry(width, height)
    cap_w = view._capsule_width({"duration_beats": duration}, ppb, s, text)
    h = s * 0.92

    plan = view._plan_note_label(text, cap_w, h, s)

    assert plan["text"] == text, "the label text must never be truncated away"
    assert plan["px"] >= MIN_LABEL_PX, (
        f"label shrank below the legibility floor at {width}x{height}, "
        f"duration {duration}: {plan['px']}px"
    )


@pytest.mark.parametrize("width", PANE_WIDTHS)
@pytest.mark.parametrize("height", PANE_HEIGHTS)
@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("text", LABELS)
def test_inside_labels_actually_fit(view, width, height, duration, text):
    """When the planner says 'inside', the glyphs must genuinely fit the capsule."""
    s, ppb = _geometry(width, height)
    cap_w = view._capsule_width({"duration_beats": duration}, ppb, s, text)
    h = s * 0.92

    plan = view._plan_note_label(text, cap_w, h, s)
    if not plan["inside"]:
        pytest.skip("planner chose outside placement")

    advance = view._text_advance(plan["text"], plan["px"])
    assert advance <= cap_w - 2 * view._label_pad_x(s) + 0.01, (
        f"label overflows its capsule at {width}x{height}: {advance} > {cap_w}"
    )


@pytest.mark.parametrize("height", PANE_HEIGHTS)
def test_tall_panes_keep_labels_inside(view, height):
    """
    At a comfortable pane size, labels belong inside the capsule.

    Outside placement is the short-pane fallback; if it started triggering at
    normal sizes the display would look scattered.
    """
    if height < 400:
        pytest.skip("short pane legitimately uses outside placement")
    s, ppb = _geometry(1400, height)
    cap_w = view._capsule_width({"duration_beats": 1.0}, ppb, s, "C")
    plan = view._plan_note_label("C", cap_w, s * 0.92, s)
    assert plan["inside"]


# --- Capsule width ---------------------------------------------------------

@pytest.mark.parametrize("width", PANE_WIDTHS)
@pytest.mark.parametrize("height", PANE_HEIGHTS)
def test_capsule_width_is_monotonic_in_duration(view, width, height):
    """Longer notes are never narrower — the duration encoding must hold."""
    s, ppb = _geometry(width, height)
    widths = [
        view._capsule_width({"duration_beats": d}, ppb, s, "C")
        for d in DURATIONS
    ]
    assert widths == sorted(widths), f"capsule widths not monotonic: {widths}"


def test_capsule_width_encodes_duration_at_normal_sizes(view):
    """A half note must be visibly wider than a quarter, not clamped flat."""
    s, ppb = _geometry(1400, 500)
    quarter = view._capsule_width({"duration_beats": 1.0}, ppb, s, "C")
    half = view._capsule_width({"duration_beats": 2.0}, ppb, s, "C")
    whole = view._capsule_width({"duration_beats": 4.0}, ppb, s, "C")
    assert half > quarter * 1.5
    assert whole > half * 1.5


@pytest.mark.parametrize("width", PANE_WIDTHS)
@pytest.mark.parametrize("height", PANE_HEIGHTS)
@pytest.mark.parametrize("text", LABELS)
def test_capsule_never_narrower_than_its_label(view, width, height, text):
    """The floor that makes inside placement possible for very short notes."""
    s, ppb = _geometry(width, height)
    cap_w = view._capsule_width({"duration_beats": 0.125}, ppb, s, text)
    needed = view._text_advance(text, MIN_LABEL_PX) + 2 * view._label_pad_x(s)
    assert cap_w >= needed - 0.01


def test_capsule_width_survives_malformed_duration(view):
    """Bad note data must not crash the width helper."""
    s, ppb = _geometry(1400, 500)
    for bad in (None, "abc", {}):
        assert view._capsule_width({"duration_beats": bad}, ppb, s, "C") > 0


# --- Contrast --------------------------------------------------------------

def _all_fill_colors(view):
    """Every capsule fill colour the renderer can produce."""
    fills = list(view._pedagogical_colors.values())
    fills += [
        "#555555",  # monochrome mode
        "#888888",  # completed / hit
        "#F44336",  # miss
        "#111111",  # monochrome active, and the no-finger fallback
    ]
    return fills


def test_every_fill_color_has_a_legible_label(view):
    for hex_fill in _all_fill_colors(view):
        fill = QColor(hex_fill)
        label = label_color_for(fill)
        ratio = contrast_ratio(fill, label)
        assert ratio >= MIN_CONTRAST, (
            f"{hex_fill} pairs with {label.name()} at only {ratio:.2f}:1"
        )


def test_luminance_endpoints():
    """Sanity-check the WCAG luminance implementation against known values."""
    assert relative_luminance(QColor("#000000")) == pytest.approx(0.0, abs=1e-6)
    assert relative_luminance(QColor("#FFFFFF")) == pytest.approx(1.0, abs=1e-6)


def test_contrast_ratio_endpoints():
    black, white = QColor("#000000"), QColor("#FFFFFF")
    assert contrast_ratio(black, white) == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio(black, black) == pytest.approx(1.0, abs=1e-6)
    # Order must not matter.
    assert contrast_ratio(white, black) == pytest.approx(contrast_ratio(black, white))


def test_amber_uses_dark_text(view):
    """
    The regression this rule fixes: the previous implementation drew white on
    every fill, which on the index-finger amber was about 1.9:1.
    """
    amber = QColor(view._pedagogical_colors["2"])
    assert label_color_for(amber).lightness() < 128
    assert contrast_ratio(amber, QColor("#FFFFFF")) < MIN_CONTRAST


# --- Outside-label collision resolution ------------------------------------

def test_outside_labels_stack_without_dropping_any(view):
    """Colliding labels are displaced, never skipped."""
    placed: list = []
    ys = [
        view._place_outside_label(placed, cx=100.0, cy=50.0, w=20.0, h=10.0, above=True)
        for _ in range(6)
    ]
    assert len(placed) == 6, "every label must be recorded, even past the row cap"
    # The first few must be pushed clear of one another.
    assert len(set(ys[:4])) == 4


def test_outside_label_rows_move_away_from_the_staff(view):
    placed: list = []
    first = view._place_outside_label(placed, 100.0, 50.0, 20.0, 10.0, above=True)
    second = view._place_outside_label(placed, 100.0, 50.0, 20.0, 10.0, above=True)
    assert second < first, "labels above the staff must stack upward"

    placed = []
    first = view._place_outside_label(placed, 100.0, 50.0, 20.0, 10.0, above=False)
    second = view._place_outside_label(placed, 100.0, 50.0, 20.0, 10.0, above=False)
    assert second > first, "labels below the staff must stack downward"


# --- Label text ------------------------------------------------------------

def test_note_label_text_covers_all_pitch_classes(view):
    for pitch in range(60, 72):
        text = view._note_label_text(pitch)
        assert text, f"pitch {pitch} produced an empty label"
        assert len(text) <= 2


def test_accidental_fallback_is_ascii_when_glyphs_missing(view, monkeypatch):
    """If the label font lacks ♯/♭, names degrade to ASCII rather than tofu."""
    monkeypatch.setattr(view, "_accidentals_renderable", lambda: False)
    assert view._note_label_text(61) == "C#"
    assert view._note_label_text(63) == "Eb"
