"""
The note editor's editing rules.

The piano roll in SongNoteEditor.qml is only a view: every selection and every
change goes through NoteEdits.qml, which holds the working copy of the song.
These tests drive that object directly, the way test_strip_window.py drives
NotationWindow, so the rules that decide where a dragged note lands — and what
one press of Undo takes back — are pinned without a mouse.
"""

import json

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

BARLINES = [4.0, 8.0, 12.0]


@pytest.fixture
def edits(qapp, qml_dir):
    engine = QQmlEngine()
    engine.addImportPath(str(qml_dir.parent))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_dir / "NoteEdits.qml")))
    if component.isError():
        pytest.fail("NoteEdits.qml failed to load:\n" +
                    "\n".join(e.toString() for e in component.errors()))
    obj = component.create()
    assert obj is not None, "NoteEdits.qml produced no object"
    obj._engine = engine  # type: ignore[attr-defined]
    obj._component = component  # type: ignore[attr-defined]
    yield obj
    obj.deleteLater()


def _py(value):
    """QML hands back a QJSValue for arrays and objects, plain values otherwise."""
    return value.toVariant() if hasattr(value, "toVariant") else value


def _row(pitch, beat, duration=1.0, hand="right", i=0):
    return {"pitch": pitch, "beat": beat, "duration": duration, "hand": hand,
            "name": f"p{pitch}", "measure": 1, "finger": 1,
            "step_index": i, "note_index": 0}


# Index:   0            1            2             3             4
# A chord at beat 0 (C E G, the C in the left hand), then two melody notes.
def _song():
    return [
        _row(48, 0.0, 2.0, "left", 0),
        _row(64, 0.0, 1.0, "right", 1),
        _row(67, 0.25, 1.0, "right", 2),
        _row(72, 4.0, 0.5, "right", 3),
        _row(74, 6.0, 1.0, "right", 4),
    ]


@pytest.fixture
def loaded(edits):
    edits.load(_song(), BARLINES)
    return edits


def _notes(edits):
    return _py(edits.property("notes"))


def _beats(edits):
    return [n["beat"] for n in _notes(edits)]


def _durations(edits):
    return [n["duration"] for n in _notes(edits)]


def _hands(edits):
    return [n["hand"] for n in _notes(edits)]


def _selection(edits):
    return [int(i) for i in _py(edits.selectedIndices())]


# --- Loading -------------------------------------------------------------------

def test_load_keeps_every_row_and_its_provenance(loaded):
    notes = _notes(loaded)
    assert len(notes) == 5
    assert [n["step_index"] for n in notes] == [0, 1, 2, 3, 4]
    assert loaded.property("changedCount") == 0
    assert loaded.property("selectedCount") == 0
    assert loaded.property("primary") == -1


def test_load_clears_what_a_previous_song_left_behind(loaded):
    loaded.selectOnly(1)
    loaded.moveBy(1.0)
    loaded.load(_song(), BARLINES)
    assert loaded.property("changedCount") == 0
    assert loaded.property("selectedCount") == 0
    assert loaded.property("undoDepth") == 0


# --- Selection -----------------------------------------------------------------

def test_select_only_replaces_the_selection(loaded):
    loaded.selectOnly(1)
    loaded.selectOnly(3)
    assert _selection(loaded) == [3]
    assert loaded.property("primary") == 3


def test_toggle_adds_and_removes(loaded):
    loaded.selectOnly(1)
    loaded.toggle(2)
    assert _selection(loaded) == [1, 2]
    loaded.toggle(1)
    assert _selection(loaded) == [2]
    assert loaded.property("primary") == 2


def test_box_selects_by_time_and_pitch(loaded):
    # Beats 0–1, pitches 60–70: the E and the G, not the low C or later notes.
    loaded.selectBox(0.0, 1.0, 60, 70, False)
    assert _selection(loaded) == [1, 2]


