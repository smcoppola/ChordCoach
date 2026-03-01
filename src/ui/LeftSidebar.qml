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

        // ── Curriculum Progress ──
        Text {
            text: "CURRICULUM"
            color: "#888888"
            font.pixelSize: 10 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
            visible: curriculumRepeater.count > 0
        }
        
        Item { Layout.preferredHeight: 8; visible: curriculumRepeater.count > 0 }
        
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: curriculumCol.implicitHeight + 24
            color: "#222222"
            radius: 8
            border.color: "#333333"
            border.width: 1
            visible: curriculumRepeater.count > 0
            
            ColumnLayout {
                id: curriculumCol
                anchors.fill: parent
                anchors.margins: 12
                spacing: 12
                
                // Active Milestones
                Repeater {
                    id: curriculumRepeater
                    model: typeof appState !== "undefined" && appState && appState.curriculumEngine ? appState.curriculumEngine.activeMilestones : []
                    
                    Connections {
                        target: typeof appState !== "undefined" && appState ? appState.curriculumEngine : null
                        function onCurriculumChanged() {
                            // Force QML to redraw the repeater when the Python dicts change
                            var freshData = appState.curriculumEngine.activeMilestones;
                            curriculumRepeater.model = null;
                            curriculumRepeater.model = freshData;
                        }
                    }
                    
                    delegate: ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: modelData["track"] ? modelData["track"].toUpperCase() : ""
                                color: "#666666"
                                font.pixelSize: 9 * mainWindow.uiScale
                                font.bold: true
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: Math.round((modelData["progress"] || 0) * 100) + "%"
                                color: "#888888"
                                font.pixelSize: 10 * mainWindow.uiScale
                            }
                        }
                        
                        Text {
                            text: modelData["title"] || ""
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
                                width: parent.width * (modelData["progress"] || 0)
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
