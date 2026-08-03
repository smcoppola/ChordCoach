"""
Frame-time regression guard for paint().

Scrolling only looks smooth if a repaint finishes inside the display's frame
period, so paint() cost is a property of the feature, not a nice-to-have. These
tests sweep the playhead across a deliberately punishing piece and assert the
per-frame cost has not regressed.

Read the budgets honestly:

  * They are measured against a raster QImage. Production renders into an
    OpenGL framebuffer, where path filling and glyph rasterisation — which is
    what the remaining time is — are markedly cheaper. These numbers are a
    pessimistic upper bound, not what the app experiences.
  * The piece is ~9 notes per beat across both hands, sustained. That is denser
    than sight-readable music; it is here to make regressions obvious.
  * "traditional" style is slower than "enhanced" (the default) and at this
    density still exceeds a 60 Hz frame period in raster. The cost is filling
    Bravura outlines at 4 staff spaces to the em, roughly 105px, which is above
    the size any glyph cache will hold. The remaining lever is a glyph atlas,
    which was rejected: blitting pre-rasterised glyphs snaps them to whole
    pixels, and stepping glyphs are exactly the artefact this work removes.

Budgets are set above measured p95 with room for machine noise. Tighten them if
paint gets faster; do not loosen them without a reason recorded here.

Run with -s to see the percentile table:
    pytest tests/test_notation_perf.py -s
"""

import statistics
import time

import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from ui.notation_view import NotationView

PAPER = QColor("#fcfcfc")
WIDTH, HEIGHT = 1200, 500

# A frame at 60 Hz is 16.67 ms and paint() is only part of it — the scene graph
# still has to composite and swap.
FRAME_PERIOD_MS = 1000.0 / 60.0

# Per style, in raster, at the stress density described above. Baselines before
# the scroll work: enhanced 18.4 ms, traditional 23.9 ms.
BUDGET_P95_MS = {
    "enhanced": 13.0,
    "traditional": 20.0,
}

FRAMES = 200
PIECE_BEATS = 200.0


def _dense_piece() -> list:
    """
    A realistic dense passage: right hand in 16ths, left hand in chords.

    ~9 notes per beat across both hands, which is about as busy as engraved
    piano music gets before it stops being sight-readable.
    """
    notes = []
    beat = 0.0
    i = 0
    while beat < PIECE_BEATS:
        # RH: four 16ths per beat, walking up a scale
        for k in range(4):
            notes.append({
                "pitch": 60 + ((i + k) % 15),
                "hand": "R",
                "finger": 1 + ((i + k) % 5),
                "start_beat": beat + k * 0.25,
                "duration_beats": 0.25,
            })
        # LH: a chord on the beat and another on the off-beat
        for offset in (0.0, 0.5):
            for voice in (0, 4, 7):
                notes.append({
                    "pitch": 36 + (i % 12) + voice,
                    "hand": "L",
                    "finger": 5 - voice // 4,
                    "start_beat": beat + offset,
                    "duration_beats": 0.5,
                })
        if i % 4 == 0:
            notes.append({"is_barline": True, "hand": "R", "start_beat": beat, "duration_beats": 0.0})
        beat += 1.0
        i += 1
    return notes


def _sweep_frame_times(view, frames: int = FRAMES) -> list[float]:
    """
    Renders `frames` repaints with the playhead advancing, returning ms per frame.

    The image and painter are reused across frames so the measurement isolates
    paint() rather than allocation of the target surface.
    """
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    timings = []

    # One warm-up frame: the first paint populates the font, metrics and advance
    # caches, and would otherwise dominate the p95.
    view.scrollBeat = 0.0
    painter = QPainter(image)
    try:
        view.paint(painter)
    finally:
        painter.end()

    for f in range(frames):
        # Advance a quarter beat per frame — 100 BPM at 60fps is ~0.028 beats,
        # so this deliberately oversamples distinct layouts rather than
        # repainting the same one.
        view.scrollBeat = f * 0.25

        image.fill(PAPER)
        painter = QPainter(image)
        start = time.perf_counter()
        try:
            view.paint(painter)
        finally:
            painter.end()
        timings.append((time.perf_counter() - start) * 1000.0)

    return timings


def _report(label: str, timings: list[float], budget: float) -> float:
    ordered = sorted(timings)
    p50 = statistics.median(ordered)
    p95 = ordered[int(len(ordered) * 0.95)]
    print(
        f"\n{label}: p50={p50:.2f}ms  p95={p95:.2f}ms  max={ordered[-1]:.2f}ms  "
        f"(budget p95 {budget:.1f}ms, 60Hz frame {FRAME_PERIOD_MS:.2f}ms)"
    )
    return p95


@pytest.fixture
def dense_view(notation_fonts):
    v = NotationView()
    v.setWidth(WIDTH)
    v.setHeight(HEIGHT)
    v.isScrollingMode = True
    v.scrollingNotes = _dense_piece()
    return v


@pytest.mark.parametrize("style", ["enhanced", "traditional"])
def test_paint_stays_within_budget(dense_view, style):
    dense_view.notationStyle = style
    budget = BUDGET_P95_MS[style]
    p95 = _report(f"paint() [{style}]", _sweep_frame_times(dense_view), budget)
    assert p95 < budget, (
        f"{style} paint p95 {p95:.2f}ms exceeds its {budget:.1f}ms budget — "
        "per-frame render cost has regressed; see this module's docstring"
    )


def test_paint_cost_is_flat_across_the_piece(dense_view):
    """
    Frame cost must not grow as the playhead advances into the piece.

    The window cull is a bisect over a prebuilt index, so cost should depend on
    notes *visible*, not on notes *passed*. A rising trend means something is
    scanning the whole array per frame.
    """
    dense_view.notationStyle = "enhanced"
    timings = _sweep_frame_times(dense_view, frames=240)


    first_quarter = statistics.median(timings[:60])
    last_quarter = statistics.median(timings[-60:])
    print(
        f"\ncost drift: first quarter p50={first_quarter:.2f}ms  "
        f"last quarter p50={last_quarter:.2f}ms"
    )

    assert last_quarter < first_quarter * 2.0 + 0.5, (
        f"paint cost grew from {first_quarter:.2f}ms to {last_quarter:.2f}ms as the "
        "playhead advanced — per-frame work is scaling with piece length, not with "
        "what is on screen"
    )
