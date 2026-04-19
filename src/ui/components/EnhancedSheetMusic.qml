import QtQuick 2.15
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
    property real evalBeat: 0                // Current beat position from service
    property var evalNoteStates: []          // Array of "pending"/"hit"/"miss"
    property real pixelsPerBeat: width * 0.10
    
    // Geometry Constants for Grand Staff mapping (inherited by native engine)
    // Professional screen-reading proportion: s = 3.5% of height, Treble at 35%, Bass at 65%
    property real lineSpacing: height * 0.035
    property real trebleCenterY: height * 0.35
    property real bassCenterY: height * 0.65
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

    property real scrollBeat: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.scrollBeat || 0.0;
        }
        return 0.0;
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

    // ADDED: Interpolators to catch backend property snaps and force smooth sliding
    Behavior on scrollBeat { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
    Behavior on evalBeat { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }

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
        anchors.topMargin: 20 * mainWindow.uiScale
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
        y: root.bassCenterY + (root.lineSpacing * 3.5)
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