def test_box_can_add_to_the_selection(loaded):
    loaded.selectOnly(4)
    loaded.selectBox(0.0, 1.0, 60, 70, True)
    assert _selection(loaded) == [1, 2, 4]


def test_box_takes_its_corners_in_either_order(loaded):
    loaded.selectBox(1.0, 0.0, 70, 60, False)
    assert _selection(loaded) == [1, 2]


def test_select_from_takes_everything_starting_at_or_after_a_beat(loaded):
    loaded.selectFrom(4.0)
    assert _selection(loaded) == [3, 4]


def test_extend_to_end_starts_at_the_earliest_selected_note(loaded):
    loaded.selectOnly(2)
    loaded.extendToEnd()
    assert _selection(loaded) == [2, 3, 4]


def test_hand_filter_limits_what_can_be_selected(loaded):
    loaded.setProperty("handFilter", "right")
    loaded.selectAll()
    assert _selection(loaded) == [1, 2, 3, 4]
    assert _py(loaded.noteAt(0.5, 48)) == -1
    loaded.setProperty("handFilter", "all")
    assert _py(loaded.noteAt(0.5, 48)) == 0


def test_clear_empties_the_selection(loaded):
    loaded.selectAll()
    loaded.clear()
    assert _selection(loaded) == []
    assert loaded.property("primary") == -1


# --- Moving --------------------------------------------------------------------

def test_move_shifts_only_the_selection(loaded):
    loaded.selectOnly(3)
    loaded.moveBy(0.5)
    assert _beats(loaded) == [0.0, 0.0, 0.25, 4.5, 6.0]
    assert loaded.property("changedCount") == 1


def test_move_snaps_to_the_sixteenth_grid(loaded):
    loaded.selectOnly(3)
    loaded.moveBy(0.6)
    assert _beats(loaded)[3] == 4.5
    loaded.moveBy(-0.1)
    assert _beats(loaded)[3] == 4.5


def test_a_group_stops_at_beat_zero_and_keeps_its_shape(loaded):
    loaded.selectBox(0.0, 5.0, 60, 80, False)   # E@0, G@0.25, C@4
    loaded.moveBy(-2.0)
    assert _beats(loaded) == [0.0, 0.0, 0.25, 4.0, 6.0]
    loaded.selectFrom(4.0)
    loaded.moveBy(-10.0)
    assert _beats(loaded)[3:] == [0.0, 2.0]


def test_moving_a_note_across_a_barline_renumbers_its_measure(loaded):
    loaded.selectOnly(3)
    assert _notes(loaded)[3]["measure"] == 2
    loaded.moveBy(-0.25)
    assert _notes(loaded)[3]["measure"] == 1
    loaded.moveBy(4.25)
    assert _notes(loaded)[3]["measure"] == 3


def test_moving_back_to_where_it_started_is_not_a_change(loaded):
    loaded.selectOnly(3)
    loaded.moveBy(0.5)
    loaded.moveBy(-0.5)
    assert loaded.property("changedCount") == 0


# --- Lengths -------------------------------------------------------------------

def test_resize_changes_every_selected_note(loaded):
    loaded.selectBox(0.0, 1.0, 60, 70, False)
    loaded.resizeBy(0.5)
    assert _durations(loaded) == [2.0, 1.5, 1.5, 0.5, 1.0]


def test_a_note_never_gets_shorter_than_one_grid_unit(loaded):
    loaded.selectOnly(3)
    loaded.resizeBy(-5.0)
    assert _durations(loaded)[3] == 0.25


def test_match_lengths_copies_the_primary_note(loaded):
    loaded.selectOnly(0)          # two beats long
    loaded.toggle(1)
    loaded.toggle(2)
    loaded.setPrimary(0)
    loaded.matchLengths()
    assert _durations(loaded)[:3] == [2.0, 2.0, 2.0]


# --- Lining up a spread chord ---------------------------------------------------

