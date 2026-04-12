import QtQuick 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects

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
    
    // Evaluation / scrolling mode properties (generic — reusable for MIDI playback)
    property string displayMode: "trainer"  // "trainer" or "evaluation"
    property var evalNotes: []               // Array of {pitch, start_beat, duration_beats, hand}
    property real evalBeat: 0                // Current beat position from service
    property var evalNoteStates: []          // Array of "pending"/"hit"/"miss"
    property real pixelsPerBeat: width * 0.10

    property string notationStyle: {
        if (typeof appState !== "undefined" && appState && appState.settingsService) {
            return appState.settingsService.notationStyle || "enhanced";
        }
        return "enhanced";
    }

    property string notationColorMode: {
        if (typeof appState !== "undefined" && appState && appState.settingsService) {
            return appState.settingsService.notationColorMode || "pedagogical";
        }
        return "pedagogical";
    }

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
    
    // Hardcode the pitch colors (matches midi_ingestor.py and VisualKeyboard needs)
    
    function getColorForFinger(finger) {
        if (!finger) return "#888888";
        if (useMonochrome) return "#111111"; // Global monochrome override
        // User-Specified pedagogical color mapping:
        // 1=Green, 2=Yellow (Deepened for contrast), 3=Purple, 4=Blue, 5=Red
        var colors = {
            1: "#4CAF50",
            2: "#FFB300", // "Amber" instead of bright yellow for white text contrast
            3: "#9C27B0",
            4: "#2196F3",
            5: "#F44336"
        };
        return colors[finger] || "#888888";
    }

    function getTextColorForFinger(finger) {
        // Uniform white text per user request
        return "#ffffff";
    }

    function getNoteName(pitch) {
        var names = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];
        var name = names[pitch % 12];
        // If traditional mode, we only want the letter here; accidental is drawn separately
        if (root.notationStyle === "traditional") return name.charAt(0);
        return name;
    }

    function getAccidentalSymbol(pitch) {
        var note = pitch % 12;
        // Correct accidentals: C=0, C#=1, D=2, Eb=3, E=4, F=5, F#=6, G=7, Ab=8, A=9, Bb=10, B=11
        if (note === 1 || note === 6 || note === 8 || note === 10 || note === 3) {
            // Check for sharps (1, 6) vs flats (3, 8, 10)
            if (notationStyle === "traditional") {
                if (note === 1 || note === 6) return "\uE262"; // Bravura Sharp
                return "\uE260"; // Bravura Flat
            }
            if (note === 1 || note === 6) return "♯";
            return "♭";
        }
        return "";
    }
    
    function getDiatonicStepsDifference(basePitch, targetPitch) {
        var diatonicValues = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6];
        var baseOctave = Math.floor(basePitch / 12);
        var baseNote = diatonicValues[basePitch % 12];
        var baseAbsolute = (baseOctave * 7) + baseNote;

        var targetOctave = Math.floor(targetPitch / 12);
        var targetNote = diatonicValues[targetPitch % 12];
        var targetAbsolute = (targetOctave * 7) + targetNote;

        return targetAbsolute - baseAbsolute;
    }

    function getLedgerSteps(steps) {
        var lines = [];
        if (steps >= 6) {
            for (var s = 6; s <= steps; s += 2) lines.push(s);
        } else if (steps <= -6) {
            for (var s = -6; s >= steps; s -= 2) lines.push(s);
        }
        return lines;
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

    // 1. Draw the Grand Staff Background & Lines
    Item {
        id: staffBackground
        anchors.fill: parent
        
        property real lineSpacing: height * 0.05
        property real trebleCenterY: height * 0.35
        property real bassCenterY: height * 0.75
        property real noteStartX: parent.width * 0.33
        
        // Pentascale staggered layout properties
        property int pentaNoteCount: root.allPentascaleNotes.length || 1
        property real pentaNoteWidth: Math.min(120, (width - noteStartX - 40) / pentaNoteCount * 0.85)
        property real pentaNoteSpacing: (width - noteStartX - 40) / pentaNoteCount
        
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

        // Treble Clef (5 lines)
        Repeater {
            model: 5
            Rectangle {
                width: parent.width
                height: Math.max(1, 1.5 * mainWindow.uiScale)
                color: "#999999" // Darkened staff lines for engraving feel
                y: staffBackground.trebleCenterY - ((4 - (index * 2)) * (staffBackground.lineSpacing / 2))
            }
        }
        
        // Bass Clef (5 lines)
        Repeater {
            model: 5
            Rectangle {
                width: parent.width
                height: Math.max(1, 1.5 * mainWindow.uiScale)
                color: "#999999" // Darkened staff lines for engraving feel
                y: staffBackground.bassCenterY - ((4 - (index * 2)) * (staffBackground.lineSpacing / 2))
            }
        }
        
        // Treble Clef Symbol
        Text {
            text: root.notationStyle === "traditional" ? "\uE050" : "𝄞"
            font.family: root.notationStyle === "traditional" ? root.musicFont : "serif"
            font.pixelSize: staffBackground.lineSpacing * (root.notationStyle === "traditional" ? 4.5 : 6)
            color: "#111111"
            x: 40 * mainWindow.uiScale
            anchors.verticalCenter: parent.top
            anchors.verticalCenterOffset: staffBackground.trebleCenterY + (staffBackground.lineSpacing * 0.5)
        }
        
        // Bass Clef Symbol
        Text {
            text: root.notationStyle === "traditional" ? "\uE062" : "𝄢"
            font.family: root.notationStyle === "traditional" ? root.musicFont : "serif"
            font.pixelSize: staffBackground.lineSpacing * (root.notationStyle === "traditional" ? 3.5 : 4.5)
            color: "#111111"
            x: 40 * mainWindow.uiScale
            anchors.verticalCenter: parent.top
            anchors.verticalCenterOffset: staffBackground.bassCenterY - (staffBackground.lineSpacing * 0.5)
        }
        
        // Vertical Barline — marks the staff start
        Rectangle {
            x: staffBackground.noteStartX
            y: staffBackground.trebleCenterY - (staffBackground.lineSpacing * 2)
            width: Math.max(1, 1.5 * mainWindow.uiScale) // Match staff line weight
            height: (staffBackground.bassCenterY + (staffBackground.lineSpacing * 2)) - y
            color: "#111111"
            // Hide during scrolling lessons to avoid clashing with the green playhead
            visible: !root.isScrollingMode && root.displayMode !== "evaluation"
        }
        
        // Playhead Line (Green) — tracks current note in pentascale mode
        Rectangle {
            x: root.displayMode === "evaluation" ? staffBackground.noteStartX :
               root.isScrollingMode ? staffBackground.noteStartX :
               root.exerciseType === "pentascale"
                ? staffBackground.noteStartX + (root.currentNoteIndex * staffBackground.pentaNoteSpacing) - (6 * mainWindow.uiScale)
                : staffBackground.noteStartX - (100 * mainWindow.uiScale)
            y: staffBackground.trebleCenterY - (staffBackground.lineSpacing * 3.1)
            width: Math.max(1, 1.8 * mainWindow.uiScale) // Thinner playhead
            height: (staffBackground.bassCenterY + (staffBackground.lineSpacing * 3.1)) - y
            visible: root.displayMode === "evaluation" || root.isScrollingMode
            color: "#4CAF50"
            radius: width / 2
            z: 1000
            
            Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
            
            // Playhead dots
            Rectangle {
                width: 16 * mainWindow.uiScale
                height: 16 * mainWindow.uiScale
                radius: 8 * mainWindow.uiScale
                color: "#ffffff"
                border.color: "#cccccc"
                anchors.horizontalCenter: parent.horizontalCenter
                y: (staffBackground.trebleCenterY - parent.y) - (8 * mainWindow.uiScale)
            }
            Rectangle {
                width: 16 * mainWindow.uiScale
                height: 16 * mainWindow.uiScale
                radius: 8 * mainWindow.uiScale
                color: "#ffffff"
                border.color: "#cccccc"
                anchors.horizontalCenter: parent.horizontalCenter
                y: (staffBackground.bassCenterY - parent.y) - (8 * mainWindow.uiScale)
            }
        }
        
        // 2. Draw the Notes (active targets)
        Repeater {
            model: root.activeTargets
            
            Item {
                id: noteContainer
                visible: root.displayMode === "trainer" && !root.isScrollingMode
                property int pitch: modelData.pitch
                property int finger: modelData.finger
                property string hand: modelData.hand
                property bool isTreble: {
                    return hand === "left" ? false : hand === "right" ? true : pitch >= 60;
                }
                property int referencePitch: isTreble ? 71 : 50 // B4 or D3
                property real referenceY: isTreble ? staffBackground.trebleCenterY : staffBackground.bassCenterY
                property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)
                
                // Determine if this note needs to stagger because it's occluding the note right below it
                property bool isStaggeredRight: {
                    if (root.exerciseType === "pentascale") return false; // pentascale uses horizontal layout
                    if (index === 0) return false;
                    var prevPitch = root.activeTargets[index - 1].pitch;
                    var stepDiff = root.getDiatonicStepsDifference(prevPitch, pitch);
                    return stepDiff < 2;
                }
                property real staggerOffset: {
                    if (isStaggeredRight) {
                        return (root.notationStyle === "traditional" ? (staffBackground.lineSpacing * 1.1) : (30 * mainWindow.uiScale));
                    }
                    return 0;
                }
                
                // In pentascale mode, position by sequence index; otherwise use full-width bar
                property bool isPentascale: root.exerciseType === "pentascale"
                property int pentaIdx: root.currentNoteIndex
                
                y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                z: isPentascale ? 200 : pitch
                
                x: isPentascale
                    ? staffBackground.noteStartX + (pentaIdx * staffBackground.pentaNoteSpacing)
                    : staffBackground.noteStartX + staggerOffset
                width: isPentascale
                    ? staffBackground.pentaNoteWidth
                    : (root.notationStyle === "traditional" ? staffBackground.lineSpacing * 1.1 : noteContainer.parent.width - x)
                height: staffBackground.lineSpacing * 0.72
                
                // --- TRADITIONAL BRAVURA HEAD ---
                Text {
                    id: headGlyph
                    visible: root.notationStyle === "traditional"
                    text: "\uE0A4" // Notehead Black
                    font.family: root.musicFont
                    font.pixelSize: staffBackground.lineSpacing * 2.8
                    color: root.getColorForFinger(finger)
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -staffBackground.lineSpacing * 0.05
                    z: 10
                }

                // --- ENHANCED CAPSULE ---
                Rectangle {
                    visible: root.notationStyle === "enhanced"
                    anchors.fill: parent
                    color: root.getColorForFinger(finger)
                    radius: height / 2
                    
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10 * mainWindow.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.getNoteName(pitch)
                        color: root.getTextColorForFinger(finger)
                        font.pixelSize: parent.height * 0.65
                        font.bold: true
                    }
                }
                
                // --- Accidental for Traditional ---
                Text {
                    visible: root.notationStyle === "traditional" && root.getAccidentalSymbol(pitch) !== ""
                    text: root.getAccidentalSymbol(pitch)
                    font.family: root.musicFont
                    color: "#111111"
                    font.pixelSize: staffBackground.lineSpacing * 2.5
                    anchors.right: parent.left
                    anchors.rightMargin: 2 * mainWindow.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                }
                
                // --- STANDARD HAND STEM ---
                Rectangle {
                    id: noteStem
                    width: Math.max(1, 1.2 * mainWindow.uiScale)
                    height: staffBackground.lineSpacing * 3.4 // Professional length (3.5 spaces)
                    color: "#111111" // Standard black
                    
                    // Logic: Traditional mode uses the "Middle Line" rule for standard engraving.
                    // Enhanced mode/Trainer uses Hand-based stems.
                    property bool stemUp: {
                        if (root.notationStyle === "traditional") {
                            // Middle Line Rule: If pitch is below Middle line (B4=71, D3=50), stem is UP.
                            // Otherwise, stem is DOWN.
                            return noteContainer.isTreble ? noteContainer.pitch < 71 : noteContainer.pitch < 50;
                        }
                        return (noteContainer.hand === "right" || noteContainer.hand === "R");
                    }
                    
                    // For Bravura head, we need to offset the stem slightly to touch the side of the glyph
                    // Note: Bravura Notehead Black (\uE0A4) is slightly wider than the line spacing.
                    property real xOffset: staffBackground.lineSpacing * 0.49
                    
                    anchors.bottom: stemUp ? parent.verticalCenter : undefined
                    anchors.top: !stemUp ? parent.verticalCenter : undefined
                    
                    x: stemUp ? (parent.width / 2 + xOffset) : (parent.width / 2 - xOffset)
                    
                    z: 5
                    visible: root.notationStyle === "traditional"
                }
                
                Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                
                // Signal connection triggers animation
                Connections {
                    target: (typeof appState !== "undefined" && appState !== null) ? appState.chordTrainer : null
                    function onInputReady() {
                        if (noteContainer.visible) {
                            readyScaleAnim.restart();
                            readyGlowAnim.restart();
                        }
                    }
                }
                
                SequentialAnimation on scale {
                    id: readyScaleAnim
                    running: false
                    NumberAnimation { to: 1.15; duration: 100; easing.type: Easing.OutQuad }
                    NumberAnimation { to: 1.0; duration: 250; easing.type: Easing.InQuad }
                }
                
                Rectangle {
                    anchors.fill: parent
                    color: "#ffffff"
                    opacity: 0.0
                    radius: 10 * mainWindow.uiScale
                    z: 10
                    
                    SequentialAnimation on opacity {
                        id: readyGlowAnim
                        running: false
                        NumberAnimation { to: 0.6; duration: 100; easing.type: Easing.OutQuad }
                        NumberAnimation { to: 0.0; duration: 350; easing.type: Easing.InQuad }
                    }
                }
                
                // Ledger lines if note is outside the staff
                Repeater {
                    model: root.getLedgerSteps(noteContainer.steps)
                    Rectangle {
                        z: -10 // Strictly behind the note
                        anchors.left: parent.left
                        anchors.leftMargin: -8 * mainWindow.uiScale
                        width: noteContainer.width + (16 * mainWindow.uiScale)
                        height: Math.max(1, 1.5 * mainWindow.uiScale) // Standard staff weight
                        color: "#111111" // Pure black for clarity
                        y: ((noteContainer.steps - modelData) * (staffBackground.lineSpacing / 2)) + (noteContainer.height / 2) - (height / 2)
                    }
                }
            }
        }
        
        Repeater {
            model: (root.displayMode === "trainer" && root.exerciseType === "pentascale") ? root.allPentascaleNotes : []
            
            Item {
                id: guideNoteItem
                property int pitch: modelData
                property bool isTreble: {
                    var h = root.getHandForTargetPitch(pitch);
                    return h === "left" ? false : h === "right" ? true : pitch >= 60;
                }
                property int referencePitch: isTreble ? 71 : 50
                property real referenceY: isTreble ? staffBackground.trebleCenterY : staffBackground.bassCenterY
                property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)
                
                // Position notes staggered horizontally in trainer mode (non-scrolling)
                property int noteIdx: {
                    if (typeof appState !== "undefined" && appState && appState.chordTrainer && appState.chordTrainer.pentascaleNotes) {
                        var seq = appState.chordTrainer.pentascaleNotes;
                        for (var i = 0; i < seq.length; i++) {
                            if (seq[i] === pitch) return i;
                        }
                    }
                    return -1;
                }
                property bool isCompleted: noteIdx < root.currentNoteIndex
                property bool isCurrent: noteIdx === root.currentNoteIndex
                property int finger: noteIdx + 1
                property string fingerColor: root.getColorForFinger(finger)
                
                // Don't draw the current note here — it's drawn by the activeTargets repeater
                visible: !isCurrent && !root.isScrollingMode
                
                y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                z: 100 + pitch
                
                // Stagger horizontally by sequence position
                x: staffBackground.noteStartX + (noteIdx * staffBackground.pentaNoteSpacing)
                width: root.notationStyle === "traditional" ? (staffBackground.lineSpacing * 1.1) : staffBackground.pentaNoteWidth
                height: staffBackground.lineSpacing * 0.72
                
                // --- TRADITIONAL BRAVURA HEAD (GUIDE) ---
                Text {
                    id: guideHead
                    visible: root.notationStyle === "traditional"
                    text: "\uE0A4"
                    font.family: root.musicFont
                    font.pixelSize: staffBackground.lineSpacing * 2.8
                    color: guideNoteItem.isCompleted ? (root.useMonochrome ? "#111111" : fingerColor) : "transparent"
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -staffBackground.lineSpacing * 0.05
                    opacity: guideNoteItem.isCompleted ? 0.9 : 0.4
                }

                // --- ENHANCED CAPSULE (GUIDE) ---
                Rectangle {
                    id: guideCapsule
                    visible: root.notationStyle === "enhanced"
                    anchors.fill: parent
                    color: guideNoteItem.isCompleted ? (root.useMonochrome ? "#111111" : fingerColor) : "transparent"
                    border.color: root.useMonochrome ? "#111111" : fingerColor
                    border.width: guideNoteItem.isCompleted ? 0 : 2
                    radius: height / 2
                    opacity: guideNoteItem.isCompleted ? 0.9 : 0.4

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 8 * mainWindow.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.getNoteName(pitch)
                        color: parent.parent.isCompleted ? "#ffffff" : "#888888"
                        font.pixelSize: parent.height * 0.6
                        font.bold: true
                    }
                }
                
                // --- Accidental for Traditional ---
                Text {
                    visible: root.notationStyle === "traditional" && root.getAccidentalSymbol(pitch) !== ""
                    text: root.getAccidentalSymbol(pitch)
                    font.family: root.musicFont
                    color: "#111111"
                    font.pixelSize: staffBackground.lineSpacing * 2.5
                    anchors.right: parent.left
                    anchors.rightMargin: 2 * mainWindow.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                }
                
                // Ledger lines
                Repeater {
                    model: root.getLedgerSteps(guideNoteItem.steps)
                    Rectangle {
                        z: -10 // Strictly behind the note
                        x: -8 * mainWindow.uiScale
                        width: guideNoteItem.width + (16 * mainWindow.uiScale)
                        height: Math.max(1, 1.5 * mainWindow.uiScale) // Standard staff weight
                        color: "#111111" // Pure black for clarity
                        y: ((guideNoteItem.steps - modelData) * (staffBackground.lineSpacing / 2)) + (guideNoteItem.height / 2) - (height / 2)
                    }
                }
            }
        }
        
        // 3.5 Sustain Pedal Notation
        Item {
            anchors.left: parent.left
            anchors.leftMargin: staffBackground.noteStartX - (20 * mainWindow.uiScale)
            anchors.right: parent.right
            y: staffBackground.bassCenterY + (staffBackground.lineSpacing * 3.5)
            height: staffBackground.lineSpacing * 2
            visible: root.displayMode === "trainer" && root.exerciseType === "sustain_pedal"
            
            Text {
                id: pedText
                text: "Ped."
                font.pixelSize: staffBackground.lineSpacing * 1.5
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
                font.pixelSize: staffBackground.lineSpacing * 2
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

        // ── 4. Scrolling Evaluation Notes ──────────────────────────────────
        Item {
            id: scrollingContainer
            y: 0
            height: parent.height
            visible: root.displayMode === "evaluation"
            
            x: - (root.evalBeat * root.pixelsPerBeat)
            Behavior on x {
                SmoothedAnimation {
                    velocity: -1
                    duration: 80
                }
            }

            Repeater {
                model: root.evalNotes

                Item {
                    id: evalNoteItem
                    property int pitch: modelData.pitch || 60
                    property string hand: modelData.hand || "R"
                    property real startBeat: modelData.start_beat || 0
                    property real durBeats: modelData.duration_beats || 1
                    property string noteState: {
                        if (root.evalNoteStates && index < root.evalNoteStates.length)
                            return root.evalNoteStates[index];
                        return "pending";
                    }

                    property bool isTreble: hand === "L" || hand === "left" ? false : hand === "R" || hand === "right" ? true : pitch >= 60
                    property int referencePitch: isTreble ? 71 : 50
                    property real referenceY: isTreble ? staffBackground.trebleCenterY : staffBackground.bassCenterY
                    property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)

                    x: staffBackground.noteStartX + (startBeat * root.pixelsPerBeat)
                    y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                    width: root.notationStyle === "traditional" ? (staffBackground.lineSpacing * 1.1) : Math.max(durBeats * root.pixelsPerBeat - 4, 8)
                    height: staffBackground.lineSpacing * 0.72
                    z: pitch

                    // --- TRADITIONAL BRAVURA HEAD ---
                    Text {
                        id: evalHead
                        visible: root.notationStyle === "traditional"
                        text: "\uE0A4"
                        font.family: root.musicFont
                        font.pixelSize: staffBackground.lineSpacing * 2.8
                        color: evalNoteItem.noteState === "hit" ? "#4CAF50" :
                               evalNoteItem.noteState === "miss" ? "#F44336" :
                               root.getColorForFinger(modelData.finger)
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: -staffBackground.lineSpacing * 0.05
                        z: 10
                        opacity: parent.opacity
                    }

                    // --- ENHANCED CAPSULE ---
                    Rectangle {
                        id: evalCapsule
                        visible: root.notationStyle === "enhanced"
                        anchors.fill: parent
                        color: evalNoteItem.noteState === "hit" ? "#4CAF50" :
                               evalNoteItem.noteState === "miss" ? "#F44336" :
                               root.getColorForFinger(modelData.finger)
                        radius: height / 2

                        // Duration Line (Enhanced Only)
                        Rectangle {
                            visible: evalNoteItem.durBeats > 0.2
                            anchors.left: parent.horizontalCenter
                            anchors.verticalCenter: parent.verticalCenter
                            width: (evalNoteItem.durBeats * root.pixelsPerBeat) - (parent.width / 2)
                            height: 2 * mainWindow.uiScale
                            color: parent.color
                            opacity: 0.6
                            z: -1
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 6 * mainWindow.uiScale
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 0
                            visible: parent.width > 30

                            property string fullNoteName: root.getNoteName(evalNoteItem.pitch)
                            property bool hasAccidental: fullNoteName.length > 1

                            Text {
                                text: parent.fullNoteName.charAt(0)
                                color: "#ffffff"
                                font.pixelSize: parent.parent.height * 0.45
                                font.bold: true
                            }
                            Text {
                                visible: parent.hasAccidental
                                text: parent.hasAccidental ? parent.fullNoteName.charAt(1) : ""
                                color: "#ffffff"
                                font.pixelSize: parent.parent.height * 0.35
                                font.bold: true
                                anchors.baseline: parent.children[0].baseline
                                anchors.baselineOffset: -parent.parent.height * 0.08
                            }
                        }
                    }

                    // --- Accidental for Traditional ---
                    Text {
                        id: evalAccidental
                        visible: root.notationStyle === "traditional" && root.getAccidentalSymbol(pitch) !== ""
                        text: root.getAccidentalSymbol(pitch)
                        font.family: root.musicFont
                        color: "#111111"
                        font.pixelSize: staffBackground.lineSpacing * 2.5
                        anchors.right: parent.left
                        anchors.rightMargin: 2 * mainWindow.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    property real distanceInBeats: startBeat - root.evalBeat
                    opacity: noteState === "miss" ? 0.4 : 
                             (distanceInBeats > 8 ? 0.3 : (distanceInBeats > 4 ? 0.6 : 1.0))
                    
                    Rectangle {
                        id: evalStem
                        width: Math.max(1, 1.2 * mainWindow.uiScale)
                        height: staffBackground.lineSpacing * 3.4
                        color: "#111111"
                        opacity: parent.opacity
                        
                        property bool stemUp: {
                           return isTreble ? pitch < 71 : pitch < 50;
                        }

                        property real xOffset: staffBackground.lineSpacing * 0.49
                        anchors.bottom: stemUp ? parent.verticalCenter : undefined
                        anchors.top: !stemUp ? parent.verticalCenter : undefined
                        x: stemUp ? (parent.width / 2 + xOffset) : (parent.width / 2 - xOffset)
                        
                        z: 5
                        visible: root.notationStyle === "traditional"
                    }

                    property real globalX: x + scrollingContainer.x
                    visible: (globalX + width > 0) && (globalX < root.width + 100)

                    Repeater {
                        model: root.getLedgerSteps(evalNoteItem.steps)
                        Rectangle {
                            z: -1
                            x: -10 * mainWindow.uiScale
                            width: evalNoteItem.width + (20 * mainWindow.uiScale)
                            height: Math.max(1, 3 * mainWindow.uiScale)
                            color: "#111111"
                            y: ((evalNoteItem.steps - modelData) * (staffBackground.lineSpacing / 2)) + (evalNoteItem.height / 2) - (height / 2)
                        }
                    }
                }
            }
        }
        // ── 5. Scrolling Trainer Notes (Live Lessons) ───────────────────────
        Item {
            id: trainerScrollingContainer
            y: 0
            height: parent.height
            visible: root.displayMode === "trainer" && root.isScrollingMode
            
            x: - (root.scrollBeat * root.pixelsPerBeat)
            Behavior on x {
                SmoothedAnimation {
                    velocity: -1
                    duration: root.scrollBpm > 0 ? 80 : 200
                }
            }

            Repeater {
                model: root.scrollingNotes

                Item {
                    id: trainerNoteItem
                    property int pitch: modelData.pitch || 60
                    property string hand: modelData.hand || "R"
                    property real startBeat: modelData.startBeat || modelData.start_beat || 0
                    property real durBeats: modelData.durationBeats || modelData.duration_beats || 1
                    property int finger: modelData.finger || 1
                    property bool isCompleted: root.scrollBeat >= (startBeat + durBeats)
                    property bool isCurrentlyActive: root.scrollBeat >= startBeat && root.scrollBeat < (startBeat + durBeats)
                    
                    property bool isTreble: hand === "L" || hand === "left" ? false : hand === "R" || hand === "right" ? true : pitch >= 60
                    property int referencePitch: isTreble ? 71 : 50
                    property real referenceY: isTreble ? staffBackground.trebleCenterY : staffBackground.bassCenterY
                    property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)

                    x: staffBackground.noteStartX + (startBeat * root.pixelsPerBeat)
                    y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                    width: root.notationStyle === "traditional" ? staffBackground.lineSpacing * 1.1 : Math.max(durBeats * root.pixelsPerBeat - 4, 8)
                    height: staffBackground.lineSpacing * 0.72
                    z: pitch

                    property real absDistance: Math.abs(startBeat - root.scrollBeat)
                    property real focalAlpha: isCurrentlyActive ? 1.0 : Math.max(0.15, 0.8 - (absDistance / 10.0))

                    // --- TRADITIONAL BRAVURA HEAD ---
                    Text {
                        id: trainerHead
                        visible: root.notationStyle === "traditional"
                        text: "\uE0A4"
                        font.family: root.musicFont
                        font.pixelSize: staffBackground.lineSpacing * 2.8
                        color: {
                            var base = trainerNoteItem.isCompleted ? "#4CAF50" : root.getColorForFinger(trainerNoteItem.finger);
                            return Qt.styleHints.colorScheme === Qt.Dark ? Qt.darker(base, trainerNoteItem.focalAlpha) : Qt.rgba(
                                parseInt(base.substring(1,3), 16)/255,
                                parseInt(base.substring(3,5), 16)/255,
                                parseInt(base.substring(5,7), 16)/255,
                                trainerNoteItem.focalAlpha
                            );
                        }
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: -staffBackground.lineSpacing * 0.05
                        z: 10
                        opacity: 1.0
                    }

                    // --- ENHANCED CAPSULE ---
                    Rectangle {
                        id: trainerCapsule
                        visible: root.notationStyle === "enhanced"
                        anchors.fill: parent
                        radius: height / 2
                        
                        // Duration Line (Enhanced)
                        Rectangle {
                            visible: trainerNoteItem.durBeats > 0.2
                            anchors.left: parent.horizontalCenter
                            anchors.verticalCenter: parent.verticalCenter
                            width: (trainerNoteItem.durBeats * root.pixelsPerBeat) - (parent.width / 2)
                            height: 2 * mainWindow.uiScale
                            color: parent.color
                            opacity: 0.6
                            z: -1
                        }

                        color: {
                            var base = trainerNoteItem.isCompleted ? "#4CAF50" : root.getColorForFinger(trainerNoteItem.finger);
                            return Qt.styleHints.colorScheme === Qt.Dark ? Qt.darker(base, trainerNoteItem.focalAlpha) : Qt.rgba(
                                parseInt(base.substring(1,3), 16)/255,
                                parseInt(base.substring(3,5), 16)/255,
                                parseInt(base.substring(5,7), 16)/255,
                                trainerNoteItem.focalAlpha
                            );
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.leftMargin: 6 * mainWindow.uiScale
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 0
                            visible: parent.width > 30

                            property string fullNoteName: root.getNoteName(trainerNoteItem.pitch)
                            property bool hasAccidental: fullNoteName.length > 1

                            Text {
                                text: parent.fullNoteName.charAt(0)
                                color: "#ffffff"
                                style: Text.Outline
                                styleColor: "#44000000"
                                font.pixelSize: parent.parent.height * 0.65
                                font.bold: true
                            }
                            Text {
                                visible: parent.hasAccidental
                                text: parent.hasAccidental ? parent.fullNoteName.charAt(1) : ""
                                color: "#ffffff"
                                style: Text.Outline
                                styleColor: "#44000000"
                                font.pixelSize: parent.parent.height * 0.45
                                font.bold: true
                                anchors.baseline: parent.children[0].baseline
                                anchors.baselineOffset: -parent.parent.height * 0.12
                            }
                        }
                    }

                    // --- Accidental for Traditional ---
                    Text {
                        id: trainerAccidental
                        visible: root.notationStyle === "traditional" && root.getAccidentalSymbol(pitch) !== ""
                        text: root.getAccidentalSymbol(pitch)
                        font.family: root.musicFont
                        color: "#111111"
                        font.pixelSize: staffBackground.lineSpacing * 2.5
                        anchors.right: parent.left
                        anchors.rightMargin: 2 * mainWindow.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    opacity: 1.0
                    
                    Rectangle {
                        id: trainerStem
                        width: Math.max(1, 1.2 * mainWindow.uiScale)
                        height: staffBackground.lineSpacing * 3.4
                        color: "#111111"
                        opacity: trainerNoteItem.focalAlpha
                        
                        property bool stemUp: {
                           return isTreble ? pitch < 71 : pitch < 50;
                        }

                        property real xOffset: staffBackground.lineSpacing * 0.49
                        anchors.bottom: stemUp ? parent.verticalCenter : undefined
                        anchors.top: !stemUp ? parent.verticalCenter : undefined
                        x: stemUp ? (parent.width / 2 + xOffset) : (parent.width / 2 - xOffset)
                        
                        z: 5
                        visible: root.notationStyle === "traditional"
                    }

                    property real globalX: x + trainerScrollingContainer.x
                    visible: (globalX + width > 0) && (globalX < root.width + 100)

                    Repeater {
                        model: root.getLedgerSteps(trainerNoteItem.steps)
                        Rectangle {
                            z: -1
                            x: -10 * mainWindow.uiScale
                            width: trainerNoteItem.width + (20 * mainWindow.uiScale)
                            height: Math.max(1, 3 * mainWindow.uiScale)
                            color: "#111111"
                            y: ((trainerNoteItem.steps - modelData) * (staffBackground.lineSpacing / 2)) + (trainerNoteItem.height / 2) - (height / 2)
                        }
                    }
                }
            }
        }
    }
}
