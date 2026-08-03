"""
The beat-space layout cache must be invisible.

Scrolling used to re-run the whole engraving pass every frame. It now runs once
per (notes, geometry) and each frame applies a horizontal translation. That is
only safe if the cached engraving is identical to what the per-frame pass
produced, and if it is genuinely rebuilt whenever anything that shapes it
changes. Both are checked here.

The perf test measures that this made things faster; these tests are the ones
that matter, because a stale or wrong cache is a correctness bug that a timing
assertion would never catch.
"""

import pytest

from ui.notation_view import NotationView

WIDTH, HEIGHT = 1200, 500

# Fields the cache carries that must match a fresh engraving exactly.
GEOMETRY_FIELDS = (
    "y", "notehead_offset_x", "accidental_offset_x", "steps_from_ref", "ref_y",
)


def _notes():
    """A slice with chords, seconds, accidentals, rests and a barline — the
    cases the engraver actually has to think about."""
    return [
        # A cluster containing an interval of a second (stagger) and accidentals
        # in the same column (collision resolution).
        {"pitch": 60, "hand": "R", "finger": 1, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 61, "hand": "R", "finger": 2, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 63, "hand": "R", "finger": 3, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 66, "hand": "R", "finger": 4, "start_beat": 0.0, "duration_beats": 1.0},
        {"pitch": 48, "hand": "L", "finger": 5, "start_beat": 0.0, "duration_beats": 4.0},
        {"is_barline": True, "hand": "R", "start_beat": 4.0, "duration_beats": 0.0},
        {"is_rest": True, "hand": "R", "start_beat": 4.0, "duration_beats": 1.0},
        {"pitch": 72, "hand": "R", "finger": 5, "start_beat": 5.0, "duration_beats": 0.5},
        {"pitch": 71, "hand": "R", "finger": 4, "start_beat": 5.5, "duration_beats": 0.5},
        # A note longer than the old hardcoded 8-beat cull window.
        {"pitch": 40, "hand": "L", "finger": 5, "start_beat": 6.0, "duration_beats": 16.0},
    ]


@pytest.fixture
def view(notation_fonts):
    v = NotationView()
    v.setWidth(WIDTH)
    v.setHeight(HEIGHT)
    v.isScrollingMode = True
    v.scrollingNotes = _notes()
    return v


def _geometry(view):
    """The derived constants paint() computes, mirrored for direct engraver calls."""
    from ui.notation_view import STAFF_SPACE_RATIO, STAFF_SEPARATION_SPACES
    s = HEIGHT * STAFF_SPACE_RATIO
    half_sep = (s * STAFF_SEPARATION_SPACES) / 2.0
    return {
        "s": s,
        "ppb": WIDTH * 0.10,
        "treble_y": (HEIGHT * 0.5) - half_sep,
        "bass_y": (HEIGHT * 0.5) + half_sep,
        "start_x": WIDTH * 0.28,
    }


@pytest.mark.parametrize("style", ["enhanced", "traditional"])
@pytest.mark.parametrize("current_beat", [0.0, 1.75, 6.5, 20.0])
def test_cached_layout_matches_a_fresh_engraving(view, style, current_beat):
    """
    The cache plus a translation must equal engraving directly at that beat.

    This is the substitution the optimisation makes, asserted directly.
    """
    view.notationStyle = style
    g = _geometry(view)
    notes = view.scrollingNotes

    fresh = view._get_layout_for_notes(
        notes, current_beat, g["start_x"], g["ppb"], g["treble_y"], g["bass_y"], g["s"]
    )
    cache = view._ensure_layout(
        "scrolling", notes, view._scrolling_version,
        g["ppb"], g["treble_y"], g["bass_y"], g["s"],
    )

    offset_x = g["start_x"] - (current_beat * g["ppb"])
    for i, (f, c) in enumerate(zip(fresh, cache["layout"])):
        assert (f is None) == (c is None), f"note {i}: cached/fresh disagree on layoutability"
        if f is None:
            continue
        assert c["beat_x"] + offset_x == pytest.approx(f["x"], abs=1e-6), (
            f"note {i}: translated cache x does not match a fresh engraving"
        )
        for field in GEOMETRY_FIELDS:
            assert c[field] == pytest.approx(f[field], abs=1e-9), (
                f"note {i}: cached {field} drifted from a fresh engraving"
            )


def test_cache_is_reused_when_nothing_changed(view):
    """A second call with the same inputs must not re-engrave."""
    g = _geometry(view)
    args = ("scrolling", view.scrollingNotes, view._scrolling_version,
            g["ppb"], g["treble_y"], g["bass_y"], g["s"])

    first = view._ensure_layout(*args)
    second = view._ensure_layout(*args)
    assert first is second, "layout was rebuilt despite identical inputs"


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda v: setattr(v, "scrollingNotes", _notes()[:3]), id="notes"),
    pytest.param(lambda v: setattr(v, "notationStyle", "traditional"), id="style"),
    pytest.param(lambda v: setattr(v, "songKeySharps", 4), id="key-signature"),
])
def test_cache_is_rebuilt_when_inputs_change(view, mutate):
    """
    Anything that changes the engraving must invalidate it.

    A stale layout here would pin notes to the wrong staff positions while the
    music kept scrolling — far worse than the cost it saves.
    """
    g = _geometry(view)

    def build():
        return view._ensure_layout(
            "scrolling", view.scrollingNotes, view._scrolling_version,
            g["ppb"], g["treble_y"], g["bass_y"], g["s"],
        )

    before = build()
    mutate(view)
    after = build()
    assert after is not before, "layout was served stale after its inputs changed"


def test_cache_is_rebuilt_on_resize(view):
    """Geometry is part of the key: a resize must re-engrave, not rescale."""
    g = _geometry(view)
    before = view._ensure_layout(
        "scrolling", view.scrollingNotes, view._scrolling_version,
        g["ppb"], g["treble_y"], g["bass_y"], g["s"],
    )

    after = view._ensure_layout(
        "scrolling", view.scrollingNotes, view._scrolling_version,
        g["ppb"] * 1.5, g["treble_y"], g["bass_y"], g["s"] * 1.5,
    )
    assert after is not before, "layout survived a resize it should not have"


def test_long_notes_stay_in_the_window(view):
    """
    A note is drawn until its end passes the playhead, however long it is.

    The cull window's left margin used to be a hardcoded 8 beats, so a note
    longer than that vanished while it was still sounding. The window now covers
    the longest note in the piece.
    """
    g = _geometry(view)
    cache = view._ensure_layout(
        "scrolling", view.scrollingNotes, view._scrolling_version,
        g["ppb"], g["treble_y"], g["bass_y"], g["s"],
    )
    assert cache["max_span"] >= 16.0, (
        "the cull window does not account for the longest note in the piece"
    )


def test_paint_is_stable_across_repeated_frames(view):
    """
    Painting the same beat twice must produce the same pixels.

    Guards against the cache accumulating state across frames — the failure mode
    where notes creep because a translation is applied on top of itself.
    """
    from PySide6.QtGui import QColor, QImage, QPainter

    def render(beat):
        view.scrollBeat = beat
        image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
        image.fill(QColor("#fcfcfc"))
        painter = QPainter(image)
        try:
            view.paint(painter)
        finally:
            painter.end()
        return image

    first = render(3.25)
    render(9.5)          # move away
    second = render(3.25)  # and back

    assert first == second, "the same beat rendered differently on a second visit"
