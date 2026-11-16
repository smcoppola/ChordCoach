// The song editor's piano roll: time left to right, pitch bottom to top, one
// bar per note, coloured by hand.
//
// This is a view and nothing else. It owns no notes and decides nothing about
// where a note may go — every click, drag and key becomes a call on `edits`
// (NoteEdits.qml), and everything drawn here is re-read from it whenever
// `edits.revision` moves. That split is why the editing rules can be tested
// without a mouse (tests/test_note_edits.py).
//
// A song is thousands of notes, so only those overlapping the visible beat
// range (plus half a screen either side) are instantiated. One MouseArea over
// the whole surface does its own hit-testing rather than giving each note a
// MouseArea: move, resize, box-select and click then cannot fight over a press.

import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: roll

    // --- Inputs --------------------------------------------------------------
    property var edits: null        // NoteEdits
    property var geometry: null     // NotationWindow, for bar start/end beats
    property real uiScale: 1.0

    property real pixelsPerBeat: 48 * uiScale
    readonly property real minPixelsPerBeat: 10 * uiScale
    readonly property real maxPixelsPerBeat: 260 * uiScale

    readonly property color leftColor: "#2196F3"
    readonly property color rightColor: "#FF9800"
    readonly property color changedColor: "#4CAF50"

    // A press on a note that was released without dragging.
    signal noteClicked(int idx)
    signal previewNoteRequested()
    signal previewBarRequested()

    // --- Derived -------------------------------------------------------------
    readonly property int rev: edits ? edits.revision : 0
    readonly property real keyWidth: 40 * uiScale
    readonly property real rulerHeight: 20 * uiScale
    readonly property real edgeGrab: 7 * uiScale
    readonly property real dragThreshold: 4 * uiScale

    // Set by reload(): the song's own range with a little air around it, so a
    // piece that lives in three octaves is not drawn across eight.
    property int loPitch: 48
    property int hiPitch: 84
    property real songBeats: 16.0
    readonly property int rowCount: hiPitch - loPitch + 1
    // Whole pixels, so the rows stay crisp and the song's range fits the view
    // exactly when it can instead of overflowing it by a fraction.
    readonly property real rowHeight: Math.max(Math.round(8 * uiScale),
                                               Math.min(Math.round(18 * uiScale),
                                                        Math.floor((height - rulerHeight - 14 * uiScale)
                                                                   / Math.max(1, rowCount))))

    property var visibleIdx: []
    property var gridLines: []      // [{beat, kind, bar}] kind 0 bar, 1 beat, 2 sixteenth
    // The beat range the two lists above were built for.
    property real _built0: 0.0
    property real _built1: -1.0

    focus: true
    activeFocusOnTab: true

    onRevChanged: roll.refresh()
    onPixelsPerBeatChanged: roll.refresh()
    onWidthChanged: roll.refresh()

    // --- Reading a note ------------------------------------------------------
    // Guarded: for a moment during a reload the delegates still hold indices
    // into the previous song.
    function field(i, name, fallback) {
        if (!roll.edits) return fallback;
        var n = roll.edits.notes[i];
        return (n === undefined || n === null) ? fallback : n[name];
    }

    function pitchAt(y) {
        return roll.hiPitch - Math.floor(y / roll.rowHeight);
    }

    function isBlackKey(pitch) {
        var pc = ((pitch % 12) + 12) % 12;
        return pc === 1 || pc === 3 || pc === 6 || pc === 8 || pc === 10;
    }

    // --- Building what is drawn ----------------------------------------------

    // Called by the editor once `edits` holds a new song.
    function reload() {
        if (!roll.edits) return;
        var range = roll.edits.pitchRange();
        roll.loPitch = Math.max(0, range.lo - 2);
        roll.hiPitch = Math.min(127, range.hi + 2);
        roll.songBeats = 16.0;
        roll._built1 = -1.0;
        flick.contentX = 0;
        // Middle of the song's range in the middle of the view.
        flick.contentY = Math.max(0, (flick.contentHeight - flick.height) / 2);
        roll.refresh();
    }

    function _sameList(a, b) {
        if (a.length !== b.length) return false;
        for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
        return true;
    }

    function refresh() {
        if (!roll.edits || roll.width <= 0 || roll.pixelsPerBeat <= 0) return;

        // Room to drag past the end of the song. Only ever grows, so the
        // surface never shrinks under the cursor mid-edit.
        var end = roll.edits.endBeat();
        if (roll.geometry) {
            var bars = roll.edits.barlines.length + 1;
            end = Math.max(end, roll.geometry.barEndBeat(bars));
        }
        if (end + 8.0 > roll.songBeats) roll.songBeats = end + 8.0;

        var screenBeats = flick.width / roll.pixelsPerBeat;
        var b0 = flick.contentX / roll.pixelsPerBeat - screenBeats * 0.5;
        var b1 = flick.contentX / roll.pixelsPerBeat + screenBeats * 1.5;
        roll._built0 = b0;
        roll._built1 = b1;

        // Re-assigning the model rebuilds every delegate, so only do it when
        // the set of notes in view really changed — not on every nudge.
        var list = roll.edits.indicesInRange(b0, b1);
        if (!roll._sameList(list, roll.visibleIdx)) roll.visibleIdx = list;

        roll.gridLines = roll._linesBetween(Math.max(0, b0), b1);
    }

    // Scrolling only rebuilds once the view nears the edge of what was built.
    function viewMoved() {
        var left = flick.contentX / roll.pixelsPerBeat;
        var right = (flick.contentX + flick.width) / roll.pixelsPerBeat;
        var slack = (flick.width / roll.pixelsPerBeat) * 0.2;
        if (left - slack < roll._built0 || right + slack > roll._built1) roll.refresh();
    }

    function _linesBetween(b0, b1) {
        var out = [];
        if (!roll.geometry || !roll.edits) return out;
        var subs = roll.pixelsPerBeat * roll.edits.grid >= 9 * roll.uiScale;
        var m = roll.edits.measureFor(b0);
        // Bounded: a pathological metre must not spin here forever.
        for (var guard = 0; guard < 2000; guard++, m++) {
            var start = roll.geometry.barStartBeat(m);
            if (start >= b1) break;
            var stop = roll.geometry.barEndBeat(m);
            if (stop <= start) break;
            out.push({ beat: start, kind: 0, bar: m });
            var step = subs ? roll.edits.grid : 1.0;
            for (var b = start + step; b < stop - 1e-6; b += step) {
                var onBeat = Math.abs(b - start - Math.round(b - start)) < 1e-6;
                out.push({ beat: b, kind: onBeat ? 1 : 2, bar: m });
            }
        }
        return out;
    }

    // --- Moving the view -----------------------------------------------------

    function _clampX(x) {
        return Math.max(0, Math.min(x, Math.max(0, flick.contentWidth - flick.width)));
    }

    function _clampY(y) {
        return Math.max(0, Math.min(y, Math.max(0, flick.contentHeight - flick.height)));
    }

    // Puts `beat` a little in from the left edge.
    function showBeat(beat) {
        flick.contentX = roll._clampX(beat * roll.pixelsPerBeat - flick.width * 0.08);
    }

    // Scrolls only if the note is out of view, so a note you can already see
    // never jumps.
    function ensureVisible(idx) {
        if (!roll.edits || idx < 0 || idx >= roll.edits.notes.length) return;
        var n = roll.edits.notes[idx];
        var x0 = n.beat * roll.pixelsPerBeat;
        var x1 = (n.beat + n.duration) * roll.pixelsPerBeat;
        var pad = 24 * roll.uiScale;
        if (x0 < flick.contentX + pad || x1 > flick.contentX + flick.width - pad)
            flick.contentX = roll._clampX(x0 - flick.width * 0.3);
        var y0 = (roll.hiPitch - n.pitch) * roll.rowHeight;
        if (y0 < flick.contentY || y0 + roll.rowHeight > flick.contentY + flick.height)
            flick.contentY = roll._clampY(y0 - flick.height * 0.5);
    }

    // Zooms the time axis, keeping the beat under `viewX` where it is.
    function zoomBy(factor, viewX) {
        var px = (viewX === undefined) ? flick.width * 0.5 : viewX;
        var beat = (flick.contentX + px) / roll.pixelsPerBeat;
        var next = Math.max(roll.minPixelsPerBeat,
                            Math.min(roll.maxPixelsPerBeat, roll.pixelsPerBeat * factor));
        if (next === roll.pixelsPerBeat) return;
        roll.pixelsPerBeat = next;
        flick.contentX = roll._clampX(beat * next - px);
        roll.refresh();
    }

    // --- Keys ----------------------------------------------------------------
    // Every one of these has a button in the editor too; the keys are the fast
    // path, not the only path.
    Keys.onPressed: (event) => {
        if (!roll.edits) return;
        var e = roll.edits;
        var ctrl = (event.modifiers & Qt.ControlModifier) !== 0;
        var shift = (event.modifiers & Qt.ShiftModifier) !== 0;
        var alt = (event.modifiers & Qt.AltModifier) !== 0;
        var handled = true;

        if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
            var sign = (event.key === Qt.Key_Left) ? -1 : 1;
            if (alt) e.resizeBy(sign * e.grid);
            else e.moveBy(sign * (shift ? 1.0 : e.grid));
            roll.ensureVisible(e.primary);
        } else if (ctrl && event.key === Qt.Key_Z) {
            if (shift) e.redo(); else e.undo();
        } else if (ctrl && event.key === Qt.Key_Y) {
            e.redo();
        } else if (ctrl && event.key === Qt.Key_A) {
            e.selectAll();
        } else if (ctrl || alt) {
            handled = false;
        } else if (event.key === Qt.Key_L) {
            e.setHand("left");
        } else if (event.key === Qt.Key_R) {
            e.setHand("right");
        } else if (event.key === Qt.Key_A) {
            e.alignStarts();
        } else if (event.key === Qt.Key_End && shift) {
            e.extendToEnd();
        } else if ((event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace) && !shift) {
            e.deleteSelection();
        } else if (event.key === Qt.Key_Space) {
            roll.previewNoteRequested();
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            roll.previewBarRequested();
        } else if (event.key === Qt.Key_Escape && e.selectedCount > 0) {
            // First Escape lets go of the selection; with nothing selected it
            // falls through to the popup, which closes.
            e.clear();
        } else {
            handled = false;
        }
        event.accepted = handled;
    }

    // Drawn here rather than left to the Controls style: the horizontal bar is
    // always on screen, and it is how you see where in the song you are.
    component RollScrollBar : ScrollBar {
        id: bar
        padding: 2 * roll.uiScale
        minimumSize: 0.04
        contentItem: Rectangle {
            implicitWidth: 8 * roll.uiScale
            implicitHeight: 8 * roll.uiScale
            radius: 4 * roll.uiScale
            color: bar.pressed ? "#9a9a9a" : (bar.hovered ? "#7a7a7a" : "#5c5c5c")
        }
        background: Rectangle { color: "#161617" }
    }

    Rectangle {
        anchors.fill: parent
        color: "#1a1a1c"
        radius: 6 * roll.uiScale
        border.color: roll.activeFocus ? "#3a3a3a" : "#2a2a2a"
    }

    // --- Ruler: bar numbers --------------------------------------------------
    Item {
        id: ruler
        anchors.left: parent.left
        anchors.leftMargin: roll.keyWidth
        anchors.right: parent.right
        anchors.top: parent.top
        height: roll.rulerHeight
        clip: true

        Repeater {
            model: roll.gridLines
            delegate: Text {
                required property var modelData
                visible: modelData.kind === 0
                x: modelData.beat * roll.pixelsPerBeat - flick.contentX + 4 * roll.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.bar
                color: "#888888"
                font.pixelSize: 10 * roll.uiScale
                font.bold: true
            }
        }
    }

    // --- Key names down the left ---------------------------------------------
    Item {
        id: gutter
        anchors.left: parent.left
        anchors.top: ruler.bottom
        anchors.bottom: parent.bottom
        width: roll.keyWidth
        clip: true

        readonly property int primaryPitch: (roll.rev >= 0 && roll.edits && roll.edits.primary >= 0)
                                            ? roll.field(roll.edits.primary, "pitch", -1) : -1

        Repeater {
            model: roll.rowCount
            delegate: Rectangle {
                required property int index
                readonly property int pitch: roll.hiPitch - index
                readonly property bool isPrimary: pitch === gutter.primaryPitch
                y: index * roll.rowHeight - flick.contentY
                width: gutter.width - 1
                height: roll.rowHeight
                color: isPrimary ? "#4a4a4a" : (roll.isBlackKey(pitch) ? "#161617" : "#2c2c2e")

                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 4 * roll.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    // Every C, plus whichever key the selected note is on.
                    visible: parent.pitch % 12 === 0 || parent.isPrimary
                    text: parent.isPrimary ? roll.field(roll.edits.primary, "name", "")
                                           : "C" + (Math.floor(parent.pitch / 12) - 1)
                    color: parent.isPrimary ? "white" : "#888888"
                    font.pixelSize: Math.min(10 * roll.uiScale, roll.rowHeight * 0.9)
                    font.bold: parent.isPrimary
                }
            }
        }
    }

    // --- The roll ------------------------------------------------------------
    Flickable {
        id: flick
        anchors.left: gutter.right
        anchors.right: parent.right
        anchors.top: ruler.bottom
        anchors.bottom: parent.bottom
        clip: true
        // Dragging means editing here, never flicking; the wheel and the
        // scrollbars move the view.
        interactive: false
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: Math.max(width, roll.songBeats * roll.pixelsPerBeat)
        // The extra strip keeps the bottom row clear of the scrollbar.
        contentHeight: Math.max(height, roll.rowCount * roll.rowHeight + 14 * roll.uiScale)

        onContentXChanged: roll.viewMoved()

        ScrollBar.horizontal: RollScrollBar { policy: ScrollBar.AlwaysOn }
        ScrollBar.vertical: RollScrollBar { policy: ScrollBar.AsNeeded }

        // Key rows.
        Repeater {
            model: roll.rowCount
            delegate: Rectangle {
                required property int index
                readonly property int pitch: roll.hiPitch - index
                y: index * roll.rowHeight
                width: flick.contentWidth
                height: roll.rowHeight
                color: roll.isBlackKey(pitch) ? "#1e1e20" : "#252527"

                // A line under every C marks the octaves.
                Rectangle {
                    visible: parent.pitch % 12 === 0
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: "#3a3a3c"
                }
            }
        }

        // Barlines, beats and (zoomed in) sixteenths.
        Repeater {
            model: roll.gridLines
            delegate: Rectangle {
                required property var modelData
                x: modelData.beat * roll.pixelsPerBeat
                width: modelData.kind === 0 ? Math.max(1, roll.uiScale) : 1
                height: roll.rowCount * roll.rowHeight
                color: modelData.kind === 0 ? "#6a6a6a"
                     : modelData.kind === 1 ? "#3c3c3e" : "#2c2c2e"
            }
        }

        // The notes.
        Repeater {
            model: roll.visibleIdx
            delegate: Rectangle {
                id: noteItem
                required property int modelData

                // Each of these names roll.rev so it is re-read on every change:
                // a note is a plain object mutated in place and notifies nobody.
                readonly property real beat: roll.rev >= 0 ? roll.field(modelData, "beat", 0) : 0
                readonly property real duration: roll.rev >= 0 ? roll.field(modelData, "duration", 0) : 0
                readonly property int pitch: roll.rev >= 0 ? roll.field(modelData, "pitch", 0) : 0
                readonly property string hand: roll.rev >= 0 ? roll.field(modelData, "hand", "right") : "right"
                readonly property bool isSelected: roll.rev >= 0 && !!roll.edits && roll.edits.isSelected(modelData)
                readonly property bool isPrimary: roll.rev >= 0 && !!roll.edits && roll.edits.primary === modelData
                readonly property bool isChanged: roll.rev >= 0 && !!roll.edits
                                                  && modelData < roll.edits.notes.length
                                                  && roll.edits.isChanged(modelData)
                readonly property bool dimmed: roll.rev >= 0 && !!roll.edits
                                               && roll.edits.handFilter !== "all"
                                               && roll.edits.handFilter !== hand
                readonly property color base: hand === "left" ? roll.leftColor : roll.rightColor

                x: beat * roll.pixelsPerBeat
                y: (roll.hiPitch - pitch) * roll.rowHeight + 1
                // The one-pixel gap keeps repeated notes on a key readable as
                // separate notes.
                width: Math.max(3 * roll.uiScale, duration * roll.pixelsPerBeat - 1)
                height: Math.max(3, roll.rowHeight - 2)
                radius: Math.min(3 * roll.uiScale, height / 2)
                z: isSelected ? 2 : 1
                opacity: dimmed ? 0.22 : 1.0
                color: isSelected ? Qt.lighter(base, 1.25) : base
                border.width: isSelected ? Math.max(2, 2 * roll.uiScale) : (isChanged ? Math.max(1, roll.uiScale) : 0)
                border.color: isSelected ? "white" : roll.changedColor

                // A changed note keeps a green mark even while selected, when
                // its outline is white.
                Rectangle {
                    visible: noteItem.isChanged && noteItem.isSelected
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.margins: parent.border.width
                    width: Math.max(2, 3 * roll.uiScale)
                    color: roll.changedColor
                }
            }
        }

        // The rubber band.
        Rectangle {
            id: band
            visible: false
            z: 5
            color: Qt.rgba(1, 1, 1, 0.08)
            border.color: "#bbbbbb"
        }

        MouseArea {
            id: mouse
            width: flick.contentWidth
            height: flick.contentHeight
            z: 10
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            hoverEnabled: true
            preventStealing: true

            property string mode: ""        // "move", "resize", "box" or ""
            property int pressIdx: -1
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            property bool additive: false
            property int lastSteps: 0

            function noteUnder(x, y) {
                return roll.edits ? roll.edits.noteAt(x / roll.pixelsPerBeat, roll.pitchAt(y)) : -1;
            }

            // True when x is on the right-hand end of note `idx`: the grab zone
            // for changing its length. Never more than a third of the note, so
            // a short note can still be picked up and moved.
            function onRightEdge(idx, x) {
                var n = roll.edits.notes[idx];
                var w = n.duration * roll.pixelsPerBeat;
                var fromEnd = (n.beat + n.duration) * roll.pixelsPerBeat - x;
                return fromEnd <= Math.min(roll.edgeGrab, w / 3);
            }

            onPressed: (ev) => {
                roll.forceActiveFocus();
                if (!roll.edits) return;
                var e = roll.edits;
                var idx = mouse.noteUnder(ev.x, ev.y);
                mouse.pressIdx = idx;
                mouse.pressX = ev.x;
                mouse.pressY = ev.y;
                mouse.moved = false;
                mouse.lastSteps = 0;
                mouse.mode = "";

                if (ev.button === Qt.RightButton) {
                    if (idx >= 0) {
                        if (!e.isSelected(idx)) e.selectOnly(idx);
                        e.flipHand(idx);
                    }
                    return;
                }

                mouse.additive = (ev.modifiers & (Qt.ControlModifier | Qt.ShiftModifier)) !== 0;
                if (idx < 0) {
                    mouse.mode = "box";
                    return;
                }
                if (mouse.additive) {
                    e.toggle(idx);
                    return;
                }
                // Pressing a note already in the selection keeps the selection,
                // so a group can be picked up by any of its notes.
                if (e.isSelected(idx)) e.setPrimary(idx);
                else e.selectOnly(idx);
                mouse.mode = mouse.onRightEdge(idx, ev.x) ? "resize" : "move";
                e.beginGesture();
            }

            onPositionChanged: (ev) => {
                if (!roll.edits) return;
                if (!mouse.pressed) {
                    var over = mouse.noteUnder(ev.x, ev.y);
                    mouse.cursorShape = over < 0 ? Qt.ArrowCursor
                                      : (mouse.onRightEdge(over, ev.x) ? Qt.SizeHorCursor
                                                                       : Qt.PointingHandCursor);
                    return;
                }
                if (mouse.mode === "") return;

                var dx = ev.x - mouse.pressX;
                var dy = ev.y - mouse.pressY;
                // A click always wobbles a pixel or two; without this, selecting
                // a note at high zoom would also nudge it.
                if (!mouse.moved && Math.abs(dx) < roll.dragThreshold
                        && Math.abs(dy) < roll.dragThreshold)
                    return;
                mouse.moved = true;

                if (mouse.mode === "box") {
                    band.x = Math.min(mouse.pressX, ev.x);
                    band.y = Math.min(mouse.pressY, ev.y);
                    band.width = Math.abs(dx);
                    band.height = Math.abs(dy);
                    band.visible = true;
                    return;
                }

                // Only on crossing a grid line: a drag fires far more often
                // than the result can change.
                var steps = Math.round(dx / roll.pixelsPerBeat / roll.edits.grid);
                if (steps === mouse.lastSteps) return;
                mouse.lastSteps = steps;
                if (mouse.mode === "move") roll.edits.gestureMove(steps * roll.edits.grid);
                else roll.edits.gestureResize(steps * roll.edits.grid);
            }

            onReleased: (ev) => {
                if (!roll.edits) return;
                var e = roll.edits;
                if (mouse.mode === "move" || mouse.mode === "resize") {
                    e.endGesture();
                    if (!mouse.moved && mouse.pressIdx >= 0) roll.noteClicked(mouse.pressIdx);
                } else if (mouse.mode === "box") {
                    band.visible = false;
                    if (mouse.moved) {
                        e.selectBox(mouse.pressX / roll.pixelsPerBeat, ev.x / roll.pixelsPerBeat,
                                    roll.pitchAt(mouse.pressY), roll.pitchAt(ev.y), mouse.additive);
                    } else if (!mouse.additive) {
                        e.clear();
                    }
                }
                mouse.mode = "";
            }

            onCanceled: {
                band.visible = false;
                if (roll.edits) roll.edits.cancelGesture();
                mouse.mode = "";
            }

            // The second press of a double-click has already begun a move; drop
            // it so the flip is the only thing recorded.
            onDoubleClicked: (ev) => {
                if (!roll.edits || ev.button !== Qt.LeftButton) return;
                var idx = mouse.noteUnder(ev.x, ev.y);
                if (idx < 0) return;
                roll.edits.cancelGesture();
                mouse.mode = "";
                roll.edits.flipHand(idx);
            }

            onWheel: (wheel) => {
                var d = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.angleDelta.x;
                if (wheel.modifiers & Qt.ControlModifier) {
                    roll.zoomBy(d > 0 ? 1.25 : 0.8, wheel.x - flick.contentX);
                } else if (wheel.modifiers & Qt.ShiftModifier) {
                    flick.contentY = roll._clampY(flick.contentY - d);
                } else {
                    // Time is the axis that matters here, so the plain wheel
                    // travels through the song.
                    flick.contentX = roll._clampX(flick.contentX - d);
                }
                wheel.accepted = true;
            }
        }
    }
}
