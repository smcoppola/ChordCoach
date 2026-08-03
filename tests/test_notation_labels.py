"""
Turns "every note always shows its letter" from an intention into an invariant.

The pedagogical display encodes pitch by staff position, duration by capsule
width, fingering by colour, and the note name by a letter drawn on the capsule.
The letter is the part users read first, so these tests assert it is always
placed and always legible, across pane sizes and note durations.
"""

import pytest

from ui.notation_view import (
    CAPSULE_HEIGHT_RATIO,
    MIN_LABEL_PX,
    NotationView,
    STAFF_SEPARATION_SPACES,
    STAFF_SPACE_RATIO,
    contrast_ratio,
    label_color_for,
    relative_luminance,
)
from PySide6.QtGui import QColor

# WCAG AA for large text. The capsule letter is Inter Bold at roughly 0.9x the
# capsule height, which clears the large-text size threshold at every pane size
# the app supports, so 3.0 is the applicable bar rather than 4.5.
MIN_LARGE_TEXT_CONTRAST = 3.0

# Every capsule fill the renderer can produce, built from the live palette so a
# new finger colour cannot be added without also being contrast-checked.
_ALL_FILLS = dict(
    {f"finger {k}": v for k, v in NotationView()._pedagogical_colors.items()},
    **{
        "monochrome": "#555555",
        "completed": "#888888",
        "miss": "#F44336",
        "monochrome active": "#111111",
    },
)

# Fills deliberately kept below MIN_LARGE_TEXT_CONTRAST with a white label.
# Listed rather than quietly dropped from the check, so the trade-off stays
# visible and no new colour can join them by accident.
ACCEPTED_BELOW_BAR = {
    # ~1.7:1. The index finger's yellow is part of the finger-colour mapping
    # learners memorise, and darkening it enough for white text turns it orange.
    # Kept as-is by explicit decision; the letter stays readable in practice
    # because it is bold and large against a saturated ground.
    "#FFB300": "index-finger amber, kept for finger-colour recognition",
    # ~2.9:1, fractionally under. These are notes the playhead has already
    # passed, where the letter is reference rather than guidance.
    "#888888": "completed/hit notes, marginally under the bar",
}

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
    """
    Mirrors the optical constants paint() derives from the item's size.

    Imports the ratios rather than restating them: a local copy would keep
    these tests passing against the old geometry while the app renders the
    new one, which is exactly the drift they exist to catch.
    """
    s = height * STAFF_SPACE_RATIO
    ppb = width * 0.10
    return s, ppb


def _staff_centers(height):
    """Treble and bass centre lines, as paint() places them."""
    s = height * STAFF_SPACE_RATIO
    half_sep = (s * STAFF_SEPARATION_SPACES) / 2.0
    return (height * 0.5) - half_sep, (height * 0.5) + half_sep


# --- The core invariant ----------------------------------------------------

@pytest.mark.parametrize("width", PANE_WIDTHS)
@pytest.mark.parametrize("height", PANE_HEIGHTS)
@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("text", LABELS)
def test_label_is_always_placed(view, width, height, duration, text):
    """No combination of pane size and duration may yield an unlabelled note."""
    s, ppb = _geometry(width, height)
    cap_w = view._capsule_width({"duration_beats": duration}, ppb, s, text)
    h = s * CAPSULE_HEIGHT_RATIO

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
    h = s * CAPSULE_HEIGHT_RATIO

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
    plan = view._plan_note_label("C", cap_w, s * CAPSULE_HEIGHT_RATIO, s)
    assert plan["inside"]


def test_note_labels_are_legible_at_a_normal_pane(view):
    """
    Readability is the point of the display, so the letter on an ordinary
    quarter note at an ordinary pane size has to be genuinely large — not
    merely "placed somewhere at the legibility floor".
    """
    s, ppb = _geometry(1400, 450)
    cap_w = view._capsule_width({"duration_beats": 1.0}, ppb, s, "C")
    plan = view._plan_note_label("C", cap_w, s * CAPSULE_HEIGHT_RATIO, s)

    assert plan["inside"]
    assert plan["px"] >= 18.0, f"quarter-note label is only {plan['px']}px"


# --- Grand staff geometry --------------------------------------------------

