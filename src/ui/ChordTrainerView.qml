import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "./components" as Components

Rectangle {
    id: root
    color: "transparent"
    
    property bool isActive: false
    property string currentTarget: ""
    
    // Lesson State Properties
    property string exerciseName: ""
    property int lessonProgress: 0
    property int lessonTotal: 0
    property bool isLessonComplete: false
    property bool isLessonMode: false
    property real holdProgress: 0.0
    property int requiredHoldMs: 0
    property bool isLoading: false
    property string loadingStatusText: ""
    property bool isPausedForSpeech: false
    
    // AI Coach State Properties
    property bool isAiSpeaking: false
    property string transcriptText: ""
    
    // Formula Properties
    property string chordType: ""
    property string formulaText: ""
    
    // New exercise type properties
    property string exerciseType: "chord"
    property var progressionNumerals: []
    property int currentProgressionIndex: 0
    property int currentNoteIndex: 0
    property string scaleName: ""

    Connections {
        target: (typeof appState !== "undefined" && appState !== null) ? appState : null
        function onAiTranscriptReceived(textMsg) {
            root.transcriptText = textMsg;
            root.isAiSpeaking = true;
            speakingTimer.restart();
        }
    }

    Timer {
        id: speakingTimer
        interval: 2500
        onTriggered: root.isAiSpeaking = false
    }
    
    Connections {
        target: (typeof appState !== "undefined" && appState) ? appState.chordTrainer : null
        function onActiveChanged(active) {
            root.isActive = active;
        }
        function onTargetChordChanged(chordName) {
            root.currentTarget = chordName;
            if (appState && appState.chordTrainer) {
                root.chordType = appState.chordTrainer.targetChordType;
                root.formulaText = appState.chordTrainer.targetFormulaText;
                root.currentNoteIndex = appState.chordTrainer.currentNoteIndex || 0;
                root.currentProgressionIndex = appState.chordTrainer.currentProgressionIndex || 0;
                root.scaleName = appState.chordTrainer.scaleName || "";
                
                var tp = appState.chordTrainer.targetPitches;
                var arr = [];
                if (tp) {
                    for (var i = 0; i < tp.length; i++) arr.push(tp[i]);
                }
                visualKeyboard.setTargetKeys(arr);
                
                console.log("ChordTrainerView updated -> type: '" + root.exerciseType + "', target: '" + root.currentTarget + "', keys: " + arr);
            }
        }
        function onChordSuccess(chordName, latencyMs) {
            // Flash background green on success
            successFlash.start();
            
            // Show latency briefly
            latencyText.text = "+" + Math.round(latencyMs) + "ms";
            latencyAnim.start();
        }
        function onChordFailed() {
            failFlash.start();
        }
        function onLessonStateChanged() {
            if (appState && appState.chordTrainer) {
                root.exerciseName = appState.chordTrainer.exerciseName;
                root.lessonProgress = appState.chordTrainer.lessonProgress;
                root.lessonTotal = appState.chordTrainer.lessonTotal;
                root.isLessonComplete = appState.chordTrainer.isLessonComplete;
                root.isLessonMode = appState.chordTrainer.isLessonMode;
                root.holdProgress = appState.chordTrainer.holdProgress;
                root.requiredHoldMs = appState.chordTrainer.requiredHoldMs;
                root.isLoading = appState.chordTrainer.isLoading;
                root.isPausedForSpeech = appState.chordTrainer.isPausedForSpeech;
                root.loadingStatusText = appState.chordTrainer.loadingStatusText;
                root.chordType = appState.chordTrainer.targetChordType;
                root.formulaText = appState.chordTrainer.targetFormulaText;
                root.exerciseType = appState.chordTrainer.exerciseType || "chord";
                var numerals = appState.chordTrainer.progressionNumerals;
                root.progressionNumerals = numerals ? numerals : [];
            }
        }
        function onLoadingStatusChanged() {
            if (appState && appState.chordTrainer) {
                root.loadingStatusText = appState.chordTrainer.loadingStatusText;
            }
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
        anchors.fill: parent
        anchors.margins: 40 * mainWindow.uiScale
        spacing: 30 * mainWindow.uiScale
        
        // Header Text
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: {
                if (!root.isActive) return "CHORD TRAINER";
                if (root.isLessonMode) return "LESSON: " + root.exerciseName.toUpperCase() + " (" + root.lessonProgress + " OF " + root.lessonTotal + ")";
                return "FREE PRACTICE";
            }
            color: root.isActive ? (root.isLessonMode ? "#2196F3" : "#888888") : "#ffffff"
            font.pixelSize: 18 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
        }
        
        // AI Coach Presenter
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 600 * mainWindow.uiScale
            spacing: 15 * mainWindow.uiScale
            visible: root.isActive && root.transcriptText.length > 0
            
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
                    border.width: root.isAiSpeaking ? 3 : 0
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
            isActive: root.isActive && !root.isLessonComplete
        }
        
        // Hold Progress Bar (Only visible during Rhythmic Locking)
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 300
            Layout.preferredHeight: 8
            radius: 4
            color: "#333333"
            visible: root.isActive && !root.isLessonComplete && root.requiredHoldMs > 0
            
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * root.holdProgress
                color: "#4CAF50"
                radius: 4
                
                // Add a smooth transition so it slides nicely even with 30fps timer tick
                Behavior on width {
                    NumberAnimation { duration: 50; easing.type: Easing.Linear }
                }
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
                    width: 60
                    height: 40
                    radius: 6
                    color: index === root.currentProgressionIndex ? "#2196F3" : "#333333"
                    border.color: index === root.currentProgressionIndex ? "#64B5F6" : "#555555"
                    border.width: index === root.currentProgressionIndex ? 2 : 1
                    
                    Text {
                        anchors.centerIn: parent
                        text: modelData
                        color: index === root.currentProgressionIndex ? "#ffffff" : "#888888"
                        font.pixelSize: 18
                        font.bold: index === root.currentProgressionIndex
                    }
                    
                    Behavior on color { ColorAnimation { duration: 200 } }
                }
            }
        }
        
        // Pentascale Note Progress Indicator  
        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 12 * mainWindow.uiScale
            visible: root.isActive && !root.isLessonComplete && root.exerciseType === "pentascale"
            
            Repeater {
                model: 5
                delegate: Rectangle {
                    width: 16
                    height: 16
                    radius: 8
                    color: index < root.currentNoteIndex ? "#4CAF50" : (index === root.currentNoteIndex ? "#2196F3" : "#333333")
                    border.color: index === root.currentNoteIndex ? "#64B5F6" : "transparent"
                    border.width: index === root.currentNoteIndex ? 2 : 0
                    
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
            }
        }
        
        // Lesson Complete screen overlay
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: 700 * mainWindow.uiScale
            Layout.fillHeight: true
            Layout.minimumHeight: 350 * mainWindow.uiScale
            color: "#1c1c1e"
            border.color: "#00BCD4"
            border.width: 1 * mainWindow.uiScale
            radius: 12 * mainWindow.uiScale
            visible: root.isActive && root.isLessonComplete
            
            // Subtle glow effect
            Rectangle {
                anchors.fill: parent
                anchors.margins: -1
                radius: 12
                color: "transparent"
                border.color: "#00BCD4"
                border.width: 2
                opacity: 0.3
            }
            
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 20
                
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
            }
        }
        
        // Center Loading Animation
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: "transparent"
            visible: !root.isActive && root.isLoading
            
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 40
                
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
            }
        }
        
        // Phase Complete screen overlay (Visible between exercises while AI speaks)
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: 700
            Layout.fillHeight: true
            Layout.minimumHeight: 350
            color: "#1c1c1e"
            border.color: "#00BCD4"
            border.width: 1
            radius: 12
            visible: root.isActive && root.isPausedForSpeech && !root.isLessonComplete
            
            // Subtle glow effect
            Rectangle {
                anchors.fill: parent
                anchors.margins: -1
                radius: 12
                color: "transparent"
                border.color: "#00BCD4"
                border.width: 2
                opacity: 0.3
            }
            
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 20
                
                Text {
                    text: root.lessonProgress <= 1 ? "GET READY" : "GREAT JOB!"
                    font.pixelSize: 42 * mainWindow.uiScale
                    font.bold: true
                    font.letterSpacing: 2 * mainWindow.uiScale
                    color: "#ffffff"
                    Layout.alignment: Qt.AlignHCenter
                    
                    SequentialAnimation on scale {
                        loops: Animation.Infinite
                        running: root.isActive && root.isPausedForSpeech && root.lessonProgress > 1
                        NumberAnimation { from: 1.0; to: 1.05; duration: 800; easing.type: Easing.InOutQuad }
                        NumberAnimation { from: 1.05; to: 1.0; duration: 800; easing.type: Easing.InOutQuad }
                    }
                }
                
                Text {
                    text: root.lessonProgress <= 1 ? "Listen to your coach's instructions." : "Preparing next exercise..."
                    font.pixelSize: 18 * mainWindow.uiScale
                    color: "#aaaaaa"
                    Layout.alignment: Qt.AlignHCenter
                }
            }
        }
        
        // Target display area - Enhanced Sheet Music
        Components.EnhancedSheetMusic {
            targetChordName: root.currentTarget
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: 700
            Layout.fillHeight: true
            Layout.minimumHeight: 350
            visible: root.isActive && !root.isLessonComplete && !root.isPausedForSpeech && root.exerciseType !== "listen"
            
            Text {
                id: latencyText
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 10
                text: ""
                color: "#4CAF50"
                font.pixelSize: 24 * mainWindow.uiScale
                font.bold: true
                opacity: 0.0
                
                SequentialAnimation on opacity {
                    id: latencyAnim
                    running: false
                    NumberAnimation { to: 1.0; duration: 50 }
                    PauseAnimation { duration: 1000 }
                    NumberAnimation { to: 0.0; duration: 500 }
                }
            }
        }
        
        // Ear Training Quiz View
        Rectangle {
            id: listenQuizView
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.maximumWidth: 700
            Layout.fillHeight: true
            Layout.minimumHeight: 350
            color: "#1c1c1e"
            radius: 12
            border.color: "#9C27B0" // Purple for ear training
            border.width: 1
            visible: root.isActive && !root.isLessonComplete && !root.isPausedForSpeech && root.exerciseType === "listen"
            
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 30
                
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
                    spacing: 20
                    
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
                                radius: 8
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
                    onClicked: appState.chordTrainer.replay_preview()
                    Layout.alignment: Qt.AlignHCenter
                }
            }
        }
        
        // Target display area - Interactive Keyboard
        Components.VisualKeyboard {
            id: visualKeyboard
            Layout.fillWidth: true
            Layout.preferredHeight: 180 * mainWindow.uiScale
            visible: root.isActive
        }
        
        Item { Layout.fillHeight: true } // Spacer
    }
}
