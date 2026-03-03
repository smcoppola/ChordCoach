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
    // Data bindings - Pure bindings to service properties
    property bool midiConnected: (typeof appState !== "undefined" && appState) ? appState.midiConnected : false
    property string midiDevice: midiConnected ? appState.midiDeviceName : "No MIDI device"
    property bool aiConnected: (typeof appState !== "undefined" && appState) ? appState.aiConnected : false
    property bool isLessonActive: (typeof appState !== "undefined" && appState && appState.chordTrainer) ? appState.chordTrainer.isActive : false
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
        // Manual updates removed here because properties now use direct bindings above.
        // This prevents "breaking" the bindings with explicit assignments.
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

        Item { Layout.preferredHeight: 16 }

        // ── Session Playlist (Only visible during active lessons) ──
        ColumnLayout {
            Layout.fillWidth: true
            visible: root.isLessonMode && typeof appState !== "undefined" && appState && appState.chordTrainer && appState.chordTrainer.lessonPlaylist && appState.chordTrainer.lessonPlaylist.length > 0
            spacing: 12
            
            Text {
                text: "SESSION PLAYLIST"
                color: "#888888"
                font.pixelSize: 10 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 2 * mainWindow.uiScale
            }
            
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: playlistCol.implicitHeight + 24
                color: "#222222"
                radius: 8
                border.color: "#333333"
                border.width: 1
                
                ColumnLayout {
                    id: playlistCol
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    
                    Repeater {
                        id: playlistRepeater
                        model: (typeof appState !== "undefined" && appState && appState.chordTrainer) ? appState.chordTrainer.lessonPlaylist : []
                        
                        delegate: RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            
                            // Status Indicator
                            Rectangle {
                                width: 12 * mainWindow.uiScale
                                height: 12 * mainWindow.uiScale
                                radius: 6 * mainWindow.uiScale
                                color: {
                                    if (index < root.lessonProgress - 1) return "#4CAF50"; // Done
                                    if (index === root.lessonProgress - 1) return "#2196F3"; // Active
                                    return "#444444"; // Pending
                                }
                                
                                // Pulse if active
                                SequentialAnimation on opacity {
                                    running: index === root.lessonProgress - 1 && !appState.chordTrainer.isPausedForSpeech
                                    loops: Animation.Infinite
                                    NumberAnimation { to: 0.4; duration: 1000; easing.type: Easing.InOutSine }
                                    NumberAnimation { to: 1.0; duration: 1000; easing.type: Easing.InOutSine }
                                }
                            }
                            
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                
                                Text {
                                    text: modelData.track ? modelData.track.toUpperCase() : ""
                                    color: index === root.lessonProgress - 1 ? "#64B5F6" : "#666666"
                                    font.pixelSize: 9 * mainWindow.uiScale
                                    font.bold: true
                                }
                                
                                Text {
                                    text: modelData.exercise_name || "Exercise"
                                    color: index === root.lessonProgress - 1 ? "#ffffff" : (index < root.lessonProgress - 1 ? "#aaaaaa" : "#888888")
                                    font.pixelSize: 12 * mainWindow.uiScale
                                    font.bold: index === root.lessonProgress - 1
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                    // Strikethrough completed items
                                    font.strikeout: index < root.lessonProgress - 1
                                }
                            }
                        }
                    }
                }
            }
        }
        
        Item { Layout.preferredHeight: 16 }

        // Replaced Skill Snapshot with just a spacer
        Item { Layout.preferredHeight: 16 }
        
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
