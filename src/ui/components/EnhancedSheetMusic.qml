import QtQuick 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#eaeaeb" // Light gray backing paper color from the mock
    clip: true
    Layout.fillWidth: true
    Layout.fillHeight: true

    property int middleC: 60
    property string targetChordName: ""
    
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
    function getColorForPitch(pitch) {
        var colors = [
            "#FF5252", // C - Red
            "#FF9800", // C# - Orange
            "#FFC107", // D - Yellow
            "#CDDC39", // D# - Lime
            "#2E7D32", // E - Darker Green
            "#00BFA5", // F - Mint
            "#00BCD4", // F# - Cyan
            "#2196F3", // G - Blue
            "#3F51B5", // G# - Indigo
            "#9C27B0", // A - Purple
            "#E040FB", // A# - Magenta
            "#E91E63", // B - Pink
        ];
        return colors[pitch % 12];
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
            if (exerciseType === "pentascale" && appState.chordTrainer.pentascaleNotes) {
                // In pentascale mode, only show the current note as the active target
                var idx = appState.chordTrainer.currentNoteIndex || 0;
                var seq = appState.chordTrainer.pentascaleNotes;
                if (seq && idx < seq.length) {
                    return [seq[idx]];
                }
                return [];
            }
            // For chords/progressions, show all notes
            return appState.chordTrainer.targetPitches.slice().sort(function(a, b){return a-b});
        }
        return [];
    }
    property string currentHand: {
        if (typeof appState !== "undefined" && appState && appState.chordTrainer) {
            return appState.chordTrainer.currentHand || "right";
        }
        return "right";
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
        
        // Target Chord Name Header
        Text {
            anchors.top: parent.top
            anchors.topMargin: 20 * mainWindow.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.formatChordTitle(root.targetChordName)
            font.pixelSize: 32 * mainWindow.uiScale
            font.bold: true
            color: "#333333"
            visible: text !== ""
            z: 20
        }

        // Treble Clef (5 lines)
        Repeater {
            model: 5
            Rectangle {
                width: parent.width
                height: Math.max(1, 2 * mainWindow.uiScale)
                color: "#111111"
                y: parent.trebleCenterY - ((4 - (index * 2)) * (parent.lineSpacing / 2))
            }
        }
        
        // Bass Clef (5 lines)
        Repeater {
            model: 5
            Rectangle {
                width: parent.width
                height: Math.max(1, 2 * mainWindow.uiScale)
                color: "#111111"
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
        
        // Vertical Barline
        Rectangle {
            x: parent.noteStartX
            y: parent.trebleCenterY - (parent.lineSpacing * 2)
            width: Math.max(1, 3 * mainWindow.uiScale)
            height: (parent.bassCenterY + (parent.lineSpacing * 2)) - y
            color: "#111111"
        }
        
        // Playhead Line (Green) — tracks current note in pentascale mode
        Rectangle {
            x: root.displayMode === "evaluation" ? parent.noteStartX :
               root.exerciseType === "pentascale"
                ? parent.noteStartX + (root.currentNoteIndex * parent.pentaNoteSpacing) - 6
                : parent.noteStartX - 100
            y: parent.trebleCenterY - (parent.lineSpacing * 3)
            width: Math.max(1, 4 * mainWindow.uiScale)
            height: (parent.bassCenterY + (parent.lineSpacing * 3)) - y
            visible: root.displayMode === "evaluation"
            color: "#8BC34A"
            radius: 2 * mainWindow.uiScale
            
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
                visible: root.displayMode === "trainer"
                property int pitch: modelData
                property bool isTreble: root.currentHand === "left" ? false :
                                        root.currentHand === "right" ? true :
                                        pitch >= 60  // "both" falls back to pitch-based
                property int referencePitch: isTreble ? 71 : 50 // B4 or D3
                property real referenceY: isTreble ? parent.trebleCenterY : parent.bassCenterY
                property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)
                
                // Determine if this note needs to stagger because it's occluding the note right below it
                property bool isStaggeredRight: {
                    if (root.exerciseType === "pentascale") return false; // pentascale uses horizontal layout
                    if (index === 0) return false;
                    var prevPitch = root.activeTargets[index - 1];
                    var stepDiff = root.getDiatonicStepsDifference(prevPitch, pitch);
                    return stepDiff < 2;
                }
                property real staggerOffset: isStaggeredRight ? (30 * mainWindow.uiScale) : 0
                
                // In pentascale mode, position by sequence index; otherwise use full-width bar
                property bool isPentascale: root.exerciseType === "pentascale"
                property int pentaIdx: root.currentNoteIndex
                
                y: referenceY - (steps * (parent.lineSpacing / 2)) - (height / 2)
                z: isPentascale ? 200 : pitch
                
                x: isPentascale
                    ? parent.noteStartX + (pentaIdx * parent.pentaNoteSpacing)
                    : parent.noteStartX + staggerOffset
                width: isPentascale
                    ? parent.pentaNoteWidth
                    : parent.width - x
                height: parent.lineSpacing * 0.95
                
                color: root.getColorForPitch(pitch)
                radius: 4
                
                Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
                
                // Text label inside the note bar
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 8 * mainWindow.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 0
                    
                    property string fullNoteName: root.getNoteName(pitch)
                    property bool hasAccidental: fullNoteName.length > 1
                    
                    Text {
                        text: parent.fullNoteName.charAt(0)
                        color: "#ffffff"
                        font.pixelSize: parent.parent.height * 0.7
                        font.bold: true
                    }
                    Text {
                        visible: parent.hasAccidental
                        text: parent.hasAccidental ? parent.fullNoteName.charAt(1) : ""
                        color: "#ffffff"
                        font.pixelSize: parent.parent.height * 0.5
                        font.bold: true
                        anchors.baseline: parent.children[0].baseline
                        anchors.baselineOffset: -parent.parent.height * 0.15
                    }
                }
                
                // Ledger lines if note is outside the staff
                Repeater {
                    model: root.getLedgerSteps(parent.steps)
                    Rectangle {
                        z: -1
                        anchors.left: parent.left
                        anchors.leftMargin: (-15 * mainWindow.uiScale) - parent.staggerOffset
                        width: (50 * mainWindow.uiScale) + parent.staggerOffset
                        height: Math.max(1, 3 * mainWindow.uiScale)
                        color: "#111111"
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
                property bool isTreble: root.currentHand === "left" ? false :
                                        root.currentHand === "right" ? true :
                                        pitch >= 60
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
                
                // Don't draw the current note here — it's drawn by the activeTargets repeater
                visible: !isCurrent
                
                y: referenceY - (steps * (parent.lineSpacing / 2)) - (height / 2)
                z: 100 + pitch
                
                // Stagger horizontally by sequence position
                x: parent.noteStartX + (noteIdx * parent.pentaNoteSpacing)
                width: parent.pentaNoteWidth
                height: parent.lineSpacing * 0.95
                
                color: isCompleted ? "#4CAF50" : "transparent"
                border.color: isCompleted ? "#4CAF50" : "#999999"
                border.width: isCompleted ? 0 : 2
                radius: 4
                opacity: isCompleted ? 0.7 : 0.4
                
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
                        z: -1
                        x: -15 * mainWindow.uiScale
                        width: parent.width + (30 * mainWindow.uiScale)
                        height: Math.max(1, 3 * mainWindow.uiScale)
                        color: "#111111"
                        y: ((parent.steps - modelData) * (parent.parent.lineSpacing / 2)) + (parent.height / 2) - (height / 2)
                    }
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
            
            Behavior on x { 
                NumberAnimation { 
                    duration: 33 // Slight interpolation to bridge 10ms-16ms Python ticks
                    easing.type: Easing.Linear 
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

                    property bool isTreble: hand === "L" ? false : hand === "R" ? true : pitch >= 60
                    property int referencePitch: isTreble ? 71 : 50
                    property real referenceY: isTreble ? staffBackground.trebleCenterY : staffBackground.bassCenterY
                    property int steps: root.getDiatonicStepsDifference(referencePitch, pitch)

                    // Static position relative to the scrolling container
                    x: staffBackground.noteStartX + (startBeat * root.pixelsPerBeat)
                    y: referenceY - (steps * (staffBackground.lineSpacing / 2)) - (height / 2)
                    width: Math.max(durBeats * root.pixelsPerBeat - 4, 8)
                    height: staffBackground.lineSpacing * 0.95
                    radius: 4
                    z: pitch

                    // Coloring: pending = pitch color, hit = green, miss = red
                    color: noteState === "hit" ? "#4CAF50" :
                           noteState === "miss" ? "#F44336" :
                           root.getColorForPitch(pitch)
                    opacity: noteState === "miss" ? 0.4 : 1.0

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
                            font.pixelSize: parent.parent.height * 0.65
                            font.bold: true
                        }
                        Text {
                            visible: parent.hasAccidental
                            text: parent.hasAccidental ? parent.fullNoteName.charAt(1) : ""
                            color: "#ffffff"
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
}
