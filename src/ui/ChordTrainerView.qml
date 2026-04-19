import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
import "./components" as Components

Rectangle {
    id: root
    color: "transparent"
    
    property bool isActive: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isActive : false
    property string currentTarget: ""
    
    signal returnToDashboard()
    
    // Lesson State Properties - Bound directly to service to survive StackView recreation
    property string exerciseName: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.exerciseName : ""
    property int lessonProgress: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.lessonProgress : 0
    property int lessonTotal: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.lessonTotal : 0
    property bool isLessonComplete: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isLessonComplete : false
    property bool isSongCompleted: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isSongCompleted : false
    property bool isLessonMode: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isLessonMode : false
    property real holdProgress: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.holdProgress : 0.0
    property int requiredHoldMs: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.requiredHoldMs : 0
    property bool isLoading: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isLoading : false
    property string loadingStatusText: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.loadingStatusText : ""
    property bool isPausedForSpeech: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isPausedForSpeech : false
    property bool isWaitingForAi: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isWaitingForAi : false
    
    // Song Metadata
    property string songTitle: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.songTitle : ""
    property string songComposer: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.songComposer : ""
    
    // UI Modal States for Blurring
    property bool isReconnecting: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false
    property bool isOverlayVisible: isWaitingForAi || isPausedForSpeech || isLessonComplete || isSongCompleted || isLoading || isReconnecting

    
    onIsPausedForSpeechChanged: {
        console.log("[TIMING " + new Date().toISOString() + "] QML root.isPausedForSpeech is now: " + root.isPausedForSpeech)
    }
    property bool isWaitingToBegin: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isWaitingToBegin : false
    property real estimatedGenerationMs: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.estimatedGenerationMs : 0.0
    
    // AI Coach State Properties
    property bool isAiSpeaking: isPausedForSpeech
    property string transcriptText: ""
    
    // Formula Properties - Pull these from service on target change
    property string chordType: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.targetChordType : ""
    property string formulaText: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.targetFormulaText : ""
    
    // New exercise type properties
    property string exerciseType: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? (appState.chordTrainer.exerciseType || "chord") : "chord"
    property var progressionNumerals: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? (appState.chordTrainer.progressionNumerals || []) : []
    property int currentProgressionIndex: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.currentProgressionIndex : 0
    property int currentNoteIndex: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.currentNoteIndex : 0
    property string scaleName: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? (appState.chordTrainer.scaleName || "") : ""
    property string currentHand: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? (appState.chordTrainer.currentHand || "right") : "right"
    property bool isSustainPedalDown: (typeof appState !== "undefined" && appState !== null && appState.hw_service) ? appState.hw_service._is_sustain_pedal_down : false
    property int pentascaleBeatCount: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.pentascaleBeatCount : 0
    property var pentascaleFeedbackList: ["", "", "", "", ""]
 
    // Internal state for loading animation
    property real loadingProgress: 0.0
    
    NumberAnimation {
        id: loadingAnim
        target: root
        property: "loadingProgress"
        from: 0.0
        to: 1.0
        duration: Math.max(1000, root.estimatedGenerationMs)
        easing.type: Easing.OutCubic
    }

    onIsLoadingChanged: {
        if (isLoading) {
            loadingProgress = 0.0;
            loadingAnim.restart();
            console.log("ChordTrainerView: Loading started, animating over " + loadingAnim.duration + "ms");
        } else {
            loadingAnim.stop();
            loadingProgress = 0.0;
        }
    }
    
    Component.onCompleted: {
        // Essential for views created late (e.g. via StackView)
        console.log("ChordTrainerView: Component completed. isLoading=" + isLoading + ", est=" + estimatedGenerationMs);
        if (appState && appState.chordTrainer) {
            if (isLoading) {
                loadingProgress = 0.0;
                loadingAnim.restart();
            }
            
            var tp = appState.chordTrainer.targetPitches;
            if (tp && tp.length > 0) {
                var arr = [];
                for (var i = 0; i < tp.length; i++) arr.push(tp[i]);
                var hands = appState.chordTrainer.targetHands;
                var fingers = appState.chordTrainer.targetFingers;
                visualKeyboard.setTargetKeys(arr, hands, fingers);
            }
        }
    }

    Connections {
        target: (typeof appState !== "undefined" && appState !== null) ? appState : null
        function onAiTranscriptReceived(textMsg) {
            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML AI Transcript received: " + textMsg.substring(0, 50) + (textMsg.length > 50 ? "..." : ""));
            root.transcriptText = textMsg;
        }
    }
    
    Connections {
        target: (typeof appState !== "undefined" && appState !== null) ? appState.chordTrainer : null
        
        function onChordFailed() {
            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML Visual failFlash triggered");
            failFlash.start();
        }
        
        function onChordSuccess(chordName, latencyMs) {
            // Disable background flash for freeplay (song_application)
            if (root.exerciseType !== "song_application") {
                successFlash.start();
            }
            
            // Qualitatively feedback for pentascales handled here...
            if (root.exerciseType === "pentascale") {
                // Future: Add logic for qualitative timing feedback if requested, 
                // but removing numeric ms indicators for now as per user request.
            }

            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML Visual successFlash triggered");
        }
        
        function onTargetChordChanged(chordName) {
            root._syncVisualKeyboard(chordName);
        }
        
        function onTargetFingersChanged() {
            root._syncVisualKeyboard(root.currentTarget);
        }
        
        
        function onPentascaleNoteHit(noteIndex, feedbackText) {
            var newFeedback = root.pentascaleFeedbackList.slice(); // Copy array
            if (noteIndex >= 0 && noteIndex < 5) {
                newFeedback[noteIndex] = feedbackText;
                root.pentascaleFeedbackList = newFeedback;      // Trigger bindings
            }
            
            // Trigger large central feedback
            centralFeedbackText.text = feedbackText;
            centralFeedbackAnim.restart();
        }

        function onStatusMessageRequested(type, message) {
            if (type === "error") {
                errorToastText.text = message;
                errorToastAnim.restart();
            }
        }
    }

    function _syncVisualKeyboard(chordName) {
        root.currentTarget = chordName;
        root.pentascaleFeedbackList = ["", "", "", "", ""]; // Reset feedback on new target
        
        // Re-sync visual keyboard target keys
        if (appState && appState.chordTrainer) {
            var tp = appState.chordTrainer.targetPitches;
            var arr = [];
            if (tp) {
                for (var i = 0; i < tp.length; i++) arr.push(tp[i]);
            }
            var hands = appState.chordTrainer.targetHands;
            var fingers = appState.chordTrainer.targetFingers;
            visualKeyboard.setTargetKeys(arr, hands, fingers);
            console.log("ChordTrainerView updated -> target: '" + root.currentTarget + "', keys: " + arr + ", fingers: " + fingers);
        }
    }
    
    // Success/Fail flash animation
    Rectangle {
        id: bgFlash
        anchors.fill: parent
        color: "transparent" // Color changes based on animation running
        opacity: 0.0
        
        SequentialAnimation on opacity {
            id: successFlash
            running: false
            PropertyAction { target: bgFlash; property: "color"; value: "#4CAF50" }
            NumberAnimation { to: 0.3; duration: 50; easing.type: Easing.OutQuad }
            NumberAnimation { to: 0.0; duration: 400; easing.type: Easing.InQuad }
        }
        
        SequentialAnimation on opacity {
            id: failFlash
            running: false
            PropertyAction { target: bgFlash; property: "color"; value: "#F44336" }
            NumberAnimation { to: 0.15; duration: 50; easing.type: Easing.OutQuad }
            NumberAnimation { to: 0.0; duration: 400; easing.type: Easing.InQuad }
        }
    }

    ColumnLayout {
        id: lessonContent
        anchors.fill: parent
        anchors.margins: 40 * mainWindow.uiScale
        spacing: 30 * mainWindow.uiScale
        layer.enabled: root.isOverlayVisible
        
        // Header Text
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: parent.width * 0.9
            text: {
                if (root.isLoading) return "INITIALIZING LESSON...";
                if (root.exerciseType === "song_application" || root.songTitle !== "") {
                    var titleStr = root.songTitle || "Unknown Piece";
                    var compStr = root.songComposer && root.songComposer !== "Unknown Composer" ? root.songComposer + ": " : "";
                    return (compStr + titleStr).toUpperCase();
                }
                if (!root.isActive) return "CHORD TRAINER";
                if (root.isLessonMode) return "LESSON: " + root.exerciseName.toUpperCase() + " (EXERCISE " + root.lessonProgress + ")";
                return "FREE PRACTICE";
            }
            color: root.isActive ? (root.isLessonMode ? "#2196F3" : "#888888") : "#ffffff"
            font.pixelSize: 18 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
        
        // AI Coach Presenter
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 600 * mainWindow.uiScale
            spacing: 15 * mainWindow.uiScale
            visible: (root.isActive || root.isLoading) && root.transcriptText.length > 0
            
            // The Glowing "Waveform/Pulse" Indicator
            Rectangle {
                id: aiPulse
                Layout.alignment: Qt.AlignVCenter
                width: 12 * mainWindow.uiScale
                height: 12 * mainWindow.uiScale
                radius: 6 * mainWindow.uiScale
                color: root.isAiSpeaking ? "#00BCD4" : "#444444"
                
                // Outer glow animation
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 2
                    height: parent.height * 2
                    radius: width / 2
                    color: "transparent"
                    border.width: root.isAiSpeaking ? (3 * mainWindow.uiScale) : 0
                    border.color: "#00BCD4"
                    opacity: 0.0
                    
                    SequentialAnimation on opacity {
                        running: root.isAiSpeaking
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.6; duration: 500; easing.type: Easing.InOutQuad }
                        NumberAnimation { to: 0.0; duration: 500; easing.type: Easing.InOutQuad }
                    }
                    SequentialAnimation on scale {
                        running: root.isAiSpeaking
                        loops: Animation.Infinite
                        NumberAnimation { from: 1.0; to: 1.5; duration: 1000; easing.type: Easing.OutQuad }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: root.transcriptText
                color: "#cccccc"
                font.pixelSize: 18 * mainWindow.uiScale
                font.italic: true
                font.weight: root.isAiSpeaking ? Font.Bold : Font.Normal
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignLeft
                lineHeight: 1.2
            }
        }
        
        // Mathematical Formula Teaching Aid overlay
        Components.ChordFormulaCard {
            targetChordName: root.currentTarget || ""
            chordType: root.chordType || ""
            formulaText: root.formulaText || ""
            isActive: root.isActive && !root.isLessonComplete && root.exerciseType !== "listen"
        }
        
        // Hold Progress Bar (Only visible during Rhythmic Locking)
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 300 * mainWindow.uiScale
            Layout.preferredHeight: 8 * mainWindow.uiScale
            radius: 4 * mainWindow.uiScale
            color: "#333333"
            visible: root.isActive && !root.isLessonComplete && root.requiredHoldMs > 0
            
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * root.holdProgress
                color: "#4CAF50"
                radius: 4 * mainWindow.uiScale
            }
        }
        
        // Progression Roman Numeral Indicator
        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20 * mainWindow.uiScale
            visible: root.isActive && !root.isLessonComplete && root.exerciseType === "progression" && root.progressionNumerals.length > 0
            
            Repeater {
                model: root.progressionNumerals
                delegate: Rectangle {
                    width: 60 * mainWindow.uiScale
                    height: 40 * mainWindow.uiScale
                    radius: 6 * mainWindow.uiScale
                    color: index === root.currentProgressionIndex ? "#2196F3" : "#333333"
                    border.color: index === root.currentProgressionIndex ? "#64B5F6" : "#555555"
                    border.width: index === root.currentProgressionIndex ? (2 * mainWindow.uiScale) : Math.max(1, 1 * mainWindow.uiScale)
                    
                    Text {
                        anchors.centerIn: parent
                        text: modelData
                        color: index === root.currentProgressionIndex ? "#ffffff" : "#888888"
                        font.pixelSize: 18 * mainWindow.uiScale
                        font.bold: index === root.currentProgressionIndex
                    }
                    
                    Behavior on color { ColorAnimation { duration: 200 } }
                }
            }
        }
        
        // Pentascale Note Progress Indicator (Deprecated in favor of scrolling)
        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 32 * mainWindow.uiScale
            visible: false // Legacy: replaced by scrolling bars
            
            Repeater {
                model: 5
                delegate: Column {
                    spacing: 12 * mainWindow.uiScale
                    width: 80 * mainWindow.uiScale
                    
                    Text {
                        id: feedbackTextLabel
                        text: root.pentascaleFeedbackList[index]
                        color: {
                            if (text === "Perfect!") return "#4CAF50";
                            if (text === "Fast") return "#FFC107";
                            if (text === "Slow") return "#FF9800";
                            return "transparent";
                        }
                        font.pixelSize: 18 * mainWindow.uiScale
                        font.bold: true
                        font.letterSpacing: 1
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: 24 * mainWindow.uiScale
                        opacity: 0.0
                        
                        onTextChanged: {
                            if (text !== "") {
                                opacity = 1.0;
                                feedbackDisplayTimer.restart();
                            }
                        }
                        
                        Behavior on opacity {
                            NumberAnimation { duration: 200; easing.type: Easing.OutQuad }
                        }
                        
                        Timer {
                            id: feedbackDisplayTimer
                            interval: 800
                            onTriggered: feedbackTextLabel.opacity = 0.0
                        }
                    }
                    
                    Rectangle {
                        id: dot
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 24 * mainWindow.uiScale
                        height: 24 * mainWindow.uiScale
                        radius: 12 * mainWindow.uiScale
                        
                        property bool isActive: index === root.currentNoteIndex
                        property bool isCorrect: index < root.currentNoteIndex
                        
                        color: isCorrect ? "#4CAF50" : (isActive ? "#00E5FF" : "#2a2a2a")
                        border.color: isActive ? "#B2EBF2" : (isCorrect ? "#81C784" : "transparent")
                        border.width: isActive ? Math.max(1, 3 * mainWindow.uiScale) : (isCorrect ? Math.max(1, 1 * mainWindow.uiScale) : 0)
                        
                        // Glow effect for active dot
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -4 * mainWindow.uiScale
                            radius: parent.radius + 4 * mainWindow.uiScale
                            color: "#00E5FF"
                            opacity: dot.isActive ? 0.4 : 0.0
                            z: -1
                            
                            Behavior on opacity { NumberAnimation { duration: 300 } }
                            
                            SequentialAnimation on scale {
                                running: dot.isActive
                                loops: Animation.Infinite
                                NumberAnimation { from: 1.0; to: 1.2; duration: 600; easing.type: Easing.InOutQuad }
                                NumberAnimation { from: 1.2; to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
                            }
                        }
                        
                        Behavior on color { ColorAnimation { duration: 250 } }
                        
                        // Icon for correct notes
                        Text {
                            anchors.centerIn: parent
                            text: "✓"
                            color: "white"
                            font.pixelSize: 14 * mainWindow.uiScale
                            visible: dot.isCorrect
                        }
                    }
                }
            }
        }

        // --- Rhythm Progress Bar (The moving target cursor) (Deprecated in favor of scrolling) ---
        Rectangle {
            id: rhythmGuide
            Layout.alignment: Qt.AlignHCenter
            width: 528 * mainWindow.uiScale // (5 dots * 80 + 4 spacing * 32)
            height: 6 * mainWindow.uiScale
            color: "#1a1a1b"
            radius: 3 * mainWindow.uiScale
            visible: false // Legacy: replaced by scrolling bars
            
            Rectangle {
                id: rhythmCursor
                width: 24 * mainWindow.uiScale
                height: 24 * mainWindow.uiScale
                radius: 12 * mainWindow.uiScale
                color: "#00E5FF"
                anchors.verticalCenter: parent.verticalCenter
                
                x: {
                    var dotWidth = 80 * mainWindow.uiScale;
                    var spacing = 32 * mainWindow.uiScale;
                    var step = dotWidth + spacing;
                    var startX = (dotWidth / 2) - (width / 2);
                    
                    if (root.pentascaleBeatCount < 0) {
                        return startX - (20 * mainWindow.uiScale); 
                    }
                    return startX + (root.pentascaleBeatCount * step);
                }
                
                opacity: root.pentascaleBeatCount >= 0 ? 1.0 : 0.3
                visible: parent.visible
                
                Behavior on x {
                    NumberAnimation { 
                        duration: (root.pentascaleBpm > 0) ? (60000 / root.pentascaleBpm) : 500
                        easing.type: Easing.Linear 
                    }
                }
                
                // Pulsing glow for the cursor
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -6 * mainWindow.uiScale
                    radius: parent.radius + (6 * mainWindow.uiScale)
                    color: parent.color
                    opacity: 0.3
                    visible: root.pentascaleBeatCount >= 0
                    SequentialAnimation on scale {
                        loops: Animation.Infinite
                        NumberAnimation { from: 1.0; to: 1.4; duration: 500; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 1.4; to: 1.0; duration: 500; easing.type: Easing.InOutSine }
                    }
                }
            }
        }
        
        
        // Target display area - Dedicated Layout for Hands and Music
        RowLayout {
            id: displayAreaRow
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: 1600 * mainWindow.uiScale
            Layout.fillHeight: true
            Layout.minimumHeight: 450 * mainWindow.uiScale
            spacing: 20 * mainWindow.uiScale
            visible: root.isActive && !root.isLessonComplete && root.exerciseType !== "listen"

            // Professional Visual Hand Guides (Image-based)
            Components.HandGuide {
                handType: "left"
                Layout.alignment: Qt.AlignVCenter
                opacity: 0.8
            }

            // Sheet Music Pane
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                
                Components.EnhancedSheetMusic {
                    id: sheetMusicPane
                    anchors.fill: parent
                    targetChordName: root.currentTarget
                    
                    // Subtle dimming if a mistake is currently being held
                    opacity: (appState && appState.chordTrainer && appState.chordTrainer.mistakeActive) ? 0.85 : 1.0
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                }
                
            }

            Components.HandGuide {
                handType: "right"
                Layout.alignment: Qt.AlignVCenter
                opacity: 0.8
            }
        } 
        
        // Ear Training Quiz View
        Rectangle {
            id: listenQuizView
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: 1000 * mainWindow.uiScale
            Layout.fillHeight: true
            Layout.minimumHeight: 450 * mainWindow.uiScale
            color: "#1c1c1e"
            radius: 12 * mainWindow.uiScale
            border.color: "#9C27B0" // Purple for ear training
            border.width: Math.max(1, 1 * mainWindow.uiScale)
            visible: root.isActive && !root.isLessonComplete && !root.isPausedForSpeech && root.exerciseType === "listen"
            onVisibleChanged: {
                var d = new Date();
                var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
                console.log("[TIMING " + timeStr + "] QML EarTraining Overlay visible: " + visible);
            }
            
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 30 * mainWindow.uiScale
                
                Text {
                    text: "EAR TRAINING"
                    font.pixelSize: 14 * mainWindow.uiScale
                    font.bold: true
                    font.letterSpacing: 4 * mainWindow.uiScale
                    color: "#9C27B0"
                    Layout.alignment: Qt.AlignHCenter
                }
                
                Text {
                    text: "Identify the chord quality you just heard."
                    font.pixelSize: 22 * mainWindow.uiScale
                    color: "#ffffff"
                    Layout.alignment: Qt.AlignHCenter
                }
                
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 20 * mainWindow.uiScale
                    
                    Repeater {
                        model: ["Major", "Minor"]
                        delegate: Button {
                            id: quizBtn
                            contentItem: Text {
                                text: modelData.toUpperCase()
                                color: "#ffffff"
                                font.pixelSize: 20 * mainWindow.uiScale
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                            }
                            background: Rectangle {
                                implicitWidth: 160 * mainWindow.uiScale
                                implicitHeight: 60 * mainWindow.uiScale
                                color: quizBtn.down ? "#7B1FA2" : (quizBtn.hovered ? "#9C27B0" : "#4A148C")
                                radius: 8 * mainWindow.uiScale
                                border.color: "#ffffff20"
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }
                            onClicked: {
                                if (appState && appState.chordTrainer) {
                                    appState.chordTrainer.handle_ear_training_answer(modelData);
                                }
                            }
                        }
                    }
                }
                
                Button {
                    text: "Replay Audio"
                    flat: true
                    onClicked: {
                        if (appState && appState.chordTrainer) {
                            appState.chordTrainer.replay_preview();
                        }
                    }
                    Layout.alignment: Qt.AlignHCenter
                }
            }
        }
        
        Item { Layout.fillHeight: true } // Spacer

        // Target display area - Interactive Keyboard
        Components.VisualKeyboard {
            id: visualKeyboard
            Layout.fillWidth: true
            Layout.preferredHeight: 180 * mainWindow.uiScale
            visible: root.isActive || root.isLoading
        }
    }

    // --- Full-pane blur when AI is speaking ---
    FastBlur {
        anchors.fill: lessonContent
        source: lessonContent
        radius: root.isOverlayVisible ? (20 * mainWindow.uiScale) : 0
        visible: radius > 0

        z: 50
        Behavior on radius { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
    }

    // Phase Complete overlay (floats over the entire blurred lesson pane)
    Rectangle {
        id: phaseCompleteOverlay
        anchors.fill: parent
        z: 100
        color: Qt.rgba(0.11, 0.11, 0.12, 0.5)
        visible: root.isOverlayVisible && !root.isLessonComplete && !root.isLoading && !appState.isReconnecting

        onVisibleChanged: {
            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML PhaseComplete Overlay visible: " + visible);
        }

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 20 * mainWindow.uiScale

            Row {
                Layout.alignment: Qt.AlignHCenter
                spacing: 12 * mainWindow.uiScale

                Repeater {
                    model: 3
                    Rectangle {
                        width: 12 * mainWindow.uiScale
                        height: 12 * mainWindow.uiScale
                        radius: 6 * mainWindow.uiScale
                        color: "#00BCD4"

                        SequentialAnimation on opacity {
                            loops: Animation.Infinite
                            running: phaseCompleteOverlay.visible
                            PauseAnimation { duration: modelData * 200 }
                            NumberAnimation { from: 0.2; to: 1.0; duration: 400; easing.type: Easing.InOutSine }
                            NumberAnimation { from: 1.0; to: 0.2; duration: 400; easing.type: Easing.InOutSine }
                            PauseAnimation { duration: (3 - modelData) * 200 }
                        }
                    }
                }
            }
        }
    }

    // Lesson Complete screen overlay
    Rectangle {
        id: lessonCompleteOverlay
        anchors.centerIn: parent
        width: Math.min(700 * mainWindow.uiScale, parent.width * 0.9)
        height: Math.min(350 * mainWindow.uiScale, parent.height * 0.8)
        color: "#1c1c1e"
        border.color: "#00BCD4"
        border.width: Math.max(1, 1 * mainWindow.uiScale)
        radius: 12 * mainWindow.uiScale
        visible: root.isLessonComplete
        z: 110
        
        // Subtle glow effect
        Rectangle {
            anchors.fill: parent
            anchors.margins: -1 * mainWindow.uiScale
            radius: 12 * mainWindow.uiScale
            color: "transparent"
            border.color: "#00BCD4"
            border.width: 2 * mainWindow.uiScale
            opacity: 0.3
        }
        
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 20 * mainWindow.uiScale
            
            Text {
                text: "LESSON COMPLETE"
                font.pixelSize: 32 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 2 * mainWindow.uiScale
                color: "#ffffff"
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                text: "You successfully finished '" + root.exerciseName + "'."
                font.pixelSize: 18 * mainWindow.uiScale
                color: "#aaaaaa"
                Layout.alignment: Qt.AlignHCenter
            }
            
            Item { Layout.preferredHeight: 10 * mainWindow.uiScale }
            
            Button {
                text: "RETURN TO DASHBOARD"
                Layout.alignment: Qt.AlignHCenter
                
                background: Rectangle {
                    implicitWidth: 220 * mainWindow.uiScale
                    implicitHeight: 50 * mainWindow.uiScale
                    color: parent.down ? "#333333" : (parent.hovered ? "#444444" : "#2a2a2a")
                    radius: 8 * mainWindow.uiScale
                    border.color: "#333333"
                }
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 14 * mainWindow.uiScale
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: root.returnToDashboard()
            }
        }
    }

    // Song Complete overlay — shown for ~1.5 s while waiting for AI feedback
    Rectangle {
        id: songCompleteOverlay
        anchors.centerIn: parent
        width: Math.min(700 * mainWindow.uiScale, parent.width * 0.9)
        height: Math.min(300 * mainWindow.uiScale, parent.height * 0.7)
        color: "#1c1c1e"
        border.color: "#4CAF50"
        border.width: Math.max(1, 1 * mainWindow.uiScale)
        radius: 12 * mainWindow.uiScale
        visible: root.isSongCompleted
        z: 110

        Rectangle {
            anchors.fill: parent
            anchors.margins: -1 * mainWindow.uiScale
            radius: 12 * mainWindow.uiScale
            color: "transparent"
            border.color: "#4CAF50"
            border.width: 2 * mainWindow.uiScale
            opacity: 0.3
        }

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 16 * mainWindow.uiScale

            Text {
                text: "SONG COMPLETE"
                font.pixelSize: 32 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 2 * mainWindow.uiScale
                color: "#ffffff"
                Layout.alignment: Qt.AlignHCenter
            }

            Text {
                text: root.songTitle + (root.songComposer !== "" ? "  ·  " + root.songComposer : "")
                font.pixelSize: 16 * mainWindow.uiScale
                color: "#aaaaaa"
                Layout.alignment: Qt.AlignHCenter
            }

            Item { Layout.preferredHeight: 8 * mainWindow.uiScale }

            Text {
                text: "Great work! Getting your feedback…"
                font.pixelSize: 14 * mainWindow.uiScale
                color: "#666666"
                Layout.alignment: Qt.AlignHCenter
            }
        }
    }

    // Center Loading Animation
    Rectangle {
        id: loadingOverlay
        anchors.fill: parent
        color: "transparent"
        visible: !root.isActive && root.isLoading
        z: 110
        
        onVisibleChanged: {
            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML LoadingAnimation Overlay visible: " + visible);
        }
        
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 40 * mainWindow.uiScale
            
            // Pulsing rings
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 100 * mainWindow.uiScale
                height: 100 * mainWindow.uiScale
                radius: 50 * mainWindow.uiScale
                color: "transparent"
                border.width: 4 * mainWindow.uiScale
                border.color: "#2196F3"
                
                SequentialAnimation on scale {
                    loops: Animation.Infinite
                    running: !root.isActive && root.isLoading
                    NumberAnimation { from: 0.5; to: 1.5; duration: 1500; easing.type: Easing.OutCubic }
                }
                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: !root.isActive && root.isLoading
                    NumberAnimation { from: 1.0; to: 0.0; duration: 1500; easing.type: Easing.OutCubic }
                }
                
                // Inner dot
                Rectangle {
                    anchors.centerIn: parent
                    width: 20 * mainWindow.uiScale
                    height: 20 * mainWindow.uiScale
                    radius: 10 * mainWindow.uiScale
                    color: "#2196F3"
                    
                    SequentialAnimation on scale {
                        loops: Animation.Infinite
                        running: !root.isActive && root.isLoading
                        NumberAnimation { from: 0.8; to: 1.2; duration: 750; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 1.2; to: 0.8; duration: 750; easing.type: Easing.InOutSine }
                    }
                }
            }
            
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: root.loadingStatusText
                color: "#2196F3"
                font.pixelSize: 18 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 4 * mainWindow.uiScale
                
                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: !root.isActive && root.isLoading
                    NumberAnimation { from: 0.4; to: 1.0; duration: 1000; easing.type: Easing.InOutSine }
                    NumberAnimation { from: 1.0; to: 0.4; duration: 1000; easing.type: Easing.InOutSine }
                }
            }
            
            // Dynamic Loading Progress Bar
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 300 * mainWindow.uiScale
                Layout.preferredHeight: 8 * mainWindow.uiScale
                radius: 4 * mainWindow.uiScale
                color: "#333333"
                visible: !root.isActive && root.isLoading && root.estimatedGenerationMs > 0
                clip: true
                
                Rectangle {
                    id: loadingFill
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: parent.width * root.loadingProgress
                    color: "#2196F3"
                    radius: 4 * mainWindow.uiScale
                }
            }
        }
    }

    // Count-in Overlay (Metronome Lead-in) moved here to float over layout
    Rectangle {
        anchors.centerIn: parent
        width: 300 * mainWindow.uiScale
        height: 150 * mainWindow.uiScale
        color: "transparent"
        visible: root.isActive && !root.isLessonComplete && root.exerciseType === "pentascale" && root.pentascaleBeatCount < 0
        z: 100 // Float above other content
        onVisibleChanged: {
            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML CountIn Overlay visible: " + visible);
        }
        
        Text {
            id: countInText
            anchors.centerIn: parent
            // Show count down: -4 -> 4, -3 -> 3, etc.
            text: Math.abs(root.pentascaleBeatCount).toString()
            font.pixelSize: 120 * mainWindow.uiScale
            font.bold: true
            color: "#64B5F6"
            style: Text.Outline
            styleColor: "#111111"
            opacity: 0.8
            
            // Add a little punch animation on every beat
            Behavior on text {
                SequentialAnimation {
                    NumberAnimation { target: countInText; property: "scale"; from: 0.8; to: 1.2; duration: 50; easing.type: Easing.OutQuad }
                    NumberAnimation { target: countInText; property: "scale"; to: 1.0; duration: 200; easing.type: Easing.InQuad }
                }
            }
        }
    }

    // Reconnecting Overlay — appears over exercise content when AI drops mid-lesson
    Rectangle {
        anchors.fill: parent
        color: "#CC111111"
        visible: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false
        z: 200
        onVisibleChanged: {
            var d = new Date();
            var timeStr = d.getHours().toString().padStart(2,'0') + ":" + d.getMinutes().toString().padStart(2,'0') + ":" + d.getSeconds().toString().padStart(2,'0') + "." + d.getMilliseconds().toString().padStart(3,'0');
            console.log("[TIMING " + timeStr + "] QML Reconnecting Overlay visible: " + visible);
        }

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 30 * mainWindow.uiScale

            // Pulsing WiFi/connection indicator
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 80 * mainWindow.uiScale
                height: 80 * mainWindow.uiScale
                radius: 40 * mainWindow.uiScale
                color: "transparent"
                border.width: 3 * mainWindow.uiScale
                border.color: "#FFC107"

                SequentialAnimation on scale {
                    loops: Animation.Infinite
                    running: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false
                    NumberAnimation { from: 0.6; to: 1.4; duration: 1500; easing.type: Easing.OutCubic }
                }
                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false
                    NumberAnimation { from: 1.0; to: 0.0; duration: 1500; easing.type: Easing.OutCubic }
                }

                // Inner icon dot
                Rectangle {
                    anchors.centerIn: parent
                    width: 20 * mainWindow.uiScale
                    height: 20 * mainWindow.uiScale
                    radius: 10 * mainWindow.uiScale
                    color: "#FFC107"

                    SequentialAnimation on scale {
                        loops: Animation.Infinite
                        running: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false
                        NumberAnimation { from: 0.8; to: 1.2; duration: 750; easing.type: Easing.InOutSine }
                        NumberAnimation { from: 1.2; to: 0.8; duration: 750; easing.type: Easing.InOutSine }
                    }
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "RECONNECTING TO YOUR COACH..."
                color: "#FFC107"
                font.pixelSize: 18 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 4 * mainWindow.uiScale

                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false
                    NumberAnimation { from: 0.4; to: 1.0; duration: 1000; easing.type: Easing.InOutSine }
                    NumberAnimation { from: 1.0; to: 0.4; duration: 1000; easing.type: Easing.InOutSine }
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Your lesson will resume automatically."
                color: "#999999"
                font.pixelSize: 14 * mainWindow.uiScale
            }
        }
    }

    // Large Central Timing Feedback (for Pentascales)
    Text {
        id: centralFeedbackText
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -50 * mainWindow.uiScale
        font.pixelSize: 64 * mainWindow.uiScale
        font.bold: true
        font.letterSpacing: 4 * mainWindow.uiScale
        color: {
            if (text === "Perfect!") return "#4CAF50";
            if (text === "Fast") return "#FFC107";
            if (text === "Slow") return "#FF9800";
            return "white";
        }
        visible: opacity > 0
        opacity: 0
        z: 150
        
        style: Text.Outline
        styleColor: "black"
        
        SequentialAnimation {
            id: centralFeedbackAnim
            NumberAnimation { target: centralFeedbackText; property: "opacity"; from: 0; to: 1; duration: 100 }
            NumberAnimation { target: centralFeedbackText; property: "scale"; from: 1.5; to: 1.0; duration: 200; easing.type: Easing.OutBack }
            PauseAnimation { duration: 400 }
            NumberAnimation { target: centralFeedbackText; property: "opacity"; to: 0; duration: 300 }
        }
    }

    // --- Error Toast Notification ---
    Rectangle {
        id: errorToast
        anchors.top: parent.top
        anchors.topMargin: 20 * mainWindow.uiScale
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(600 * mainWindow.uiScale, parent.width * 0.8)
        height: 60 * mainWindow.uiScale
        radius: 8 * mainWindow.uiScale
        color: "#f44336"
        opacity: 0.0
        z: 999
        
        RowLayout {
            anchors.fill: parent
            anchors.margins: 15 * mainWindow.uiScale
            spacing: 12 * mainWindow.uiScale
            
            Text {
                text: "⚠"
                color: "white"
                font.pixelSize: 24 * mainWindow.uiScale
                font.bold: true
            }
            
            Text {
                id: errorToastText
                Layout.fillWidth: true
                text: ""
                color: "white"
                font.pixelSize: 16 * mainWindow.uiScale
                font.bold: true
                wrapMode: Text.WordWrap
            }
        }
        
        SequentialAnimation on opacity {
            id: errorToastAnim
            running: false
            NumberAnimation { to: 1.0; duration: 200; easing.type: Easing.OutQuad }
            PauseAnimation { duration: 4000 }
            NumberAnimation { to: 0.0; duration: 500; easing.type: Easing.InQuad }
        }
        
        // Shadow for depth
        layer.enabled: true
        layer.effect: DropShadow {
            transparentBorder: true
            horizontalOffset: 0
            verticalOffset: 4 * mainWindow.uiScale
            radius: 12 * mainWindow.uiScale
            samples: 25
            color: "#80000000"
        }
    }
}
