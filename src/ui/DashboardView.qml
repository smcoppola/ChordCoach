import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects

Rectangle {
    id: root
    color: "#121212"
    
    signal startLesson(int minutes)
    signal startReview()
    signal freePractice()

    layer.enabled: durationPicker.visible

    FastBlur {
        anchors.fill: dashboardContent
        source: dashboardContent
        radius: durationPicker.visible ? (20 * mainWindow.uiScale) : 0
        visible: radius > 0
        z: 90
        Behavior on radius { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
    }

    ColumnLayout {
        id: dashboardContent
        anchors.centerIn: parent
        width: parent.width * 0.8
        spacing: 40 * mainWindow.uiScale
        
        // ── Header Section ──
        ColumnLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 8
            
            Text {
                text: "DASHBOARD"
                font.pixelSize: 14 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 4 * mainWindow.uiScale
                color: "#666666"
                Layout.alignment: Qt.AlignHCenter
            }
            
            Text {
                text: "Ready for your next session?"
                font.pixelSize: 32 * mainWindow.uiScale
                font.bold: true
                color: "#ffffff"
                Layout.alignment: Qt.AlignHCenter
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
        
        // ── Main Action Cards ──
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 24 * mainWindow.uiScale
            
            // 1. Generate New Lesson
            ActionCard {
                title: "Daily Lesson"
                description: "AI-generated plan based on your curriculum."
                icon: "✨"
                accentColor: "#4CAF50"
                onClicked: durationPicker.open()
            }
            
            // 2. Quick Review (Conditional)
            ActionCard {
                title: "Quick Review"
                description: "Practice the items you struggled with today."
                icon: "🎯"
                accentColor: "#FF9800"
                enabled: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length > 0 : false
                opacity: enabled ? 1.0 : 0.4
                onClicked: root.startReview()
                
                Rectangle {
                    parent: parent
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: -8
                    width: 24; height: 24; radius: 12
                    color: "#F44336"
                    visible: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length > 0 : false
                    
                    Text {
                        anchors.centerIn: parent
                        text: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length : 0
                        color: "#ffffff"
                        font.bold: true
                        font.pixelSize: 12
                    }
                }
            }
            
            // 3. Free Practice
            ActionCard {
                title: "Free Play"
                description: "Just jam. I'll listen and identify what you play. (Coming Soon)"
                icon: "🎹"
                accentColor: "#2196F3"
                enabled: false
                opacity: 0.4
                onClicked: {
                    if (enabled) {
                        root.freePractice()
                    }
                }
            }
        }
        // ── Curriculum Progress ──
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 800 * mainWindow.uiScale
            spacing: 16
            visible: (typeof appState !== "undefined" && appState !== null && appState.curriculumEngine) && appState.curriculumEngine.activeMilestones.length > 0
            
            Rectangle { Layout.fillWidth: true; height: 1; color: "#2a2a2a" }
            
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "YOUR CURRICULUM"
                    font.pixelSize: 12 * mainWindow.uiScale
                    font.bold: true
                    font.letterSpacing: 2 * mainWindow.uiScale
                    color: "#666666"
                }
                
                Item { Layout.fillWidth: true }
                
                Text {
                    text: "Reviews Due: " + ((typeof appState !== "undefined" && appState !== null && appState.curriculumEngine) ? appState.curriculumEngine.reviewQueueCount : 0)
                    color: "#FF9800"
                    font.pixelSize: 12 * mainWindow.uiScale
                    font.bold: true
                }
            }
            
            Flow {
                Layout.fillWidth: true
                spacing: 16 * mainWindow.uiScale
                
                Repeater {
                    id: dashboardCurriculumRepeater
                    model: (typeof appState !== "undefined" && appState !== null && appState.curriculumEngine) ? appState.curriculumEngine.activeMilestones : []
                    
                    Connections {
                        target: (typeof appState !== "undefined" && appState !== null) ? appState.curriculumEngine : null
                        function onCurriculumChanged() {
                            if (appState && appState.curriculumEngine) {
                                var freshData = appState.curriculumEngine.activeMilestones;
                                dashboardCurriculumRepeater.model = null;
                                dashboardCurriculumRepeater.model = freshData;
                            }
                        }
                    }
                    
                    delegate: Rectangle {
                        width: 250 * mainWindow.uiScale
                        height: 90 * mainWindow.uiScale
                        color: "#1c1c1e"
                        radius: 12
                        border.color: "#333333"
                        border.width: 1
                        
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 8
                            
                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    text: modelData["track"] ? modelData["track"].toUpperCase() : ""
                                    color: "#666666"
                                    font.pixelSize: 10 * mainWindow.uiScale
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
                                font.pixelSize: 14 * mainWindow.uiScale
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
                                    color: "#42A5F5"
                                    Behavior on width { NumberAnimation { duration: 300 } }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        // ── Performance Summary ──
        ColumnLayout {
            Layout.fillWidth: true
            Layout.maximumWidth: 800 * mainWindow.uiScale
            Layout.alignment: Qt.AlignHCenter
            spacing: 16
            visible: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length > 0 : false
            
            Rectangle { Layout.fillWidth: true; height: 1; color: "#2a2a2a" }
            
            Text {
                text: "NEEDS ATTENTION"
                font.pixelSize: 12 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 2 * mainWindow.uiScale
                color: "#666666"
            }
            
            Flow {
                Layout.fillWidth: true
                spacing: 10
                Repeater {
                    model: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems : []
                    delegate: Rectangle {
                        width: tagText.implicitWidth + 24
                        height: 32
                        color: "#1c1c1e"
                        radius: 16
                        border.color: "#333333"
                        
                        Text {
                            id: tagText
                            anchors.centerIn: parent
                            text: modelData.name
                            color: "#cccccc"
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
    
    // Internal Helper Component
    component ActionCard : Rectangle {
        property string title: ""
        property string description: ""
        property string icon: ""
        property color accentColor: "#ffffff"
        signal clicked()
        
        Layout.preferredWidth: 220 * mainWindow.uiScale
        Layout.preferredHeight: 180 * mainWindow.uiScale
        color: "#1c1c1e"
        radius: 16
        border.color: mouseArea.containsMouse ? accentColor : "#333333"
        border.width: mouseArea.containsMouse ? 2 : 1
        
        Behavior on border.color { ColorAnimation { duration: 200 } }
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12
            
            Text {
                text: icon
                font.pixelSize: 32 * mainWindow.uiScale
            }
            
            Text {
                text: title
                color: "#ffffff"
                font.pixelSize: 18 * mainWindow.uiScale
                font.bold: true
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            
            Text {
                text: description
                color: "#888888"
                font.pixelSize: 13 * mainWindow.uiScale
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                lineHeight: 1.2
            }
        }
        
        MouseArea {
            id: mouseArea
            anchors.fill: parent
            hoverEnabled: parent.enabled
            cursorShape: parent.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: {
                if (parent.enabled) {
                    parent.clicked()
                }
            }
        }
    }
    // ── Duration Picker Popup ──
    Popup {
        id: durationPicker
        anchors.centerIn: parent
        width: 520 * mainWindow.uiScale
        height: 280 * mainWindow.uiScale
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: "#1c1c1e"
            radius: 16
            border.color: "#4CAF50"
            border.width: 1

            Rectangle {
                anchors.fill: parent
                anchors.margins: -1
                radius: 16
                color: "transparent"
                border.color: "#4CAF50"
                border.width: 2
                opacity: 0.3
            }
        }

        contentItem: ColumnLayout {
            spacing: 24

            Text {
                text: "SESSION LENGTH"
                font.pixelSize: 12 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 4 * mainWindow.uiScale
                color: "#666666"
                Layout.alignment: Qt.AlignHCenter
            }

            Text {
                text: "How long would you like to practice?"
                font.pixelSize: 18 * mainWindow.uiScale
                color: "#ffffff"
                Layout.alignment: Qt.AlignHCenter
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 12 * mainWindow.uiScale

                Repeater {
                    model: [{"mins": 5, "label": "5 min"}, {"mins": 10, "label": "10 min"}, {"mins": 15, "label": "15 min"}, {"mins": 20, "label": "20 min"}]

                    delegate: Rectangle {
                        Layout.preferredWidth: 110 * mainWindow.uiScale
                        Layout.preferredHeight: 64 * mainWindow.uiScale
                        radius: 10
                        color: durationMouse.containsMouse ? "#4CAF50" : "#2a2a2a"
                        border.color: durationMouse.containsMouse ? "#66BB6A" : "#444444"
                        border.width: 1

                        Behavior on color { ColorAnimation { duration: 150 } }

                        Text {
                            anchors.centerIn: parent
                            text: modelData.label
                            color: durationMouse.containsMouse ? "#ffffff" : "#cccccc"
                            font.pixelSize: 16 * mainWindow.uiScale
                            font.bold: true
                        }

                        MouseArea {
                            id: durationMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                durationPicker.close();
                                root.startLesson(modelData.mins);
                            }
                        }
                    }
                }
            }
        }
    }
}
