"""
The notation strip's windowing rules.

The song editor shows a few bars of notation around the note being edited. What
makes that affordable is that it engraves a *window*, not the song — so the
rules deciding what falls inside it are the whole design, and they are easy to
get subtly wrong in ways that read as "the strip is showing me the wrong thing".

Driven the same way test_scroll_clock.py drives ScrollClock: load the component,
set its inputs, call build() directly.
"""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

FOUR_FOUR = [{"offset": 0.0, "numerator": 4, "denominator": 4}]


@pytest.fixture
def window(qapp, qml_dir):
    """A live NotationWindow instance, loaded the way the app loads it."""
    engine = QQmlEngine()
    engine.addImportPath(str(qml_dir.parent))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_dir / "NotationWindow.qml")))

    if component.isError():
        pytest.fail("NotationWindow.qml failed to load:\n" +
                    "\n".join(e.toString() for e in component.errors()))

    obj = component.create()
    assert obj is not None, "NotationWindow.qml produced no object"
    obj._engine = engine  # type: ignore[attr-defined]
    obj._component = component  # type: ignore[attr-defined]
    yield obj
    obj.deleteLater()


def _note(pitch, beat, duration, hand="right", finger=1):
    return {"pitch": pitch, "beat": beat, "duration": duration, "hand": hand, "finger": finger}


def _load(window, notes, bar, sel_beat, sel_duration=1.0,
          barlines=(4.0, 8.0, 12.0, 16.0), signatures=None):
    window.setProperty("notes", list(notes))
    window.setProperty("barlines", list(barlines))
    window.setProperty("timeSignatures", FOUR_FOUR if signatures is None else signatures)
    window.setProperty("bar", bar)
    window.setProperty("selBeat", sel_beat)
    window.setProperty("selDuration", sel_duration)


def _build(window):
    """A QML function hands Python a QJSValue; unwrap it to plain lists/dicts."""
    return window.build().toVariant()


def _barlines_in(window):
    return window.barlinesInWindow().toVariant()


def _pitches(items):
    return sorted(i["pitch"] for i in items if "pitch" in i)


def _notes_only(items):
    return [i for i in items if "pitch" in i]


# --- Nothing selected ------------------------------------------------------

def test_nothing_selected_yields_an_empty_window(window):
    _load(window, [_note(60, 0.0, 1.0)], bar=0, sel_beat=0.0)

    assert _build(window) == []
    assert _barlines_in(window) == []


# --- What falls inside -----------------------------------------------------

def test_the_current_bar_and_its_neighbours_are_included(window):
    notes = [_note(60, 1.0, 1.0), _note(62, 5.0, 1.0), _note(64, 9.0, 1.0)]
    _load(window, notes, bar=2, sel_beat=5.0)

    assert _pitches(_build(window)) == [60, 62, 64]


def test_bars_beyond_the_neighbours_are_excluded(window):
    notes = [_note(60, 1.0, 1.0), _note(72, 17.0, 1.0)]
    _load(window, notes, bar=1, sel_beat=1.0)

    assert _pitches(_build(window)) == [60]


def test_a_note_held_over_from_the_previous_bar_is_included(window):
    """Starts outside the window, still sounding inside it — the context case."""
    notes = [_note(48, 0.5, 8.0), _note(60, 9.0, 1.0)]
    _load(window, notes, bar=3, sel_beat=9.0)

    assert 48 in _pitches(_build(window))


def test_a_note_ending_exactly_at_the_window_start_is_excluded(window):
    notes = [_note(48, 0.0, 4.0), _note(60, 9.0, 1.0)]
    _load(window, notes, bar=3, sel_beat=9.0)

    assert _pitches(_build(window)) == [60]


def test_a_note_starting_exactly_at_the_window_end_is_excluded(window):
    notes = [_note(60, 1.0, 1.0), _note(72, 12.0, 1.0)]
    _load(window, notes, bar=1, sel_beat=1.0)

    assert _pitches(_build(window)) == [60]


# --- The selection is always visible ---------------------------------------

def test_a_note_dragged_past_the_end_of_the_song_stays_in_the_window(window):
    notes = [_note(60, 200.0, 1.0)]
    _load(window, notes, bar=5, sel_beat=200.0)

    assert _pitches(_build(window)) == [60]


def test_the_window_anchors_on_the_note_once_it_is_far_past_its_downbeat(window):
    _load(window, [_note(60, 200.0, 1.0)], bar=5, sel_beat=200.0)

    # Anchored on the note itself, not on bar 5's downbeat at beat 16.
    assert window.scrollBeat() == pytest.approx(199.0)


def test_the_window_anchors_on_the_bar_for_a_note_inside_it(window):
    _load(window, [_note(60, 9.0, 1.0)], bar=3, sel_beat=9.0)

    # Bar 3 starts at beat 8; one beat of lead-in.
    assert window.scrollBeat() == pytest.approx(7.0)


# --- The array's shape -----------------------------------------------------

def test_the_window_opens_with_the_metre_in_force(window):
    _load(window, [_note(60, 1.0, 1.0)], bar=1, sel_beat=1.0)
    items = _build(window)

    assert items[0]["is_time_sig"] is True
    assert items[0]["start_beat"] == 0.0
    assert (items[0]["numerator"], items[0]["denominator"]) == (4, 4)