def test_align_puts_every_selected_note_on_the_earliest_start(loaded):
    loaded.selectBox(0.0, 1.0, 40, 70, False)
    loaded.alignStarts()
    assert _beats(loaded)[:3] == [0.0, 0.0, 0.0]
    assert loaded.property("changedCount") == 1


# --- Hands ---------------------------------------------------------------------

def test_set_hand_applies_to_the_selection(loaded):
    loaded.selectBox(0.0, 1.0, 60, 70, False)
    loaded.setHand("left")
    assert _hands(loaded) == ["left", "left", "left", "right", "right"]


def test_flip_hand_changes_one_note_whatever_is_selected(loaded):
    loaded.selectOnly(3)
    loaded.flipHand(0)
    assert _hands(loaded) == ["right", "right", "right", "right", "right"]
    loaded.flipHand(0)
    assert _hands(loaded)[0] == "left"
    assert loaded.property("changedCount") == 0


# --- Reset ---------------------------------------------------------------------

def test_reset_restores_the_selected_notes_only(loaded):
    loaded.selectAll()
    loaded.moveBy(1.0)
    loaded.setHand("left")
    loaded.selectOnly(1)
    loaded.resetSelection()
    assert _beats(loaded) == [1.0, 0.0, 1.25, 5.0, 7.0]
    assert _hands(loaded)[1] == "right"
    assert loaded.property("changedCount") == 4


# --- Undo ----------------------------------------------------------------------

def test_undo_and_redo_restore_exactly(loaded):
    before = _notes(loaded)
    loaded.selectAll()
    loaded.moveBy(1.0)
    loaded.setHand("left")
    after = _notes(loaded)

    loaded.undo()
    loaded.undo()
    assert _notes(loaded) == before
    assert loaded.property("changedCount") == 0
    loaded.undo()                                  # nothing left: a no-op
    assert _notes(loaded) == before

    loaded.redo()
    loaded.redo()
    assert _notes(loaded) == after


def test_a_drag_is_one_undo_step_however_far_it_went(loaded):
    loaded.selectOnly(3)
    loaded.beginGesture()
    for delta in (0.25, 0.5, 0.75, 1.0):
        loaded.gestureMove(delta)
    loaded.endGesture()
    assert _beats(loaded)[3] == 5.0
    assert loaded.property("undoDepth") == 1
    loaded.undo()
    assert _beats(loaded)[3] == 4.0


def test_a_drag_that_ends_where_it_began_leaves_no_undo_step(loaded):
    loaded.selectOnly(3)
    loaded.beginGesture()
    loaded.gestureMove(0.5)
    loaded.gestureMove(0.0)
    loaded.endGesture()
    assert loaded.property("undoDepth") == 0


def test_a_cancelled_drag_puts_everything_back(loaded):
    loaded.selectOnly(3)
    loaded.beginGesture()
    loaded.gestureResize(1.0)
    loaded.cancelGesture()
    assert _durations(loaded)[3] == 0.5
    assert loaded.property("undoDepth") == 0


def test_a_new_edit_discards_the_redo_history(loaded):
    loaded.selectOnly(3)
    loaded.moveBy(1.0)
    loaded.undo()
    assert loaded.property("redoDepth") == 1
    loaded.moveBy(0.5)
    assert loaded.property("redoDepth") == 0


def test_an_edit_with_nothing_selected_does_nothing(loaded):
    loaded.moveBy(1.0)
    loaded.setHand("left")
    loaded.alignStarts()
    assert loaded.property("undoDepth") == 0
    assert loaded.property("changedCount") == 0


# --- What the view asks --------------------------------------------------------

def test_note_at_finds_a_note_by_beat_and_pitch(loaded):
    assert _py(loaded.noteAt(4.2, 72)) == 3
    assert _py(loaded.noteAt(4.6, 72)) == -1      # past its end
    assert _py(loaded.noteAt(4.2, 71)) == -1


