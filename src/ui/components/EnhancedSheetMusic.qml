// Unversioned QtQuick import: FrameAnimation, which ScrollClock is built on,
// arrived in Qt 6.4 and is not reachable through the QtQuick 2.x version scheme.
import QtQuick
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
import ChordCoach 1.0

Rectangle {
    id: root
    color: "#fcfcfc" // Light, clean paper color
    clip: true
    Layout.fillWidth: true
    Layout.fillHeight: true

    property int middleC: 60
    property string targetChordName: ""
    onTargetChordNameChanged: {
        var d = new Date();
        var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
        console.log("[TIMING " + timeStr + "] QML EnhancedSheetMusic updated target: " + targetChordName);
    }
    
    // Evaluation / scrolling mode properties (generic - reusable for MIDI playback)
    property string displayMode: "trainer"  // "trainer" or "evaluation"
    property var evalNotes: []               // Array of {pitch, start_beat, duration_beats, hand}

    // Evaluation playhead. Same two regimes as scrollBeat: an anchor drives it
    // when the onboarding clock is running, otherwise the raw value is used.
    property var evalAnchor: null
    property real evalSteppedBeat: 0
    property bool evalClockDriven: evalAnchor ? evalAnchor.active === true : false
    property real evalBeat: evalClockDriven ? evalClock.beat : evalSteppedBeat

    property real loopStartBeat: -1.0
    property real loopEndBeat: -1.0
    property var evalNoteStates: []          // Array of "pending"/"hit"/"miss"
    property real pixelsPerBeat: width * 0.10
    
    // Geometry Constants for Grand Staff mapping.
    // These MIRROR STAFF_SPACE_RATIO / STAFF_SEPARATION_SPACES in notation_view.py,
    // which is what actually paints the staff. They exist here only so the QML
    // overlays below (playhead, tap-to-seek, pedal marking) can line up with the
    // painted ink — change them in both places or the overlays desync.
    // s = 5.25% of height; staves sit 8 staff spaces apart, centred on the pane.
    property real lineSpacing: height * 0.0525
    property real trebleCenterY: (height * 0.5) - (lineSpacing * 4.0)
    property real bassCenterY: (height * 0.5) + (lineSpacing * 4.0)
    // Note Start Position (Aligned with native NotationView)
    property real noteStartX: width * 0.28

    // Replace the existing notationStyle property with this direct binding
    property string notationStyle: appState ? appState.settingsService.notationStyle.toLowerCase() : "enhanced"

    // Do the same for color mode
    property string notationColorMode: appState ? appState.settingsService.notationColorMode.toLowerCase() : "pedagogical"

    property bool useMonochrome: notationColorMode === "monochrome"
    property string musicFont: "Bravura"
    
    function formatChordTitle(name) {
        if (!name) return "";
        // 1. Replace accidentally trailing/spaced sharps and flats
        var formatted = name.replace(/#/g, " Sharp").replace(/b( |$)/g, " Flat$1");
        
        // 2. Handle Major/Minor abbreviations for standard notation above the staff
        // "A Major" -> "A" (standard convention is to omit "Major" for triads)
        formatted = formatted.replace(/\bMajor\b/gi, "");
        // "A Minor" -> "Am"
        formatted = formatted.replace(/\bMinor\b/gi, "m");
        
        // 3. Clean up any accidental double spaces left behind
        return formatted.trim().replace(/\s+/g, ' ');
    }

    // Connect to global state to get active target pitches and sort them low-to-high
    // so the Repeater draws them back-to-front, guaranteeing higher pitches (and their staggered text)
    // always render on top of lower pitches.
    property string exerciseType: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.exerciseType || "chord";
        }
        return "chord";
    }
    property int currentNoteIndex: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.currentNoteIndex || 0;
        }
        return 0;
    }
    property var allPentascaleNotes: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer && appState.chordTrainer.pentascaleNotes) {
            return appState.chordTrainer.pentascaleNotes.slice().sort(function(a, b){return a-b});
        }
        return [];
    }
    property var activeTargets: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer && appState.chordTrainer.targetPitches) {
            var pitches = appState.chordTrainer.targetPitches;
            var hands = appState.chordTrainer.targetHands;
            var fingers = appState.chordTrainer.targetFingers;
            var idx = appState.chordTrainer.currentNoteIndex || 0;
            var seq = appState.chordTrainer.pentascaleNotes;

            if (exerciseType === "pentascale" && seq) {
                // In pentascale mode, only show the current note as the active target
                if (idx < seq.length) {
                    var p = seq[idx];
                    // Service now sends only the CURRENT finger as a length-1 array
                    var f = (fingers && fingers.length > 0) ? fingers[0] : (idx + 1);
                    return [{ pitch: p, hand: currentHand, finger: f }];
                }
                return [];
            }
            
            // For chords/progressions, combine parallel arrays into objects for sorting
            var combined = [];
            for (var i = 0; i < pitches.length; i++) {
                combined.push({
                    pitch: pitches[i],
                    hand: (hands && i < hands.length) ? hands[i] : currentHand,
                    finger: (fingers && i < fingers.length) ? fingers[i] : 0
                });
            }
            // Sort low-to-high by pitch so Reaper draws back-to-front
            return combined.sort(function(a, b){ return a.pitch - b.pitch });
        }
        return [];
    }
    property string currentHand: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.currentHand || "right";
        }
        return "right";
    }
    
    property string pedalType: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.pedalType || "";
        }
        return "";
    }

    // The playhead position, from whichever of the two regimes is driving.
    //
    // A clocked transport (piece playback, rhythm mode, the metronome) publishes
    // an anchor and scrollClock extrapolates it on the display's frame clock —
    // uniform velocity, one update per frame, no easing.
    //
    // Self-paced play has no clock: the playhead jumps a step at a time as the
    // user plays, so it goes through steppedBeat and keeps the 150 ms ease that
    // makes each jump readable. Easing the clocked regime is what made it
    // judder, so the two must not share a path.
    property real steppedBeat: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.scrollBeat || 0.0;
        }
        return 0.0;
    }

    property var scrollAnchor: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.scrollAnchor || null;
        }
        return null;
    }

    // Set by a parent that owns a different transport (ChordTrainerView routes
    // piece playback in here), overriding the chordTrainer anchor.
    property var scrollAnchorOverride: null
    property var activeAnchor: scrollAnchorOverride ? scrollAnchorOverride : scrollAnchor
    property bool clockDriven: activeAnchor ? activeAnchor.active === true : false

    property real scrollBeat: clockDriven ? scrollClock.beat : steppedBeat

    // The two frame-locked playhead clocks. Each runs only while its own
    // transport is active, so neither keeps the render loop awake otherwise.
    ScrollClock {
        id: scrollClock
        anchor: root.activeAnchor
        active: root.clockDriven
    }

    ScrollClock {
        id: evalClock
        anchor: root.evalAnchor
        active: root.evalClockDriven
    }

    property var scrollingNotes: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.scrollingNotes || [];
        }
        return [];
    }

    property int scrollBpm: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.scrollBpm || 0;
        }
        return 0;
    }

    property string songTitle: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.songTitle || "";
        }
        return "";
    }

    property string songKey: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.songKey || "";
        }
        return "";
    }

    property int songKeySharps: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.songKeySharps || 0;
        }
        return 0;
    }

    // Eases the discrete step-to-step jumps of self-paced play. Deliberately NOT
    // on scrollBeat: a Behavior retargeted before it finishes restarts its
    // easing curve, so against a continuously moving playhead it produced a
    // sawtooth velocity — the judder this whole path exists to avoid — plus
    // 150 ms of lag behind the audio.
    Behavior on steppedBeat { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }

    property bool isScrollingMode: {
        return (exerciseType === "pentascale" || exerciseType === "steady_pulse" || exerciseType === "progression" || exerciseType === "song_application");
    }
    
    function getHandForTargetPitch(pitch) {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            var pitches = appState.chordTrainer.targetPitches;
            var hands = appState.chordTrainer.targetHands;
            if (pitches && hands) {
                for (var i = 0; i < pitches.length; i++) {
                    if (pitches[i] === pitch) return hands[i];
                }
            }
        }
        return currentHand;
    }


    // 1. Draw the Staff Title
    Text {
        anchors.top: parent.top
        // Tight against the top edge: the taller staff space raises the treble
        // staff, so this margin is now ledger-line headroom.
        anchors.topMargin: 8 * mainWindow.uiScale
        anchors.horizontalCenter: parent.horizontalCenter
        width: parent.width * 0.9
        text: {
            if (root.exerciseType === "song_application" && root.songTitle !== "") {
                return root.songTitle + (root.songKey !== "" ? (" — " + root.songKey) : "");
            }
            return root.formatChordTitle(root.targetChordName);
        }
        font.pixelSize: (root.exerciseType === "song_application") ? (24 * mainWindow.uiScale) : (32 * mainWindow.uiScale)
        font.bold: true
        color: "#333333"
        visible: text !== "" && root.exerciseType !== "song_application"
        z: 20
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
    }

    // 2. Draw the Grand Staff and ALL Notes using the native Rendering Engine
    NotationView {
        id: nativeNotation
        anchors.fill: parent
        z: 0

        notationStyle: root.notationStyle
        notationColorMode: root.notationColorMode
        displayMode: root.displayMode
        isScrollingMode: root.isScrollingMode

        // Data payloads
        targetPitches: root.activeTargets
        evalNotes: root.evalNotes
        scrollingNotes: root.scrollingNotes
        evalNoteStates: root.evalNoteStates
        songKeySharps: root.songKeySharps
        
        // Synchronization
        scrollBeat: root.scrollBeat
        evalBeat: root.evalBeat
        loopStartBeat: root.loopStartBeat
        loopEndBeat: root.loopEndBeat
    }

    // 2.5 Tap-to-Seek Mouse Area (active during piece playback)
    MouseArea {
        id: tapToSeekArea
        anchors.fill: parent
        z: 500
        enabled: typeof appState !== "undefined" && appState !== null && appState.playback && appState.playback.isPlaying
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor

        onClicked: (mouse) => {
            if (appState && appState.playback) {
                var currentBeat = appState.playback.playbackBeat;
                var clickBeat = currentBeat + (mouse.x - root.noteStartX) / root.pixelsPerBeat;
                if (clickBeat >= 0) {
                    appState.playback.seek(clickBeat);
                }
            }
        }
    }

    // 3. Playhead Line (Green) — remains for scrolling/evaluation modes
    Rectangle {
        id: playheadLine
        x: {
            if (root.displayMode === "evaluation") return root.noteStartX;
            if (root.isScrollingMode) return root.noteStartX;
            if (root.exerciseType === "pentascale") {
                return root.noteStartX + (root.currentNoteIndex * (parent.width - root.noteStartX - 40) / (root.allPentascaleNotes.length || 1)) - (6 * mainWindow.uiScale);
            }
            return root.noteStartX - (100 * mainWindow.uiScale);
        }
        y: parent.height * 0.1
        width: Math.max(1, 1.8 * mainWindow.uiScale)
        height: parent.height * 0.8
        visible: root.displayMode === "evaluation" || root.isScrollingMode
        color: "#4CAF50"
        radius: width / 2
        z: 1000
        
        Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
    }

    // 3.5 Sustain Pedal Notation
    Item {
        anchors.left: parent.left
        anchors.leftMargin: root.noteStartX - (20 * mainWindow.uiScale)
        anchors.right: parent.right
        // 0.6 spaces below the bottom staff line. Was 3.5 spaces from the
        // centre, which at the current staff space runs off the pane bottom.
        y: root.bassCenterY + (root.lineSpacing * 2.6)
        height: root.lineSpacing * 2
        visible: root.displayMode === "trainer" && root.exerciseType === "sustain_pedal"
        
        Text {
            id: pedText
            text: "Ped."
            font.pixelSize: root.lineSpacing * 1.5
            font.italic: true
            font.bold: true
            font.family: "Times New Roman"
            color: "#111111"
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
        }
        
        Text {
            visible: root.pedalType === "direct"
            text: "*"
            font.pixelSize: root.lineSpacing * 2
            font.family: "Times New Roman"
            color: "#111111"
            anchors.left: pedText.right
            anchors.leftMargin: 150 * mainWindow.uiScale
            anchors.verticalCenter: parent.verticalCenter
        }
        
        // Legato Bracket
        Item {
            visible: root.pedalType === "legato"
            anchors.left: pedText.right
            anchors.leftMargin: 10 * mainWindow.uiScale
            anchors.verticalCenter: parent.verticalCenter
            width: 156 * mainWindow.uiScale
            height: 10 * mainWindow.uiScale
            
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 2 * mainWindow.uiScale
                color: "#111111"
            }
            Rectangle {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                width: 2 * mainWindow.uiScale
                height: parent.height
                color: "#111111"
            }
        }
    }
}
