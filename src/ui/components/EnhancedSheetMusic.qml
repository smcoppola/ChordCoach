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
        return names[pitch % 12];
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
            visible: text !== ""
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
                color: "#e0e0e0" // Subtle staff lines
                y: parent.trebleCenterY - ((4 - (index * 2)) * (parent.lineSpacing / 2))
            }
        }
        
        // Bass Clef (5 lines)
        Repeater {
            model: 5
            Rectangle {
                width: parent.width
                height: Math.max(1, 1.5 * mainWindow.uiScale)
                color: "#e0e0e0" // Subtle staff lines
                y: parent.bassCenterY - ((4 - (index * 2)) * (parent.lineSpacing / 2))
            }
        }
        
        // Treble Clef Symbol & Label
        Text {
            text: "𝄞"
            font.pixelSize: parent.lineSpacing * 6
            color: "#101010"
            x: 40 * mainWindow.uiScale
            anchors.verticalCenter: parent.top
            anchors.verticalCenterOffset: parent.trebleCenterY + (parent.lineSpacing * 0.5)
        }
        
        // Bass Clef Symbol & Label
        Text {
            text: "𝄢"
            font.pixelSize: parent.lineSpacing * 4.5
            color: "#101010"
            x: 40 * mainWindow.uiScale
            anchors.verticalCenter: parent.top
            anchors.verticalCenterOffset: parent.bassCenterY - (parent.lineSpacing * 0.5)
        }
        
        // Vertical Barline — marks the staff start
        Rectangle {
            x: parent.noteStartX
            y: parent.trebleCenterY - (parent.lineSpacing * 2)
            width: Math.max(1, 1.5 * mainWindow.uiScale) // Match staff line weight
            height: (parent.bassCenterY + (parent.lineSpacing * 2)) - y
            color: "#111111"
            // Hide during scrolling lessons to avoid clashing with the green playhead
            visible: !root.isScrollingMode && root.displayMode !== "evaluation"
        }
        
        // Playhead Line (Green) — tracks current note in pentascale mode
        Rectangle {
            x: root.displayMode === "evaluation" ? parent.noteStartX :
               root.isScrollingMode ? parent.noteStartX :
               root.exerciseType === "pentascale"
                ? parent.noteStartX + (root.currentNoteIndex * parent.pentaNoteSpacing) - 6
                : parent.noteStartX - 100
            y: parent.trebleCenterY - (parent.lineSpacing * 3.1)
            width: Math.max(1, 1.8 * mainWindow.uiScale) // Thinner playhead
            height: (parent.bassCenterY + (parent.lineSpacing * 3.1)) - y
            visible: root.displayMode === "evaluation" || root.isScrollingMode
            color: "#4CAF50"
            radius: width / 2
            z: 1000
            
            // Halo removed for professional clarity
            
            Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
            
            // Playhead dots
            Rectangle {
                width: 16 * mainWindow.uiScale
                height: 16 * mainWindow.uiScale
                radius: 8 * mainWindow.uiScale
                color: "#ffffff"
                border.color: "#cccccc"
                anchors.horizontalCenter: parent.horizontalCenter
                y: (parent.parent.trebleCenterY - parent.y) - (8 * mainWindow.uiScale)
            }
            Rectangle {
                width: 16 * mainWindow.uiScale
                height: 16 * mainWindow.uiScale
                radius: 8 * mainWindow.uiScale
                color: "#ffffff"
                border.color: "#cccccc"
                anchors.horizontalCenter: parent.horizontalCenter
                y: (parent.parent.bassCenterY - parent.y) - (8 * mainWindow.uiScale)
            }
        }
        
        // 2. Draw the Notes (active targets)
        Repeater {
            model: root.activeTargets
            
            Rectangle {
                visible: root.displayMode === "trainer" && !root.isScrollingMode
                property int pitch: modelData.pitch
                property int finger: modelData.finger
                property string hand: modelData.hand
                property bool isTreble: {
                    return hand === "left" ? false : hand === "right" ? true : pitch >= 60;
                }
                property int referencePitch: isTreble ? 71 : 50 // B4 or D3
                property real referenceY: isTreble ? parent.trebleCenterY : parent.bassCenterY
                property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)
                
                // Determine if this note needs to stagger because it's occluding the note right below it
                property bool isStaggeredRight: {
                    if (root.exerciseType === "pentascale") return false; // pentascale uses horizontal layout
                    if (index === 0) return false;
                    var prevPitch = root.activeTargets[index - 1].pitch;
                    var stepDiff = root.getDiatonicStepsDifference(prevPitch, pitch);
                    return stepDiff < 2;
                }
                property real staggerOffset: isStaggeredRight ? (30 * mainWindow.uiScale) : 0
                
                // In pentascale mode, position by sequence index; otherwise use full-width bar
                property bool isPentascale: root.exerciseType === "pentascale"
                property int pentaIdx: root.currentNoteIndex
                
                y: referenceY - (steps * (parent.lineSpacing / 2)) - (height / 2)
                // Use modelData.pitch for persistent Z sorting so higher notes are always on top
                z: isPentascale ? 200 : pitch
                
                x: isPentascale
                    ? parent.noteStartX + (pentaIdx * parent.pentaNoteSpacing)
                    : parent.noteStartX + staggerOffset
                width: isPentascale
                    ? parent.pentaNoteWidth
                    : parent.width - x
                height: parent.lineSpacing * 0.70 // Refined: 70% of spacing
                
                // Solid content logic: Apply transparency ONLY to background
                color: root.getColorForFinger(finger)
                radius: height / 2 // Capsule look
                
                // --- STANDARD HAND STEM ---
                Rectangle {
                    id: noteStem
                    width: Math.max(1, 1.5 * mainWindow.uiScale)
                    height: staffBackground.lineSpacing * 2.5
                    color: "#111111" // Standard black
                    
                    // Logic: RH = Up Right, LH = Down Left
                    anchors.bottom: (hand === "right" || hand === "R") ? parent.verticalCenter : undefined
                    anchors.top: (hand === "left" || hand === "L") ? parent.verticalCenter : undefined
                    anchors.right: (hand === "right" || hand === "R") ? parent.right : undefined
                    anchors.left: (hand === "left" || hand === "L") ? parent.left : undefined
                    
                    z: -5 // Behind the pill but in front of staff
                }
                
                Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                
                // Signal connection triggers animation
                Connections {
                    target: (typeof appState !== "undefined" && appState !== null) ? appState.chordTrainer : null
                    function onInputReady() {
                        if (visible) {
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
                    radius: parent.radius
                    z: 10
                    
                    SequentialAnimation on opacity {
                        id: readyGlowAnim
                        running: false
                        NumberAnimation { to: 0.6; duration: 100; easing.type: Easing.OutQuad }
                        NumberAnimation { to: 0.0; duration: 350; easing.type: Easing.InQuad }
                    }
                }
                
                // Text label inside the note bar
                Text {
                    id: labelText
                    anchors.left: parent.left
                    anchors.leftMargin: 10 * mainWindow.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.getNoteName(pitch)
                    color: root.getTextColorForFinger(finger)
                    font.pixelSize: parent.height * 0.65
                    font.bold: true
                    opacity: 1.0 // Ensure text is never faded
                }
                
                // Ledger lines if note is outside the staff
                Repeater {
                    model: root.getLedgerSteps(parent.steps)
                    Rectangle {
                        z: -10 // Strictly behind the note
                        anchors.left: parent.left
                        anchors.leftMargin: -8 * mainWindow.uiScale
                        width: 38 * mainWindow.uiScale // Fixed professional width
                        height: Math.max(1, 1.5 * mainWindow.uiScale) // Standard staff weight
                        color: "#111111" // Pure black for clarity
                        y: ((parent.steps - modelData) * (parent.parent.lineSpacing / 2)) + (parent.height / 2) - (height / 2)
                    }
                }
            }
        }
        
        // 3. Draw pentascale guide notes — staggered horizontally by sequence index
        Repeater {
            model: (root.displayMode === "trainer" && root.exerciseType === "pentascale") ? root.allPentascaleNotes : []
            
            Rectangle {
                property int pitch: modelData
                property bool isTreble: {
                    var h = root.getHandForTargetPitch(pitch);
                    return h === "left" ? false : h === "right" ? true : pitch >= 60;
                }
                property int referencePitch: isTreble ? 71 : 50
                property real referenceY: isTreble ? parent.trebleCenterY : parent.bassCenterY
                property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)
                property int noteIdx: {
                    // Find this pitch's index in the original (unsorted) pentascale sequence
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
                // Don't draw them at all if we are in scrolling mode
                visible: !isCurrent && !root.isScrollingMode
                
                y: referenceY - (steps * (parent.lineSpacing / 2)) - (height / 2)
                z: 100 + pitch
                
                // Stagger horizontally by sequence position
                x: parent.noteStartX + (noteIdx * parent.pentaNoteSpacing)
                width: parent.pentaNoteWidth
                height: parent.lineSpacing * 0.70 // Refined: 70% height
                
                color: isCompleted ? fingerColor : "transparent"
                border.color: fingerColor
                border.width: isCompleted ? 0 : 2
                radius: height / 2 // Capsule look
                opacity: isCompleted ? 0.9 : 0.4
                
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 8 * mainWindow.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.getNoteName(pitch)
                    color: parent.isCompleted ? "#ffffff" : "#888888"
                    font.pixelSize: parent.height * 0.6
                    font.bold: true
                }
                
                // Ledger lines
                Repeater {
                    model: root.getLedgerSteps(parent.steps)
                    Rectangle {
                        z: -10 // Strictly behind the note
                        x: -8 * mainWindow.uiScale
                        width: 38 * mainWindow.uiScale // Fixed professional width
                        height: Math.max(1, 1.5 * mainWindow.uiScale) // Standard staff weight
                        color: "#111111" // Pure black for clarity
                        y: ((parent.steps - modelData) * (parent.parent.parent.lineSpacing / 2)) + (parent.height / 2) - (height / 2)
                    }
                }
            }
        }
        
        // 3.5 Sustain Pedal Notation
        Item {
            anchors.left: parent.left
            anchors.leftMargin: parent.noteStartX - (20 * mainWindow.uiScale)
            anchors.right: parent.right
            y: parent.bassCenterY + (parent.lineSpacing * 3.5)
            height: parent.lineSpacing * 2
            visible: root.displayMode === "trainer" && root.exerciseType === "sustain_pedal"
            
            Text {
                id: pedText
                text: "Ped."
                font.pixelSize: parent.parent.lineSpacing * 1.5
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
                font.pixelSize: parent.parent.lineSpacing * 2
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
                width: 150 * mainWindow.uiScale
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
        // Visible ONLY in evaluation mode. Notes scroll right → left,
        // positioned by parent container offset from current beat.
        Item {
            id: scrollingContainer
            y: 0
            height: parent.height
            visible: root.displayMode === "evaluation"
            
            // The container x origin is at parent.noteStartX. 
            // We shift it left by currentBeat * pixelsPerBeat.
            x: - (root.evalBeat * root.pixelsPerBeat)
            // Use SmoothedAnimation to interpolate between Python beat ticks.
            // Python emits at 100fps but QML renders at vsync (~60fps), so
            // direct binding produces visible jumps. This smooths the gap.
            Behavior on x {
                SmoothedAnimation {
                    velocity: -1  // Match the target as fast as possible
                    duration: 80  // Enough duration to smooth Windows OS timer jitter
                }
            }

            Repeater {
                model: root.evalNotes

                Rectangle {
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

                    // Static position relative to the scrolling container
                    x: staffBackground.noteStartX + (startBeat * root.pixelsPerBeat)
                    y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                    width: Math.max(durBeats * root.pixelsPerBeat - 4, 8)
                    height: staffBackground.lineSpacing * 0.70 // Refined: 70% height
                    radius: height / 2 // Capsule look
                    z: pitch

                    // Distance-based focus: notes arriving soon are opaque
                    property real distanceInBeats: startBeat - root.evalBeat
                    opacity: noteState === "miss" ? 0.4 : 
                             (distanceInBeats > 8 ? 0.3 : (distanceInBeats > 4 ? 0.6 : 1.0))

                    // Coloring: pending = pitch color, hit = green, miss = red
                    color: noteState === "hit" ? "#4CAF50" :
                           noteState === "miss" ? "#F44336" :
                           root.getColorForFinger(modelData.finger)
                    
                    // --- STANDARD HAND STEM (SCROLLING) ---
                    Rectangle {
                        width: Math.max(1, 1.5 * mainWindow.uiScale)
                        height: staffBackground.lineSpacing * 2.5
                        color: "#111111"
                        opacity: parent.opacity // Follow the distance-fade
                        
                        anchors.bottom: (hand === "right" || hand === "R") ? parent.verticalCenter : undefined
                        anchors.top: (hand === "left" || hand === "L") ? parent.verticalCenter : undefined
                        anchors.right: (hand === "right" || hand === "R") ? parent.right : undefined
                        anchors.left: (hand === "left" || hand === "L") ? parent.left : undefined
                        z: -5
                    }

                    // Efficiency check (global coordinate check)
                    property real globalX: x + scrollingContainer.x
                    visible: (globalX + width > 0) && (globalX < root.width + 100)

                    // Note name label
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 6 * mainWindow.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 0
                        visible: parent.width > 30

                        property string fullNoteName: root.getNoteName(parent.pitch)
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

                    // Ledger lines for notes outside the staff
                    Repeater {
                        model: root.getLedgerSteps(parent.steps)
                        Rectangle {
                            z: -1
                            x: -10 * mainWindow.uiScale
                            width: parent.width + (20 * mainWindow.uiScale)
                            height: Math.max(1, 3 * mainWindow.uiScale)
                            color: "#111111"
                            y: ((parent.steps - modelData) * (parent.parent.parent.lineSpacing / 2)) + (parent.height / 2) - (height / 2)
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
            
            // Only smooth animation if metronome is running; otherwise step normally
            Behavior on x {
                SmoothedAnimation {
                    velocity: -1
                    duration: root.scrollBpm > 0 ? 80 : 200
                }
            }

            Repeater {
                model: root.scrollingNotes

                Rectangle {
                    property int pitch: modelData.pitch || 60
                    property string hand: modelData.hand || "R"
                    property real startBeat: modelData.startBeat || modelData.start_beat || 0
                    property real durBeats: modelData.durationBeats || modelData.duration_beats || 1
                    property int finger: modelData.finger || 1
                    // A note is completed if the playhead (scrollBeat) has passed the end of the note duration
                    property bool isCompleted: root.scrollBeat >= (startBeat + durBeats)
                    // The note currently crossing the start line
                    property bool isCurrentlyActive: root.scrollBeat >= startBeat && root.scrollBeat < (startBeat + durBeats)
                    
                    property bool isTreble: hand === "L" || hand === "left" ? false : hand === "R" || hand === "right" ? true : pitch >= 60
                    property int referencePitch: isTreble ? 71 : 50
                    property real referenceY: isTreble ? staffBackground.trebleCenterY : staffBackground.bassCenterY
                    property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)

                    x: staffBackground.noteStartX + (startBeat * root.pixelsPerBeat)
                    y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                    width: Math.max(durBeats * root.pixelsPerBeat - 4, 8)
                    height: staffBackground.lineSpacing * 0.70 // Refined: 70% height
                    radius: height / 2 // Capsule look
                    z: pitch

                    // Distance-based focus: Apply alpha to background ONLY
                    property real absDistance: Math.abs(startBeat - root.scrollBeat)
                    property real focalAlpha: isCurrentlyActive ? 1.0 : Math.max(0.15, 0.8 - (absDistance / 10.0))
                    
                    color: {
                        var base = isCompleted ? "#4CAF50" : root.getColorForFinger(finger);
                        return Qt.styleHints.colorScheme === Qt.Dark ? Qt.darker(base, focalAlpha) : Qt.rgba(
                            parseInt(base.substring(1,3), 16)/255,
                            parseInt(base.substring(3,5), 16)/255,
                            parseInt(base.substring(5,7), 16)/255,
                            focalAlpha
                        );
                    }
                    
                    // Standardize: No parent opacity so children stay solid
                    opacity: 1.0
                    
                    // --- STANDARD HAND STEM (TRAINER SCROLLING) ---
                    Rectangle {
                        width: Math.max(1, 1.5 * mainWindow.uiScale)
                        height: staffBackground.lineSpacing * 2.5
                        color: "#111111"
                        opacity: parent.opacity
                        
                        anchors.bottom: (hand === "right" || hand === "R") ? parent.verticalCenter : undefined
                        anchors.top: (hand === "left" || hand === "L") ? parent.verticalCenter : undefined
                        anchors.right: (hand === "right" || hand === "R") ? parent.right : undefined
                        anchors.left: (hand === "left" || hand === "L") ? parent.left : undefined
                        z: -5
                    }

                    // Efficiency check (global coordinate check)
                    property real globalX: x + trainerScrollingContainer.x
                    visible: (globalX + width > 0) && (globalX < root.width + 100)

                    // Note name label
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 6 * mainWindow.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 0
                        visible: parent.width > 30

                        property string fullNoteName: root.getNoteName(parent.pitch)
                        property bool hasAccidental: fullNoteName.length > 1

                        Text {
                            text: parent.fullNoteName.charAt(0)
                            color: "#ffffff"
                            style: Text.Outline
                            styleColor: "#44000000" // Subtle drop shadow for focus
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

                    // Ledger lines for notes outside the staff
                    Repeater {
                        model: root.getLedgerSteps(parent.steps)
                        Rectangle {
                            z: -1
                            x: -10 * mainWindow.uiScale
                            width: parent.width + (20 * mainWindow.uiScale)
                            height: Math.max(1, 3 * mainWindow.uiScale)
                            color: "#111111"
                            y: ((parent.steps - modelData) * (parent.parent.parent.lineSpacing / 2)) + (parent.height / 2) - (height / 2)
                        }
                    }
                }
            }
        }
    }
    
    // Blur overlay applied when waiting for the next exercise
}