def test_the_header_reports_the_metre_at_the_window_not_the_song_start(window):
    signatures = [
        {"offset": 0.0, "numerator": 4, "denominator": 4},
        {"offset": 8.0, "numerator": 3, "denominator": 4},
    ]
    _load(window, [_note(60, 13.0, 1.0)], bar=4, sel_beat=13.0,
          barlines=(4.0, 8.0, 11.0, 14.0), signatures=signatures)
    items = _build(window)

    assert (items[0]["numerator"], items[0]["denominator"]) == (3, 4)


def test_a_metre_change_inside_the_window_is_kept_at_its_own_beat(window):
    signatures = [
        {"offset": 0.0, "numerator": 4, "denominator": 4},
        {"offset": 8.0, "numerator": 3, "denominator": 4},
    ]
    _load(window, [_note(60, 5.0, 1.0)], bar=2, sel_beat=5.0, signatures=signatures)

    changes = [i for i in _build(window) if i.get("is_time_sig") and i["start_beat"] > 0.0]
    assert len(changes) == 1
    assert changes[0]["start_beat"] == 8.0
    assert changes[0]["numerator"] == 3


def test_no_barline_items_are_emitted(window):
    """The strip draws barlines as an overlay; emitting them too would double up."""
    _load(window, [_note(60, 1.0, 1.0)], bar=1, sel_beat=1.0)

    assert not any(i.get("is_barline") for i in _build(window))


def test_hands_are_mapped_to_the_renderer_vocabulary(window):
    notes = [_note(60, 1.0, 1.0, hand="right"), _note(48, 1.0, 1.0, hand="left")]
    _load(window, notes, bar=1, sel_beat=1.0)

    hands = {i["pitch"]: i["hand"] for i in _notes_only(_build(window))}
    assert hands == {60: "R", 48: "L"}


def test_notes_carry_their_finger_and_no_stale_relationships(window):
    _load(window, [_note(60, 1.0, 1.0, finger=3)], bar=1, sel_beat=1.0)
    [note] = _notes_only(_build(window))

    assert note["finger"] == 3
    assert note["tie"] is None
    assert note["beam"] is None
    assert note["tuplet"] is None


def test_items_come_back_in_timeline_order(window):
    notes = [_note(67, 5.0, 1.0), _note(60, 1.0, 1.0), _note(64, 1.0, 1.0)]
    _load(window, notes, bar=2, sel_beat=5.0)
    items = _build(window)

    beats = [i["start_beat"] for i in items]
    assert beats == sorted(beats)
    # Equal beats break by pitch, and the header signature leads.
    assert items[0]["is_time_sig"] is True
    assert [i["pitch"] for i in _notes_only(items)] == [60, 64, 67]


# --- Degenerate songs ------------------------------------------------------

def test_a_song_with_no_barlines_does_not_reach_off_the_end(window):
    _load(window, [_note(60, 0.0, 1.0)], bar=1, sel_beat=0.0, barlines=())

    assert _pitches(_build(window)) == [60]
    assert window.windowStart() == pytest.approx(0.0)
    assert window.windowEnd() == pytest.approx(8.0)


def test_a_song_with_no_notes_still_yields_a_drawable_header(window):
    _load(window, [], bar=1, sel_beat=0.0)
    items = _build(window)

    assert len(items) == 1
    assert items[0]["is_time_sig"] is True


def test_a_bar_past_the_last_barline_is_sized_by_the_metre(window):
    """3/4 keeps three-beat bars past the end instead of collapsing."""
    signatures = [{"offset": 0.0, "numerator": 3, "denominator": 4}]
    _load(window, [_note(60, 13.0, 1.0)], bar=6, sel_beat=13.0,
          barlines=(3.0, 6.0, 9.0, 12.0), signatures=signatures)

    # Bar 5 starts at 12.0; bar 6 at 15.0; bar 7 ends at 21.0.
    assert window.barStartBeat(6) == pytest.approx(15.0)
    assert window.windowEnd() == pytest.approx(21.0)


# --- Bar numbering for the overlay -----------------------------------------

def test_barlines_in_window_are_numbered_by_the_bar_they_begin(window):
    _load(window, [_note(60, 9.0, 1.0)], bar=3, sel_beat=9.0)

    assert _barlines_in(window) == [
        {"beat": 4.0, "bar": 2},
        {"beat": 8.0, "bar": 3},
        {"beat": 12.0, "bar": 4},
        {"beat": 16.0, "bar": 5},
    ]


def test_the_first_bar_is_marked_at_the_start_of_the_song(window):
    _load(window, [_note(60, 1.0, 1.0)], bar=1, sel_beat=1.0)

    assert _barlines_in(window)[0] == {"beat": 0.0, "bar": 1}


def test_bar_one_is_not_marked_when_the_window_starts_later(window):
    _load(window, [_note(60, 9.0, 1.0)], bar=3, sel_beat=9.0)

    assert all(b["beat"] > 0.0 for b in _barlines_in(window))


# --- The reason all of this exists -----------------------------------------

def test_a_large_song_still_engraves_a_small_window(window):
    notes = [_note(60 + (i % 12), i * 0.25, 0.25) for i in range(5000)]
    _load(window, notes, bar=3, sel_beat=9.0)

    items = _build(window)
    assert len(items) < 100, "the window must stay small no matter how long the song is"
    assert len(notes) == 5000
