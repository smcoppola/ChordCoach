import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#121212"
    
    signal startLesson()
    signal startReview()
    signal freePractice()

    ColumnLayout {
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
                onClicked: root.startLesson()
            }
            
            // 2. Quick Review (Conditional)
            ActionCard {
                title: "Quick Review"
                description: "Practice the items you struggled with today."
                icon: "🎯"
                accentColor: "#FF9800"
                enabled: appState && appState.chordTrainer && appState.chordTrainer.struggledItems.length > 0
                opacity: enabled ? 1.0 : 0.4
                onClicked: root.startReview()
                
                Rectangle {
                    parent: parent
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: -8
                    width: 24; height: 24; radius: 12
                    color: "#F44336"
                    visible: appState.chordTrainer.struggledItems.length > 0
                    
                    Text {
                        anchors.centerIn: parent
                        text: appState.chordTrainer.struggledItems.length
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
        
        // ── Performance Summary ──
        ColumnLayout {
            Layout.fillWidth: true
            Layout.maximumWidth: 800 * mainWindow.uiScale
            Layout.alignment: Qt.AlignHCenter
            spacing: 16
            visible: appState.chordTrainer.struggledItems.length > 0
            
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
                    model: appState.chordTrainer.struggledItems
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
}
