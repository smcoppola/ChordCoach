import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "transparent"

    signal recalibrateRequested()

    Flickable {
        anchors.fill: parent
        anchors.margins: 24 * mainWindow.uiScale
        contentHeight: settingsColumn.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    ColumnLayout {
        id: settingsColumn
        width: parent.width
        spacing: 20 * mainWindow.uiScale



        // API Key Section
        GroupBox {
            title: "Gemini AI Coach Settings"
            Layout.fillWidth: true
            
            ColumnLayout {
                anchors.fill: parent
                spacing: 15 * mainWindow.uiScale

                Text {
                    text: "Google Gemini API Key:"
                    color: "#888888"
                    font.pixelSize: 12 * mainWindow.uiScale
                }

                TextField {
                    id: apiKeyInput
                    Layout.fillWidth: true
                    placeholderText: "Enter your Google Gemini API Key"
                    echoMode: TextInput.Password
                    text: (typeof appState !== "undefined" && appState !== null && appState.settingsService) ? appState.settingsService.apiKey : ""
                }

                Button {
                    text: "Save API Key"
                    onClicked: {
                        if (typeof appState !== "undefined" && appState !== null && appState.settingsService) {
                            appState.settingsService.apiKey = apiKeyInput.text;
                            saveFeedback.start();
                        }
                    }
                }
                
                Text {
                    id: saveFeedbackText
                    text: "Saved!"
                    color: "#4CAF50"
                    opacity: 0.0
                    
                    SequentialAnimation on opacity {
                        id: saveFeedback
                        running: false
                        NumberAnimation { to: 1.0; duration: 200 }
                        PauseAnimation { duration: 1500 }
                        NumberAnimation { to: 0.0; duration: 500 }
                    }
                }
            }
        }

        // Coach Personality Section
        GroupBox {
            title: "Coach Personality"
            Layout.fillWidth: true
            
            ColumnLayout {
                anchors.fill: parent
                spacing: 15 * mainWindow.uiScale

                RowLayout {
                    spacing: 20 * mainWindow.uiScale
                    Layout.fillWidth: true

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Voice"; color: "#888888"; font.pixelSize: 12 * mainWindow.uiScale }
                        ComboBox {
                            id: voiceCombo
                            Layout.fillWidth: true
                            model: ["Puck", "Kore", "Charon", "Fenrir", "Aoede", "Leda"]
                            currentIndex: {
                                var v = (typeof appState !== "undefined" && appState !== null && appState.settingsService) ? appState.settingsService.coachVoice : "Kore";
                                return model.indexOf(v) >= 0 ? model.indexOf(v) : 2;
                            }
                            onActivated: {
                                if (typeof appState !== "undefined" && appState !== null && appState.settingsService)
                                    appState.settingsService.coachVoice = model[currentIndex];
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Brevity"; color: "#888888"; font.pixelSize: 12 * mainWindow.uiScale }
                        ComboBox {
                            id: brevityCombo
                            Layout.fillWidth: true
                            model: ["Detailed", "Normal", "Terse"]
                            currentIndex: {
                                var v = (typeof appState !== "undefined" && appState !== null && appState.settingsService) ? appState.settingsService.coachBrevity : "Normal";
                                return model.indexOf(v) >= 0 ? model.indexOf(v) : 1;
                            }
                            onActivated: {
                                if (typeof appState !== "undefined" && appState !== null && appState.settingsService)
                                    appState.settingsService.coachBrevity = model[currentIndex];
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Personality"; color: "#888888"; font.pixelSize: 12 * mainWindow.uiScale }
                        ComboBox {
                            id: personalityCombo
                            Layout.fillWidth: true
                            model: ["Balanced", "Encouraging", "Old-School"]
                            currentIndex: {
                                var v = (typeof appState !== "undefined" && appState !== null && appState.settingsService) ? appState.settingsService.coachPersonality : "Balanced";
                                return model.indexOf(v) >= 0 ? model.indexOf(v) : 0;
                            }
                            onActivated: {
                                if (typeof appState !== "undefined" && appState !== null && appState.settingsService)
                                    appState.settingsService.coachPersonality = model[currentIndex];
                            }
                        }
                    }
                }

                Text {
                    text: "Voice changes take effect on next session."
                    color: "#666666"
                    font.pixelSize: 11 * mainWindow.uiScale
                    font.italic: true
                }
            }
        }

        // Hardware Settings Section Removed


        // Skill Matrix Section
        GroupBox {
            title: "Skill Matrix Database"
            Layout.fillWidth: true
            Layout.preferredHeight: 400 * mainWindow.uiScale

            ColumnLayout {
                anchors.fill: parent
                spacing: 20 * mainWindow.uiScale

                TabBar {
                    id: statsTabs
                    Layout.fillWidth: true
                    background: Rectangle { color: "transparent" }
                    
                    TabButton {
                        text: "CHORD PROGRESS"
                        width: implicitWidth + 20 * mainWindow.uiScale
                    }
                    TabButton {
                        text: "SONG MASTERY"
                        width: implicitWidth + 20 * mainWindow.uiScale
                    }
                }

                StackLayout {
                    currentIndex: statsTabs.currentIndex
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    // Chord Stats View
                    ListView {
                        id: chordListView
                        clip: true
                        model: (typeof appState !== "undefined" && appState !== null && appState.settingsService) ? appState.settingsService.chordStats : []
                        spacing: 10 * mainWindow.uiScale
                        
                        delegate: Rectangle {
                            width: chordListView.width
                            height: 60 * mainWindow.uiScale
                            color: "#1a1a1a"
                            radius: 8 * mainWindow.uiScale
                            border.color: "#333333"

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 20
                                anchors.rightMargin: 20
                                spacing: 20

                                ColumnLayout {
                                    Layout.preferredWidth: 150 * mainWindow.uiScale
                                    Text {
                                        text: modelData.name
                                        color: "#ffffff"
                                        font.bold: true
                                        font.pixelSize: 16 * mainWindow.uiScale
                                    }
                                }

                                ColumnLayout {
                                    id: masteryColumn
                                    Layout.fillWidth: true
                                    
                                    property real successRate: (modelData.success_count + modelData.fail_count > 0) ? 
                                                               (modelData.success_count / (modelData.success_count + modelData.fail_count)) : 0

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text { 
                                            text: "Success Rate"
                                            color: "#aaaaaa"
                                            font.pixelSize: 12 * mainWindow.uiScale
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text { 
                                            text: (masteryColumn.successRate * 100).toFixed(0) + "%"
                                            color: masteryColumn.successRate > 0.8 ? "#4CAF50" : (masteryColumn.successRate > 0.5 ? "#FFC107" : "#F44336")
                                            font.bold: true
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: 6
                                        color: "#2a2a2a"
                                        radius: 3
                                        
                                        Rectangle {
                                            width: parent.width * masteryColumn.successRate
                                            height: parent.height
                                            color: masteryColumn.successRate > 0.8 ? "#4CAF50" : (masteryColumn.successRate > 0.5 ? "#FFC107" : "#F44336")
                                            radius: 3
                                            
                                            Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutQuad } }
                                        }
                                    }
                                }
                                
                                ColumnLayout {
                                    Layout.preferredWidth: 100 * mainWindow.uiScale
                                    Text {
                                        text: "Attempts: " + (modelData.success_count + modelData.fail_count)
                                        color: "#cccccc"
                                        font.pixelSize: 12 * mainWindow.uiScale
                                        Layout.alignment: Qt.AlignRight
                                    }
                                    Text {
                                        text: "Wrong Notes: " + modelData.total_wrong_notes
                                        color: "#888888"
                                        font.pixelSize: 11 * mainWindow.uiScale
                                        Layout.alignment: Qt.AlignRight
                                    }
                                }
                            }
                        }
                    }

                    // Song Stats View
                    ListView {
                        id: songListView
                        clip: true
                        model: (typeof appState !== "undefined" && appState !== null && appState.settingsService) ? appState.settingsService.songStats : []
                        spacing: 10 * mainWindow.uiScale
                        
                        delegate: Rectangle {
                            width: songListView.width
                            height: 60 * mainWindow.uiScale
                            color: "#1a1a1a"
                            radius: 8 * mainWindow.uiScale
                            border.color: "#333333"

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 20
                                anchors.rightMargin: 20
                                spacing: 20

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: modelData.title
                                        color: "#ffffff"
                                        font.bold: true
                                        font.pixelSize: 16 * mainWindow.uiScale
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        text: "Plays: " + modelData.play_count
                                        color: "#888888"
                                        font.pixelSize: 12 * mainWindow.uiScale
                                    }
                                }

                                ColumnLayout {
                                    Layout.preferredWidth: 200 * mainWindow.uiScale
                                    
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text { 
                                            text: "Mastery"
                                            color: "#aaaaaa"
                                            font.pixelSize: 12 * mainWindow.uiScale
                                        }
                                        Item { Layout.fillWidth: true }
                                        Text { 
                                            text: modelData.mastery_score.toFixed(1) + "%"
                                            color: "#2196F3"
                                            font.bold: true
                                        }
                                    }

                                    Rectangle {
                                        Layout.fillWidth: true
                                        height: 6 * mainWindow.uiScale
                                        color: "#2a2a2a"
                                        radius: 3 * mainWindow.uiScale
                                        
                                        Rectangle {
                                            width: parent.width * (modelData.mastery_score / 100)
                                            height: parent.height
                                            color: "#2196F3"
                                            radius: 3 * mainWindow.uiScale
                                            
                                            Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutQuad } }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10 * mainWindow.uiScale
                    
                    Item { Layout.fillWidth: true }
                    
                    Button {
                        text: "Recalibrate Baseline"
                        onClicked: root.recalibrateRequested()
                        
                        contentItem: Text {
                            text: parent.text
                            color: "#2196F3"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.bold: true
                            font.pixelSize: 14 * mainWindow.uiScale
                        }
                    }
                    
                    Button {
                        text: "Reset Progress"
                        onClicked: resetDialog.open()
                        
                        contentItem: Text {
                            text: parent.text
                            color: "#F44336"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.bold: true
                            font.pixelSize: 14 * mainWindow.uiScale
                        }
                    }
                }
            }
        }
    } // end ColumnLayout
    } // end Flickable

    Dialog {
        id: resetDialog
        title: "Reset Skill Matrix"
        standardButtons: Dialog.Yes | Dialog.No
        
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2

        Label {
            text: "Are you sure you want to reset all your chord progress? This cannot be undone."
            color: "#ffffff"
            padding: 20 * mainWindow.uiScale
            font.pixelSize: 14 * mainWindow.uiScale
            width: 300 * mainWindow.uiScale
            wrapMode: Text.WordWrap
        }

        onAccepted: {
            if (typeof appState !== "undefined" && appState !== null && appState.settingsService) {
                appState.settingsService.resetSkillMatrix();
            }
        }
    }
}
