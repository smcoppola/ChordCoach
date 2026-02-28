import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "." as Components

Rectangle {
    id: root
    color: "#000000"
    opacity: 0.0
    visible: false
    z: 1000
    
    signal completed()
    
    property int phase: 0  // 0=welcome, 1=evaluation, 2=results, 3=arch_tutorial
    property bool isRunning: false
    
    property var evalEngine: {
        if (typeof appState !== "undefined" && appState !== null && appState.evaluationEngine)
            return appState.evaluationEngine;
        return null;
    }
    
    function show() {
        root.visible = true;
        root.phase = 0;
        showAnim.start();
    }
    
    function hide() {
        hideAnim.start();
    }
    
    NumberAnimation {
        id: showAnim
        target: root
        property: "opacity"
        from: 0.0; to: 1.0
        duration: 400
        easing.type: Easing.OutQuad
    }
    
    NumberAnimation {
        id: hideAnim
        target: root
        property: "opacity"
        from: 1.0; to: 0.0
        duration: 300
        easing.type: Easing.InQuad
        onFinished: {
            root.visible = false;
            root.completed();
        }
    }

    // Listen for evaluation finish
    Connections {
        target: root.evalEngine
        function onEvaluationFinished() {
            root.phase = 2;
            root.isRunning = false;
        }
        function onLevelChanged() {
            // Force QML to re-read properties when level changes
            root.isRunning = true;
        }
    }

    // Direct listener for appState signals to ensure UI update
    Connections {
        target: (typeof appState !== "undefined") ? appState : null
        function onEvalIntroPendingChanged() {
            // Force re-evaluation of bindings dependent on appState
            root.isRunning = !root.isRunning;
            root.isRunning = !root.isRunning;
        }
    }

    // ── Phase 0: Welcome Screen ──
    Item {
        anchors.fill: parent
        visible: root.phase === 0
        
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 30
            width: Math.min(parent.width * 0.8, 500)
            
            Text {
                text: "🎹"
                font.pixelSize: 72 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                text: "Welcome to ChordCoach"
                color: "#ffffff"
                font.pixelSize: 32 * mainWindow.uiScale
                font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                text: "Let's find out where you are! You'll play along with short melodies that scroll across the screen. We'll start easy and ramp up until we find your level."
                color: "#aaaaaa"
                font.pixelSize: 15 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                lineHeight: 1.4
                horizontalAlignment: Text.AlignHCenter
            }
            
            Item { Layout.preferredHeight: 10 }
            
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 260 * mainWindow.uiScale
                Layout.preferredHeight: 54 * mainWindow.uiScale
                radius: 27 * mainWindow.uiScale
                color: beginMA.containsMouse ? "#1E88E5" : "#2196F3"
                
                Text {
                    anchors.centerIn: parent
                    text: "Begin Evaluation"
                    color: "#ffffff"
                    font.pixelSize: 16 * mainWindow.uiScale
                    font.bold: true
                }
                
                MouseArea {
                    id: beginMA
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.phase = 1;
                        root.isRunning = true;
                        if (typeof appState !== "undefined" && appState !== null) {
                            appState.startEvaluationWithIntro();
                        }
                    }
                }
            }
            
            // Skip option
            Text {
                text: "Skip for now →"
                color: "#666666"
                font.pixelSize: 13 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
                
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.hide()
                }
            }
        }
    }
    
    // ── Phase 1: Scrolling Sheet Music Evaluation ──
    Item {
        anchors.fill: parent
        visible: root.phase === 1
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 40
            spacing: 30

            // ── The "Green Box" Level Card (aligned with ChordFormulaCard design) ──
            Rectangle {
                id: levelCard
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.maximumWidth: 600 * mainWindow.uiScale
                Layout.preferredHeight: 120 * mainWindow.uiScale
                color: "#222222"
                radius: 8 * mainWindow.uiScale
                border.color: "#4CAF50" // Success green
                border.width: 1 // Keep border width thin
                
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 15
                    spacing: 5
                    
                    // AI Intro Status (Consistent with Sidebar)
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        visible: (typeof appState !== "undefined" && appState !== null) && appState.evalIntroPending
                        spacing: 10 * mainWindow.uiScale
                        
                        Rectangle {
                            width: 12 * mainWindow.uiScale; height: 12 * mainWindow.uiScale; radius: 6 * mainWindow.uiScale
                            color: "#2196F3"
                            
                            SequentialAnimation on opacity {
                                running: parent.visible
                                loops: Animation.Infinite
                                NumberAnimation { from: 0.3; to: 1.0; duration: 800; easing.type: Easing.InOutSine }
                                NumberAnimation { from: 1.0; to: 0.3; duration: 800; easing.type: Easing.InOutSine }
                            }
                        }
                        
                        Text {
                            text: "Preparing your evaluation..."
                            color: "#2196F3"
                            font.pixelSize: 15 * mainWindow.uiScale
                            font.bold: true
                        }
                    }
                    
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: root.evalEngine ? ("LEVEL " + root.evalEngine.currentLevel) : "EVALUATION"
                        visible: (typeof appState !== "undefined" && appState !== null) && !appState.evalIntroPending
                        font.pixelSize: 14 * mainWindow.uiScale
                        font.bold: true
                        font.letterSpacing: 2 * mainWindow.uiScale
                        color: "#4CAF50"
                    }
                    
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.fillWidth: true
                        text: root.evalEngine ? root.evalEngine.sequenceTitle : "Waiting..."
                        visible: (typeof appState !== "undefined" && appState !== null) && !appState.evalIntroPending
                        font.pixelSize: 26 * mainWindow.uiScale
                        font.bold: true
                        color: "#FFFFFF"
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                    }
                    
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: 5 * mainWindow.uiScale
                        text: {
                            var acc = root.evalEngine ? Math.round(root.evalEngine.accuracy * 100) : 0;
                            return "Accuracy: " + acc + "% — Keep following the scrolling notes!";
                        }
                        font.pixelSize: 12 * mainWindow.uiScale
                        color: "#888888"
                        font.italic: true
                        visible: (typeof appState !== "undefined" && appState !== null) && !appState.evalIntroPending
                    }
                }

                // Accuracy corner indicator (optional, but nice)
                Text {
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 12
                    visible: root.evalEngine && root.evalEngine.accuracy > 0
                    text: root.evalEngine ? (Math.round(root.evalEngine.accuracy * 100) + "%") : ""
                    color: {
                        if (!root.evalEngine) return "#888888";
                        if (root.evalEngine.accuracy >= 0.70) return "#4CAF50";
                        if (root.evalEngine.accuracy >= 0.60) return "#FFC107";
                        return "#F44336";
                    }
                    font.pixelSize: 18 * mainWindow.uiScale
                    font.bold: true
                }
            }

            // The scrolling sheet music (Now constrained to match lesson view height)
            Components.EnhancedSheetMusic {
                id: evalStaff
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                Layout.maximumWidth: 1050 * mainWindow.uiScale
                Layout.preferredHeight: 350 * mainWindow.uiScale
                Layout.minimumHeight: 350 * mainWindow.uiScale
                
                displayMode: "evaluation"
                evalNotes: root.evalEngine ? root.evalEngine.sequenceNotes : []
                evalBeat: root.evalEngine ? root.evalEngine.currentBeat : 0
                evalNoteStates: root.evalEngine ? root.evalEngine.noteStates : []
            }

            // Control Buttons
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: 60 * mainWindow.uiScale
                Layout.fillWidth: false
                spacing: 20 * mainWindow.uiScale
                visible: root.phase === 1 && (typeof appState !== "undefined" && appState !== null)
                
                // Pause/Resume Button
                Rectangle {
                    Layout.preferredWidth: 160 * mainWindow.uiScale
                    Layout.preferredHeight: 44 * mainWindow.uiScale
                    radius: 22 * mainWindow.uiScale
                    color: pauseMA.containsMouse ? "#444444" : "#333333"
                    border.color: "#666666"
                    border.width: 1

                    Text {
                        anchors.centerIn: parent
                        text: (root.evalEngine && root.evalEngine.paused) ? "▶  Resume" : "⏸  Pause"
                        color: "#ffffff"
                        font.pixelSize: 14 * mainWindow.uiScale
                        font.bold: true
                    }

                    MouseArea {
                        id: pauseMA
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.evalEngine) root.evalEngine.togglePause();
                        }
                    }
                }

                // Restart Level Button
                Rectangle {
                    Layout.preferredWidth: 160 * mainWindow.uiScale
                    Layout.preferredHeight: 44 * mainWindow.uiScale
                    radius: 22 * mainWindow.uiScale
                    color: restartMA.containsMouse ? "#444444" : "#333333"
                    border.color: "#666666"
                    border.width: 1

                    Text {
                        anchors.centerIn: parent
                        text: "↺  Restart Level"
                        color: "#ffffff"
                        font.pixelSize: 14 * mainWindow.uiScale
                        font.bold: true
                    }

                    MouseArea {
                        id: restartMA
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.evalEngine) root.evalEngine.restartLevel();
                        }
                    }
                }
            }
            
            Item { Layout.fillHeight: true } // Spacer
        }
    }
    
    // ── Phase 2: Results ──
    Item {
        anchors.fill: parent
        visible: root.phase === 2
        
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 25
            width: Math.min(parent.width * 0.8, 500)
            
            Text {
                text: "✓"
                color: "#4CAF50"
                font.pixelSize: 72 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                text: "Evaluation Complete!"
                color: "#ffffff"
                font.pixelSize: 28 * mainWindow.uiScale
                font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                property int level: root.evalEngine ? root.evalEngine.assessedLevel : 0
                text: {
                    if (level === 0) return "We'll start you off with the basics. Don't worry — everyone starts somewhere!";
                    if (level <= 2) return "You're at Level " + level + " — solid beginner foundation. Let's build your chord vocabulary!";
                    if (level <= 4) return "You're at Level " + level + " — nice right-hand skills! Time to add some complexity.";
                    if (level <= 6) return "You're at Level " + level + " — impressive two-hand coordination! Let's push further.";
                    return "You're at Level " + level + " — advanced player! Let's work on mastery and speed.";
                }
                color: "#aaaaaa"
                font.pixelSize: 15 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                lineHeight: 1.4
                horizontalAlignment: Text.AlignHCenter
            }
            
            Item { Layout.preferredHeight: 10 * mainWindow.uiScale }
            
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 260 * mainWindow.uiScale
                Layout.preferredHeight: 54 * mainWindow.uiScale
                radius: 27 * mainWindow.uiScale
                color: startMA.containsMouse ? "#43A047" : "#4CAF50"
                
                Text {
                    anchors.centerIn: parent
                    text: "Start Learning"
                    color: "#ffffff"
                    font.pixelSize: 16 * mainWindow.uiScale
                    font.bold: true
                }
                
                MouseArea {
                    id: startMA
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.phase = 3;
                        if (typeof appState !== "undefined" && appState !== null) {
                            appState.startArchTutorialWithIntro();
                        }
                    }
                }
            }
        }
    }
    
    // ── Phase 3: Keyboard Arches Tutorial ──
    Item {
        anchors.fill: parent
        visible: root.phase === 3
        
        property bool archHasBeenClicked: false
        
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 30
            width: Math.min(parent.width * 0.9, 800)
            
            Text {
                text: "The Virtual Keyboard"
                color: "#ffffff"
                font.pixelSize: 28 * mainWindow.uiScale
                font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                text: "During lessons, the keyboard shows the notes you need to play. The <font color='#4CAF50'><b>green arches</b></font> above the keys show the musical interval—the number of half-steps between the notes."
                color: "#aaaaaa"
                font.pixelSize: 16 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                lineHeight: 1.5
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.RichText
            }
            
            Text {
                text: "Try clicking an arch below to see its interval name!"
                color: "#2196F3"
                font.pixelSize: 16 * mainWindow.uiScale
                font.bold: true
                font.italic: true
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 10 * mainWindow.uiScale
            }
            
            Item { Layout.preferredHeight: 15 * mainWindow.uiScale }
            
            Components.VisualKeyboard {
                id: tutorialKeyboard
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: parent.width
                Layout.preferredHeight: 150 * mainWindow.uiScale
                targetKeys: [60, 64, 67] // C Major Chord (C4, E4, G4)
                
                onArchClicked: {
                    parent.parent.archHasBeenClicked = true;
                }
            }
            
            Item { Layout.preferredHeight: 15 * mainWindow.uiScale }
            
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 260 * mainWindow.uiScale
                Layout.preferredHeight: 54 * mainWindow.uiScale
                radius: 27 * mainWindow.uiScale
                color: finishMA.containsMouse ? "#43A047" : "#4CAF50"
                opacity: parent.parent.archHasBeenClicked ? 1.0 : 0.0
                visible: opacity > 0
                
                Behavior on opacity { NumberAnimation { duration: 400 } }
                
                Text {
                    anchors.centerIn: parent
                    text: "Finish Setup"
                    color: "#ffffff"
                    font.pixelSize: 16 * mainWindow.uiScale
                    font.bold: true
                }
                
                MouseArea {
                    id: finishMA
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.hide()
                }
            }
        }
    }
}