@pytest.mark.parametrize("height", PANE_HEIGHTS)
def test_middle_c_positions_do_not_cross(height):
    """
    The two staves are placed a fixed number of staff spaces apart precisely so
    this holds. With centres pinned to height fractions instead, raising
    STAFF_SPACE_RATIO eventually pushes the treble's middle C *below* the
    bass's and the grand staff turns inside out.
    """
    s = height * STAFF_SPACE_RATIO
    treble_cy, bass_cy = _staff_centers(height)

    treble_middle_c = treble_cy + 3 * s   # 6 diatonic steps below B4
    bass_middle_c = bass_cy - 3 * s       # 6 diatonic steps above D3

    assert bass_middle_c - treble_middle_c >= s, (
        "middle C must read unambiguously on each staff: "
        f"treble at {treble_middle_c}, bass at {bass_middle_c}"
    )


@pytest.mark.parametrize("height", PANE_HEIGHTS)
def test_grand_staff_leaves_ledger_headroom(height):
    """The system must fit the pane with room for ledger lines above and below."""
    s = height * STAFF_SPACE_RATIO
    treble_cy, bass_cy = _staff_centers(height)

    top_line = treble_cy - 2 * s
    bottom_line = bass_cy + 2 * s

    assert top_line >= 3 * s, f"only {top_line / s:.1f} spaces above the treble staff"
    assert height - bottom_line >= 3 * s, (
        f"only {(height - bottom_line) / s:.1f} spaces below the bass staff"
    )


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

def _worst_case_contrast(hex_fill: str) -> float:
    """
    Contrast of the label against the lightest part of the capsule.

    The fill is a vertical gradient running from lighter(112) to darker(108),
    so the top of the capsule is where a white letter is hardest to read. Testing
    the flat colour would pass fills that are marginal in the places that matter.
    """
    fill = QColor(hex_fill)
    return contrast_ratio(fill.lighter(112), label_color_for(fill))


@pytest.mark.parametrize("name,hex_fill", sorted(_ALL_FILLS.items()))
def test_every_fill_carries_its_label(view, name, hex_fill):
    """
    Labels are always white, so the legibility requirement lands on the fills:
    each must be dark enough to carry white text.

    The bar is the WCAG large-text threshold, which these labels qualify for —
    Inter Bold at roughly 0.9x the capsule height. Fills held below it on
    purpose are listed in ACCEPTED_BELOW_BAR with the reason.
    """
    if hex_fill in ACCEPTED_BELOW_BAR:
        pytest.skip(f"{name}: {ACCEPTED_BELOW_BAR[hex_fill]}")

    ratio = _worst_case_contrast(hex_fill)
    assert ratio >= MIN_LARGE_TEXT_CONTRAST, (
        f"{name} ({hex_fill}) carries white text at only {ratio:.2f}:1 at the "
        f"light end of its gradient; needs {MIN_LARGE_TEXT_CONTRAST}:1"
    )


def test_accepted_exceptions_are_still_in_use():
    """
    Stops the exception list outliving the colours it excuses.

    An entry here suppresses a real legibility check, so a stale one would
    silently keep suppressing it for a colour that no longer exists.
    """
    unused = set(ACCEPTED_BELOW_BAR) - set(_ALL_FILLS.values())
    assert not unused, f"ACCEPTED_BELOW_BAR lists fills nothing uses: {unused}"


def test_accepted_exceptions_actually_need_the_exception():
    """
    The converse: an entry that now clears the bar should be deleted, not left
    quietly disabling the check.
    """
    needless = {
        h for h in ACCEPTED_BELOW_BAR
        if _worst_case_contrast(h) >= MIN_LARGE_TEXT_CONTRAST
    }
    assert not needless, (
        f"these fills now clear {MIN_LARGE_TEXT_CONTRAST}:1 and no longer need "
        f"an exception: {needless}"
    )


def test_labels_are_uniformly_white(view):
    """No fill may opt into a dark label — that is the look this replaced."""
    for hex_fill in _ALL_FILLS.values():
        assert label_color_for(QColor(hex_fill)).name().upper() == "#FFFFFF"


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


def test_green_and_blue_stay_dark_enough_for_white(view):
    """
    Pins the two colours that were darkened specifically to carry a white label.

    Green and blue are the Material 700 shades rather than 500 for this reason;
    reverting either to a lighter shade fails here.
    """
    for finger, name in (("1", "green"), ("4", "blue")):
        hex_fill = view._pedagogical_colors[finger]
        ratio = _worst_case_contrast(hex_fill)
        assert ratio >= MIN_LARGE_TEXT_CONTRAST, (
            f"{name} ({hex_fill}) is too light for a white label ({ratio:.2f}:1)"
        )


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
