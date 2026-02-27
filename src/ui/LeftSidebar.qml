import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#1a1a1a"
    
    signal openSettings()
    signal openOnboarding()

    // Vertical split line
    Rectangle {
        width: 1
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: "#333333"
    }
    
    // Data bindings
    property bool midiConnected: typeof appState !== "undefined" && appState && appState.midiConnected
    property string midiDevice: midiConnected ? appState.midiDeviceName : ""
    property bool aiConnected: typeof appState !== "undefined" && appState && appState.aiConnected
    property bool isLessonActive: typeof appState !== "undefined" && appState && appState.chordTrainer && appState.chordTrainer.isActive
    property bool isLessonMode: isLessonActive && appState.chordTrainer.isLessonMode
    property int lessonProgress: isLessonMode ? appState.chordTrainer.lessonProgress : 0
    property int lessonTotal: isLessonMode ? appState.chordTrainer.lessonTotal : 0
    property string exerciseName: isLessonMode ? appState.chordTrainer.exerciseName : ""
    property string exerciseType: isLessonActive ? (appState.chordTrainer.exerciseType || "chord") : "chord"
    
    // Stats from settings service
    property var chordStats: {
        if (typeof appState !== "undefined" && appState && appState.settingsService) {
            return appState.settingsService.chordStats || [];
        }
        return [];
    }
    
    Connections {
        target: (typeof appState !== "undefined" && appState) ? appState.chordTrainer : null
        function onLessonStateChanged() {
            if (appState && appState.chordTrainer) {
                root.isLessonActive = appState.chordTrainer.isActive;
                root.isLessonMode = appState.chordTrainer.isActive && appState.chordTrainer.isLessonMode;
                root.lessonProgress = appState.chordTrainer.lessonProgress;
                root.lessonTotal = appState.chordTrainer.lessonTotal;
                root.exerciseName = appState.chordTrainer.exerciseName;
                root.exerciseType = appState.chordTrainer.exerciseType || "chord";
            }
        }
        function onTargetChordChanged() {
            if (appState && appState.chordTrainer) {
                root.lessonProgress = appState.chordTrainer.lessonProgress;
            }
        }
    }
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20 * mainWindow.uiScale
        spacing: 0

        // ── App Title ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            
            Image {
                source: "../../resources/icon.png"
                Layout.preferredWidth: 36 * mainWindow.uiScale
                Layout.preferredHeight: 36 * mainWindow.uiScale
                fillMode: Image.PreserveAspectFit
                smooth: true
            }
            
            Text {
                text: "ChordCoach"
                color: "#ffffff"
                font.pixelSize: 20 * mainWindow.uiScale
                font.bold: true
            }
        }
        
        Text {
            text: "COMPANION"
            color: "#666666"
            font.pixelSize: 11 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 4 * mainWindow.uiScale
            Layout.leftMargin: 48 * mainWindow.uiScale
            Layout.topMargin: -4 * mainWindow.uiScale
        }
        
        Item { Layout.preferredHeight: 20 }
        
        Rectangle { Layout.fillWidth: true; height: 1; color: "#2a2a2a" }
        
        Item { Layout.preferredHeight: 16 * mainWindow.uiScale }

        // ── AI Coach Status ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 10 * mainWindow.uiScale
            
            Rectangle {
                width: 10 * mainWindow.uiScale; height: 10 * mainWindow.uiScale; radius: 5 * mainWindow.uiScale
                color: root.aiConnected ? "#4CAF50" : "#F44336"
                
                SequentialAnimation on opacity {
                    running: root.aiConnected
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.4; duration: 1500; easing.type: Easing.InOutSine }
                    NumberAnimation { to: 1.0; duration: 1500; easing.type: Easing.InOutSine }
                }
            }
            
            Text {
                text: root.aiConnected ? "AI Coach Connected" : "AI Coach Offline"
                color: root.aiConnected ? "#4CAF50" : "#F44336"
                font.pixelSize: 13 * mainWindow.uiScale
                font.bold: true
            }
        }
        
        Item { Layout.preferredHeight: 20 }

        // ── Current Lesson ──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: lessonContent.implicitHeight + 24
            color: root.isLessonMode ? "#1e2a1e" : "#222222"
            radius: 8
            border.color: root.isLessonMode ? "#4CAF5040" : "#333333"
            border.width: 1
            
            ColumnLayout {
                id: lessonContent
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                
                Text {
                    text: root.isLessonMode ? "CURRENT LESSON" : "SESSION"
                    color: "#888888"
                    font.pixelSize: 10 * mainWindow.uiScale
                    font.bold: true
                    font.letterSpacing: 2 * mainWindow.uiScale
                }
                
                Text {
                    text: root.isLessonMode ? root.exerciseName : (root.isLessonActive ? "Free Practice" : "Ready to begin")
                    color: "#ffffff"
                    font.pixelSize: 14 * mainWindow.uiScale
                    font.bold: true
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                
                // Progress bar
                Rectangle {
                    Layout.fillWidth: true
                    height: 6
                    radius: 3
                    color: "#333333"
                    visible: root.isLessonMode
                    
                    Rectangle {
                        width: root.lessonTotal > 0 ? parent.width * (root.lessonProgress / root.lessonTotal) : 0
                        height: parent.height
                        radius: 3
                        color: "#4CAF50"
                        
                        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutQuad } }
                    }
                }
                
                Text {
                    text: root.lessonProgress + " / " + root.lessonTotal + " steps"
                    color: "#888888"
                    font.pixelSize: 11 * mainWindow.uiScale
                    visible: root.isLessonMode
                }
            }
        }
        
        Item { Layout.preferredHeight: 16 }

        // ── Curriculum Progress ──
        Text {
            text: "CURRICULUM"
            color: "#888888"
            font.pixelSize: 10 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
        }
        
        Item { Layout.preferredHeight: 8 }
        
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: curriculumCol.implicitHeight + 24
            color: "#222222"
            radius: 8
            border.color: "#333333"
            border.width: 1
            
            ColumnLayout {
                id: curriculumCol
                anchors.fill: parent
                anchors.margins: 12
                spacing: 12
                
                // Active Milestones
                Repeater {
                    model: (typeof appState !== "undefined" && appState && appState.curriculumEngine) ? appState.curriculumEngine.activeMilestones : []
                    delegate: ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: modelData.track.toUpperCase()
                                color: "#666666"
                                font.pixelSize: 9 * mainWindow.uiScale
                                font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: Math.round((modelData.progress || 0) * 100) + "%"
                                color: "#888888"
                                font.pixelSize: 10 * mainWindow.uiScale
                            }
                        }
                        
                        Text {
                            text: modelData.title
                            color: "#ffffff"
                            font.pixelSize: 12 * mainWindow.uiScale
                            font.bold: true
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        
                        Rectangle {
                            Layout.fillWidth: true
                            height: 4
                            radius: 2
                            color: "#333333"
                            
                            Rectangle {
                                width: parent.width * (modelData.progress || 0)
                                height: parent.height
                                radius: 2
                                color: "#42A5F5" // Slightly different blue for curriculum
                                Behavior on width { NumberAnimation { duration: 300 } }
                            }
                        }
                    }
                }
                
                // Review Queue
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: "#333333"
                    visible: appState.curriculumEngine.reviewQueueCount > 0
                }
                
                RowLayout {
                    Layout.fillWidth: true
                    visible: appState.curriculumEngine.reviewQueueCount > 0
                    
                    Text {
                        text: "Reviews Due:"
                        color: "#888888"
                        font.pixelSize: 12 * mainWindow.uiScale
                    }
                    Item { Layout.fillWidth: true }
                    Rectangle {
                        width: 20 * mainWindow.uiScale; height: 18 * mainWindow.uiScale; radius: 4
                        color: "#FF9800"
                        Text {
                            anchors.centerIn: parent
                            text: appState.curriculumEngine.reviewQueueCount
                            color: "#000000"
                            font.pixelSize: 11 * mainWindow.uiScale
                            font.bold: true
                        }
                    }
                }
            }
        }
        
        Item { Layout.preferredHeight: 16 }

        // ── Skill Snapshot ──
        Text {
            text: "SKILL SNAPSHOT"
            color: "#888888"
            font.pixelSize: 10 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
        }
        
        Item { Layout.preferredHeight: 8 }
        
        // Stats summary
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: statsCol.implicitHeight + 24
            color: "#222222"
            radius: 8
            border.color: "#333333"
            border.width: 1
            
            ColumnLayout {
                id: statsCol
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6
                
                // Compute stats from chord data
                property int totalAttempts: {
                    var total = 0;
                    var stats = root.chordStats;
                    if (stats && stats.length) {
                        for (var i = 0; i < stats.length; i++) {
                            total += (stats[i].success_count || 0) + (stats[i].fail_count || 0);
                        }
                    }
                    return total;
                }
                property int totalSuccesses: {
                    var total = 0;
                    var stats = root.chordStats;
                    if (stats && stats.length) {
                        for (var i = 0; i < stats.length; i++) {
                            total += stats[i].success_count || 0;
                        }
                    }
                    return total;
                }
                property real accuracy: totalAttempts > 0 ? (totalSuccesses / totalAttempts * 100) : 0
                property int chordsLearned: {
                    var count = 0;
                    var stats = root.chordStats;
                    if (stats && stats.length) {
                        for (var i = 0; i < stats.length; i++) {
                            if ((stats[i].success_count || 0) >= 3) count++;
                        }
                    }
                    return count;
                }
                
                Row {
                    spacing: 8 * mainWindow.uiScale
                    Text { text: "Chords Learned:"; color: "#888888"; font.pixelSize: 12 * mainWindow.uiScale }
                    Text { text: statsCol.chordsLearned.toString(); color: "#ffffff"; font.pixelSize: 12 * mainWindow.uiScale; font.bold: true }
                }
                Row {
                    spacing: 8 * mainWindow.uiScale
                    Text { text: "Total Attempts:"; color: "#888888"; font.pixelSize: 12 * mainWindow.uiScale }
                    Text { text: statsCol.totalAttempts.toString(); color: "#ffffff"; font.pixelSize: 12 * mainWindow.uiScale; font.bold: true }
                }
                Row {
                    spacing: 8 * mainWindow.uiScale
                    Text { text: "Accuracy:"; color: "#888888"; font.pixelSize: 12 * mainWindow.uiScale }
                    Text { 
                        text: statsCol.totalAttempts > 0 ? statsCol.accuracy.toFixed(1) + "%" : "—"
                        color: statsCol.accuracy >= 80 ? "#4CAF50" : (statsCol.accuracy >= 50 ? "#FFC107" : "#F44336")
                        font.pixelSize: 12 * mainWindow.uiScale; font.bold: true 
                    }
                }
            }
        }
        
        Item { Layout.fillHeight: true }

        // ── Hardware Status ──
        Rectangle { Layout.fillWidth: true; height: 1; color: "#2a2a2a" }
        
        Item { Layout.preferredHeight: 12 }
        
        Text {
            text: "HARDWARE"
            color: "#666666"
            font.pixelSize: 10 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
        }
        
        Item { Layout.preferredHeight: 6 }
        
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            
            Rectangle {
                width: 8 * mainWindow.uiScale; height: 8 * mainWindow.uiScale; radius: 4 * mainWindow.uiScale
                color: root.midiConnected ? "#4CAF50" : "#F44336"
            }
            
            Text {
                text: root.midiConnected ? root.midiDevice : "No MIDI device"
                color: root.midiConnected ? "#cccccc" : "#888888"
                font.pixelSize: 12 * mainWindow.uiScale
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
        }
        
        Item { Layout.preferredHeight: 16 }
        
        // ── Bottom Actions ──
        Rectangle { Layout.fillWidth: true; height: 1; color: "#2a2a2a" }
        
        Item { Layout.preferredHeight: 12 }
        
        // Settings button
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 42
            color: settingsMA.containsMouse ? "#2a2a2a" : "transparent"
            radius: 8
            
            MouseArea {
                id: settingsMA
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openSettings()
            }
            
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 10
                
                Text {
                    text: "⚙"
                    font.pixelSize: 16 * mainWindow.uiScale
                    color: "#888888"
                }
                Text {
                    text: "Settings"
                    color: "#888888"
                    font.pixelSize: 13 * mainWindow.uiScale
                    font.bold: true
                    Layout.fillWidth: true
                }
            }
        }
    }
}