def test_note_at_follows_a_note_after_it_moves(loaded):
    loaded.selectOnly(4)
    loaded.moveBy(-5.0)                            # now before notes 2 and 3
    assert _py(loaded.noteAt(1.5, 74)) == 4
    assert _py(loaded.noteAt(6.5, 74)) == -1


def test_indices_in_range_uses_overlap_and_survives_reordering(loaded):
    assert [int(i) for i in _py(loaded.indicesInRange(1.5, 4.25))] == [0, 3]
    loaded.selectOnly(4)
    loaded.moveBy(-5.0)
    assert [int(i) for i in _py(loaded.indicesInRange(1.5, 4.25))] == [0, 3, 4]


def test_pitch_range_and_end_beat(loaded):
    assert _py(loaded.pitchRange()) == {"lo": 48, "hi": 74}
    assert _py(loaded.endBeat()) == 7.0


def test_first_from_respects_the_hand_filter(loaded):
    assert _py(loaded.firstFrom(0.0)) in (0, 1)
    loaded.setProperty("handFilter", "right")
    assert _py(loaded.firstFrom(0.0)) == 1
    assert _py(loaded.firstFrom(5.0)) == 4
    assert _py(loaded.firstFrom(50.0)) == -1


def test_is_changed_and_is_selected(loaded):
    loaded.selectOnly(3)
    loaded.moveBy(0.25)
    assert _py(loaded.isChanged(3)) is True
    assert _py(loaded.isChanged(2)) is False
    assert _py(loaded.isSelected(3)) is True
    assert _py(loaded.isSelected(2)) is False


def test_every_change_bumps_the_revision_the_view_watches(loaded):
    r0 = loaded.property("revision")
    loaded.selectOnly(3)
    r1 = loaded.property("revision")
    loaded.moveBy(0.25)
    r2 = loaded.property("revision")
    loaded.undo()
    r3 = loaded.property("revision")
    assert r0 < r1 < r2 < r3


# --- Round trip through the real save path -------------------------------------

def test_edits_save_through_the_song_library(qapp, edits, tmp_user_songs_dir):
    """Rows out of the library, edited here, go back in and land as steps."""
    from logic.services.music21_service import Music21Service

    record = {
        "id": "user::roll-1", "title": "Roll", "bpm": 100, "key_sharps": 0,
        "hand_mode": "auto",
        "time_signatures": [{"offset": 0.0, "numerator": 4, "denominator": 4}],
        "barlines": [4.0],
        "steps": [
            {"offset": 0.0, "duration": 1.0, "pitches": [48, 64],
             "hands": ["left", "right"], "durations": [1.0, 1.0],
             "fingers": [5, 1], "rests": []},
            {"offset": 0.25, "duration": 1.0, "pitches": [67],
             "hands": ["right"], "durations": [1.0], "fingers": [3], "rests": []},
            {"offset": 2.0, "duration": 1.0, "pitches": [72],
             "hands": ["right"], "durations": [1.0], "fingers": [5], "rests": []},
        ],
    }
    service = Music21Service()
    path = service.library._user_song_path("user::roll-1")
    with open(path, "w") as f:
        json.dump(record, f)

    rows = service.get_user_song_notes("user::roll-1")
    assert len(rows) == 4
    edits.load(rows, [4.0])

    # Line the spread chord up, lengthen it, and give the top note to the left hand.
    edits.selectBox(0.0, 1.0, 40, 70, False)
    edits.alignStarts()
    edits.resizeBy(1.0)
    edits.flipHand(int(_py(edits.noteAt(2.5, 72))))

    assert service.save_user_song_notes("user::roll-1", _notes(edits)) == ""

    with open(path) as f:
        saved = json.load(f)
    assert [s["offset"] for s in saved["steps"]] == [0.0, 2.0]
    chord, top = saved["steps"]
    assert chord["pitches"] == [48, 64, 67]
    assert chord["durations"] == [2.0, 2.0, 2.0]
    assert chord["fingers"] == [5, 1, 3]
    assert top["hands"] == ["left"]
    assert saved["hand_mode"] == "manual"
