import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import Qt5Compat.GraphicalEffects

Rectangle {
    id: root
    color: "#121212"
    
    function getColorForGrade(level) {
        if (!level) return "#666666";
        var match = level.match(/Grade (\d+)/);
        if (!match) return "#666666";
        var g = parseInt(match[1]);
        
        // Gradient: Green -> Yellow -> Orange -> Red
        var colors = [
            "#4CAF50", "#8BC34A", "#CDDC39", "#FFEB3B", "#FFC107",
            "#FF9800", "#FF5722", "#F44336", "#D32F2F", "#B71C1C"
        ];
        return colors[Math.max(0, Math.min(g-1, 9))];
    }
    
    signal startLesson(int minutes)
    signal startReview()
    signal freePractice()
    signal startSong(string pieceName)
    signal startSpecificDrill(string track, string milestoneId)

    // Imported songs get a difficulty chooser; catalog songs load directly
    function requestSongWithDifficulty(songId) {
        if (songId.indexOf("user::") === 0) {
            difficultyPicker.pendingSongId = songId;
            difficultyPicker.open();
        } else {
            appState.music21Service.mark_song_played(songId);
            songPicker.isLoadingSong = true;
            appState.music21Service.songRequested(songId);
        }
    }

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
            spacing: 8 * mainWindow.uiScale
            
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
                    anchors.margins: -8 * mainWindow.uiScale
                    width: 24 * mainWindow.uiScale; height: 24 * mainWindow.uiScale; radius: 12 * mainWindow.uiScale
                    color: "#F44336"
                    visible: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length > 0 : false
                    
                    Text {
                        anchors.centerIn: parent
                        text: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length : 0
                        color: "#ffffff"
                        font.bold: true
                        font.pixelSize: 12 * mainWindow.uiScale
                    }
                }
            }
            
            // 3. Specific Drill
            ActionCard {
                title: "Specific Drill"
                description: "Focused practice on a single technique or concept."
                icon: "🎯"
                accentColor: "#9C27B0"
                onClicked: drillPicker.open()
            }
            
            // 4. Free Practice
            ActionCard {
                title: "Free Play"
                description: "Play along with classic pieces at your own pace."
                icon: "🎹"
                accentColor: "#2196F3"
                enabled: true
                opacity: 1.0
                onClicked: {
                    songPicker.open()
                }
            }
        }
        // ── Curriculum Progress ──
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 800 * mainWindow.uiScale
            spacing: 16 * mainWindow.uiScale
            visible: (typeof appState !== "undefined" && appState !== null && appState.curriculumEngine) && appState.curriculumEngine.activeMilestones.length > 0
            
            Rectangle { Layout.fillWidth: true; height: Math.max(1, 1 * mainWindow.uiScale); color: "#2a2a2a" }
            
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
                        radius: 12 * mainWindow.uiScale
                        border.color: "#333333"
                        border.width: Math.max(1, 1 * mainWindow.uiScale)
                        
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 16 * mainWindow.uiScale
                            spacing: 8 * mainWindow.uiScale
                            
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
                                height: 4 * mainWindow.uiScale
                                radius: 2 * mainWindow.uiScale
                                color: "#333333"
                                
                                Rectangle {
                                    width: parent.width * (modelData["progress"] || 0)
                                    height: parent.height
                                    radius: 2 * mainWindow.uiScale
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
            spacing: 16 * mainWindow.uiScale
            visible: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems.length > 0 : false
            
            Rectangle { Layout.fillWidth: true; height: Math.max(1, 1 * mainWindow.uiScale); color: "#2a2a2a" }
            
            Text {
                text: "NEEDS ATTENTION"
                font.pixelSize: 12 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 2 * mainWindow.uiScale
                color: "#666666"
            }
            
            Flow {
                Layout.fillWidth: true
                spacing: 10 * mainWindow.uiScale
                Repeater {
                    model: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.struggledItems : []
                    delegate: Rectangle {
                        width: tagText.implicitWidth + (24 * mainWindow.uiScale)
                        height: 32 * mainWindow.uiScale
                        color: "#1c1c1e"
                        radius: 16 * mainWindow.uiScale
                        border.color: "#333333"
                        
                        Text {
                            id: tagText
                            anchors.centerIn: parent
                            text: modelData.name
                            color: "#cccccc"
                            font.pixelSize: 12 * mainWindow.uiScale
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
        radius: 16 * mainWindow.uiScale
        border.color: mouseArea.containsMouse ? accentColor : "#333333"
        border.width: mouseArea.containsMouse ? (2 * mainWindow.uiScale) : Math.max(1, 1 * mainWindow.uiScale)
        
        Behavior on border.color { ColorAnimation { duration: 200 } }
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24 * mainWindow.uiScale
            spacing: 12 * mainWindow.uiScale
            
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
            radius: 16 * mainWindow.uiScale
            border.color: "#4CAF50"
            border.width: Math.max(1, 1 * mainWindow.uiScale)

            Rectangle {
                anchors.fill: parent
                anchors.margins: -1 * mainWindow.uiScale
                radius: 16 * mainWindow.uiScale
                color: "transparent"
                border.color: "#4CAF50"
                border.width: 2 * mainWindow.uiScale
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
                        radius: 10 * mainWindow.uiScale
                        color: durationMouse.containsMouse ? "#4CAF50" : "#2a2a2a"
                        border.color: durationMouse.containsMouse ? "#66BB6A" : "#444444"
                        border.width: Math.max(1, 1 * mainWindow.uiScale)

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

    // ── Drill Picker Popup ──
    Popup {
        id: drillPicker
        anchors.centerIn: parent
        width: 520 * mainWindow.uiScale
        height: 520 * mainWindow.uiScale
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: "#1c1c1e"
            radius: 16 * mainWindow.uiScale
            border.color: "#9C27B0"
            border.width: Math.max(1, 1 * mainWindow.uiScale)

            Rectangle {
                anchors.fill: parent
                anchors.margins: -1 * mainWindow.uiScale
                radius: 16 * mainWindow.uiScale
                color: "transparent"
                border.color: "#9C27B0"
                border.width: 2 * mainWindow.uiScale
                opacity: 0.3
            }
        }

        contentItem: ColumnLayout {
            spacing: 24

            Text {
                text: "SELECT DRILL"
                font.pixelSize: 12 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 4 * mainWindow.uiScale
                color: "#666666"
                Layout.alignment: Qt.AlignHCenter
            }

            Text {
                text: "Which focused exercise do you want to run?"
                font.pixelSize: 18 * mainWindow.uiScale
                color: "#ffffff"
                Layout.alignment: Qt.AlignHCenter
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ColumnLayout {
                    width: drillPicker.width - 48 // Account for margins
                    spacing: 16
                    
                    Repeater {
                        model: (typeof appState !== "undefined" && appState !== null && appState.curriculumEngine) ? appState.curriculumEngine.drillsByTrack : []
                        
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            
                            // Track Header
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                Text {
                                    text: modelData.icon
                                    font.pixelSize: 16 * mainWindow.uiScale
                                }
                                Text {
                                    text: modelData.name.toUpperCase()
                                    font.pixelSize: 11 * mainWindow.uiScale
                                    font.bold: true
                                    font.letterSpacing: 2 * mainWindow.uiScale
                                    color: "#888888"
                                }
                            }
                            
                            // Drills in this track
                            Repeater {
                                model: modelData.drills
                                delegate: Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 45 * mainWindow.uiScale
                                    radius: 8 * mainWindow.uiScale
                                    color: itemMouse.containsMouse ? "#332244" : "#2a2a2a"
                                    border.color: itemMouse.containsMouse ? "#9C27B0" : "#444444"
                                    border.width: Math.max(1, 1 * mainWindow.uiScale)

                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData.label
                                        color: "#ffffff"
                                        font.pixelSize: 14 * mainWindow.uiScale
                                    }

                                    MouseArea {
                                        id: itemMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            drillPicker.close();
                                            root.startSpecificDrill(modelData.track, modelData.id);
                                        }
                                    }
                                }
                            }
                            
                            Item { Layout.preferredHeight: 12 * mainWindow.uiScale } // Section spacer
                        }
                    }
                }
            }
        }
    }

    // ── Difficulty Chooser for Imported Songs ──
    Popup {
        id: difficultyPicker
        anchors.centerIn: parent
        width: 340 * mainWindow.uiScale
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property string pendingSongId: ""

        function play(level) {
            var baseId = pendingSongId;
            appState.music21Service.mark_song_played(baseId);
            songPicker.isLoadingSong = true;
            appState.music21Service.songRequested(
                level > 0 ? baseId + "::L" + level : baseId);
            difficultyPicker.close();
        }

        background: Rectangle {
            color: "#1c1c1e"
            radius: 12 * mainWindow.uiScale
            border.color: "#4CAF50"
        }

        contentItem: ColumnLayout {
            spacing: 8

            Text {
                text: "CHOOSE DIFFICULTY"
                color: "#666666"
                font.pixelSize: 11 * mainWindow.uiScale
                font.bold: true
                font.letterSpacing: 3 * mainWindow.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 8 * mainWindow.uiScale
            }

            Repeater {
                model: [
                    { level: 0, label: "Original", desc: "No adjustment — play it as imported" },
                    { level: 4, label: "Level 4", desc: "Light touch: extreme stretches tamed" },
                    { level: 3, label: "Level 3", desc: "Smaller chords, easier reaches" },
                    { level: 2, label: "Level 2", desc: "Simple chords, thinned fast runs" },
                    { level: 1, label: "Level 1", desc: "Simplest: melody + bass, slow pace" }
                ]
                delegate: Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 52 * mainWindow.uiScale
                    Layout.leftMargin: 8 * mainWindow.uiScale
                    Layout.rightMargin: 8 * mainWindow.uiScale
                    radius: 8 * mainWindow.uiScale
                    color: levelMouse.containsMouse ? "#4CAF5020" : "#2a2a2a"
                    border.color: levelMouse.containsMouse ? "#4CAF50" : "#444444"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 8 * mainWindow.uiScale
                        spacing: 2
                        Text {
                            text: modelData.label
                            color: "white"
                            font.bold: true
                            font.pixelSize: 13 * mainWindow.uiScale
                        }
                        Text {
                            text: modelData.desc
                            color: "#888888"
                            font.pixelSize: 10 * mainWindow.uiScale
                        }
                    }

                    MouseArea {
                        id: levelMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: difficultyPicker.play(modelData.level)
                    }
                }
            }

            Item { Layout.preferredHeight: 4 * mainWindow.uiScale }
        }
    }

    // ── MIDI Import File Dialog ──
    FileDialog {
        id: midiImportDialog
        title: "Import a MIDI File"
        nameFilters: ["MIDI files (*.mid *.midi)"]
        onAccepted: {
            songPicker.importError = "";
            songPicker.isLoadingSong = true;
            // Async: importSucceeded / importFailed arrive via Connections below
            appState.music21Service.import_midi_file(selectedFile.toString());
        }
    }

    // ── Song Picker Popup (Hierarchical) ──
    Popup {
        id: songPicker
        anchors.centerIn: parent
        width: 520 * mainWindow.uiScale
        height: 600 * mainWindow.uiScale
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        
        property var catalogPath: []
        property string searchQuery: ""
        property bool isLoadingSong: false
        property string importError: ""

        onClosed: {
            isLoadingSong = false;
            catalogPath = [];
            searchQuery = "";
            importError = "";
        }

        // Auto-close once Python finishes parsing the score
        Connections {
            target: (typeof appState !== "undefined" && appState && appState.chordTrainer) ? appState.chordTrainer : null
            function onLessonStateChanged() {
                if (songPicker.isLoadingSong && !appState.chordTrainer.isLoading) {
                    songPicker.close();
                }
            }
        }

        // Background MIDI import results
        Connections {
            target: (typeof appState !== "undefined" && appState && appState.music21Service) ? appState.music21Service : null
            function onImportSucceeded(songId) {
                songPicker.isLoadingSong = false;
                root.requestSongWithDifficulty(songId);
            }
            function onImportFailed(error) {
                songPicker.isLoadingSong = false;
                songPicker.importError = "Import failed: " + error;
            }
        }

        background: Rectangle {
            color: "#1c1c1e"
            radius: 16 * mainWindow.uiScale
            border.color: "#2196F3"
            border.width: Math.max(1, 1 * mainWindow.uiScale)

            Rectangle {
                anchors.fill: parent
                anchors.margins: -1 * mainWindow.uiScale
                radius: 16 * mainWindow.uiScale
                color: "transparent"
                border.color: "#2196F3"
                border.width: 2 * mainWindow.uiScale
                opacity: 0.3
            }
        }

        contentItem: Item {
            // Main Catalog UI
            ColumnLayout {
                anchors.fill: parent
                spacing: 16
                visible: !!appState && !!appState.music21Service && appState.music21Service.isCorpusReady
                
                // Bridge the dashboard ID directly into the popup's content scope
                property var hostDashboard: root

                // Search bar
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 45 * mainWindow.uiScale
                    Layout.margins: 10 * mainWindow.uiScale
                    color: "#2a2a2a"
                    radius: 8 * mainWindow.uiScale
                    border.color: searchInput.activeFocus ? "#2196F3" : "#444444"
                    
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8 * mainWindow.uiScale
                        spacing: 12
                        
                        Text { 
                            text: "🔍"
                            font.pixelSize: 16 * mainWindow.uiScale
                            opacity: 0.6
                        }
                        
                        TextInput {
                            id: searchInput
                            Layout.fillWidth: true
                            color: "white"
                            font.pixelSize: 14 * mainWindow.uiScale
                            selectByMouse: true
                            text: songPicker.searchQuery
                            onTextChanged: songPicker.searchQuery = text
                            
                            Text {
                                text: "Search songs or composers..."
                                color: "#666666"
                                font.pixelSize: 14 * mainWindow.uiScale
                                visible: parent.text.length === 0 && !parent.activeFocus
                            }
                        }
                        
                        Text {
                            text: "✕"
                            font.pixelSize: 14 * mainWindow.uiScale
                            color: "#666666"
                            visible: songPicker.searchQuery.length > 0
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    searchInput.text = "";
                                    searchInput.forceActiveFocus();
                                }
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: importLabel.implicitWidth + 24 * mainWindow.uiScale
                            Layout.preferredHeight: 30 * mainWindow.uiScale
                            radius: 15 * mainWindow.uiScale
                            color: importMouse.containsMouse ? "#4CAF5030" : "transparent"
                            border.color: "#4CAF50"

                            Text {
                                id: importLabel
                                anchors.centerIn: parent
                                text: "⬆ IMPORT MIDI"
                                color: "#4CAF50"
                                font.bold: true
                                font.pixelSize: 10 * mainWindow.uiScale
                            }

                            MouseArea {
                                id: importMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: midiImportDialog.open()
                            }
                        }
                    }
                }

                // Import error banner
                Text {
                    visible: songPicker.importError.length > 0
                    text: "⚠ " + songPicker.importError
                    color: "#FF7043"
                    font.pixelSize: 12 * mainWindow.uiScale
                    Layout.alignment: Qt.AlignHCenter
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                }

                // Header Section
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    visible: songPicker.searchQuery.length === 0
                    
                    Text {
                        text: "REPERTOIRE CATALOG"
                        font.pixelSize: 12 * mainWindow.uiScale
                        font.bold: true
                        font.letterSpacing: 4 * mainWindow.uiScale
                        color: "#666666"
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Text {
                        text: songPicker.catalogPath.length === 0 ? "Choose Difficulty" : 
                              songPicker.catalogPath.length === 1 ? "Select Style" :
                              songPicker.catalogPath.length === 2 ? "Select Composer" : "Pick a Song"
                        font.pixelSize: 22 * mainWindow.uiScale
                        font.bold: true
                        color: "#ffffff"
                        Layout.alignment: Qt.AlignHCenter
                    }
                }
                
                // Search Results Header
                Text {
                    text: "SEARCH RESULTS"
                    font.pixelSize: 12 * mainWindow.uiScale
                    font.bold: true
                    font.letterSpacing: 4 * mainWindow.uiScale
                    color: "#2196F3"
                    Layout.alignment: Qt.AlignHCenter
                    visible: songPicker.searchQuery.length > 0
                }

                // Navigation / Breadcrumbs
                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40 * mainWindow.uiScale
                    visible: songPicker.catalogPath.length > 0 && songPicker.searchQuery.length === 0
                    
                    Rectangle {
                        width: 80 * mainWindow.uiScale
                        height: 30 * mainWindow.uiScale
                        radius: 15 * mainWindow.uiScale
                        color: backMouse.containsMouse ? "#333333" : "#2a2a2a"
                        border.color: "#444444"
                        
                        Text {
                            anchors.centerIn: parent
                            text: "← BACK"
                            color: "#2196F3"
                            font.bold: true
                            font.pixelSize: 11 * mainWindow.uiScale
                        }
                        
                        MouseArea {
                            id: backMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                var p = songPicker.catalogPath;
                                songPicker.catalogPath = p.slice(0, -1); // Force fresh reference
                            }
                        }
                    }
                        
                    Row {
                        spacing: 8
                        Layout.fillWidth: true
                        
                        // Recently Played Shelf (only at root level)
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: !!songPicker && songPicker.catalogPath.length === 0 && songPicker.searchQuery.length === 0 && !!appState && !!appState.music21Service && appState.music21Service.get_recent_songs().length > 0
                            spacing: 8
                            
                            Text {
                                text: "RECENTLY PLAYED"
                                color: "#666666"
                                font.pixelSize: 10 * mainWindow.uiScale
                                font.bold: true
                                Layout.leftMargin: 4
                            }
                            
                            RowLayout {
                                spacing: 12
                                Repeater {
                                    model: (!!appState && !!appState.music21Service) ? appState.music21Service.get_recent_songs() : []
                                    delegate: Rectangle {
                                        width: 140 * mainWindow.uiScale
                                        height: 80 * mainWindow.uiScale
                                        radius: 10 * mainWindow.uiScale
                                        color: recentMouse.containsMouse ? "#2196F315" : "#1a1a1a"
                                        border.color: recentMouse.containsMouse ? "#2196F3" : "#333333"
                                        
                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 10
                                            spacing: 2
                                            Text {
                                                text: modelData.title
                                                color: "white"
                                                font.pixelSize: 12 * mainWindow.uiScale
                                                font.bold: true
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            Text {
                                                text: modelData.artist
                                                color: "#888888"
                                                font.pixelSize: 10 * mainWindow.uiScale
                                                elide: Text.ElideRight
                                                Layout.fillWidth: true
                                            }
                                            Item { Layout.fillHeight: true }
                                            Rectangle {
                                                width: 50 * mainWindow.uiScale
                                                height: 14 * mainWindow.uiScale
                                                radius: 3 * mainWindow.uiScale
                                                color: root.getColorForGrade(modelData.level)
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: modelData.level
                                                    font.pixelSize: 8 * mainWindow.uiScale
                                                    color: "white"
                                                    font.bold: true
                                                }
                                            }
                                        }
                                        
                                        MouseArea {
                                            id: recentMouse
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                // Popup stays open — Connections block closes it when loading finishes
                                                root.requestSongWithDifficulty(modelData.id);
                                            }
                                        }
                                    }
                                }
                            }
                            
                            Item { Layout.preferredHeight: 15 } // Spacer
                            
                            Rectangle {
                                Layout.fillWidth: true
                                height: 1
                                color: "#333333"
                            }
                            
                            Item { Layout.preferredHeight: 10 } // Spacer
                        }

                        Repeater {
                            model: songPicker.catalogPath
                            delegate: Text {
                                text: modelData + (index < songPicker.catalogPath.length - 1 ? "  ›  " : "")
                                color: breadMouse.containsMouse ? "#ffffff" : "#666666"
                                font.pixelSize: 12 * mainWindow.uiScale
                                font.bold: index === songPicker.catalogPath.length - 1
                                
                                MouseArea {
                                    id: breadMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        songPicker.catalogPath = songPicker.catalogPath.slice(0, index + 1);
                                    }
                                }
                            }
                        }
                    }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    ColumnLayout {
                        width: songPicker.width - 48
                        spacing: 10
                        
                        Repeater {
                            model: {
                                if (!appState || !appState.music21Service) return [];
                                if (songPicker.searchQuery.length >= 2) {
                                    return appState.music21Service.search_catalog(songPicker.searchQuery);
                                }
                                return appState.music21Service.get_catalog_level(songPicker.catalogPath);
                            }
                            delegate: Rectangle {
                                id: catalogEntry
                                Layout.fillWidth: true
                                Layout.preferredHeight: (modelData.isCategory ? 50 : 70) * mainWindow.uiScale
                                radius: 8 * mainWindow.uiScale
                                color: entryMouse.containsMouse ? "#1a2a3a" : "#2a2a2a"
                                border.color: entryMouse.containsMouse ? "#2196F3" : "#444444"
                                border.width: 1

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 2

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            text: (!!modelData.isCategory ? "📁  " : "🎵  ") + (modelData.title || modelData.id || "")
                                            color: "#ffffff"
                                            font.pixelSize: (!!modelData.isCategory ? 16 : 14) * mainWindow.uiScale
                                            font.bold: true
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                        }
                                        
                                        // Item level tag for songs
                                        Rectangle {
                                            visible: !modelData.isCategory
                                            width: 75 * mainWindow.uiScale
                                            height: 22 * mainWindow.uiScale
                                            radius: 4 * mainWindow.uiScale
                                            color: root.getColorForGrade(modelData.level)
                                            Text {
                                                anchors.centerIn: parent
                                                text: modelData.level || ""
                                                color: "white"
                                                font.pixelSize: 10 * mainWindow.uiScale
                                                font.bold: true
                                            }
                                        }
                                        
                                        Text {
                                            visible: !!modelData.isCategory
                                            text: "→"
                                            color: "#444444"
                                            font.pixelSize: 18 * mainWindow.uiScale
                                        }
                                    }

                                    Text {
                                        visible: !modelData.isCategory
                                        text: modelData.artist || "Unknown Composer"
                                        color: "#888888"
                                        font.pixelSize: 11 * mainWindow.uiScale
                                        Layout.leftMargin: 26 * mainWindow.uiScale
                                        Layout.fillWidth: true
                                        elide: Text.ElideRight
                                    }
                                }

                                MouseArea {
                                    id: entryMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (!!modelData.isCategory) {
                                            var p = songPicker.catalogPath;
                                            songPicker.catalogPath = p.concat([modelData.id]);
                                        } else {
                                            console.log("Dashboard: Requesting song selection: " + modelData.id);
                                            if (typeof appState !== "undefined" && appState && appState.music21Service) {
                                                // Popup stays open — Connections block closes it when loading finishes
                                                root.requestSongWithDifficulty(modelData.id);
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        
                        Item { Layout.preferredHeight: 20 * mainWindow.uiScale }
                    }
                }
            }
            
            // ── Song Loading Overlay ──
            Rectangle {
                anchors.fill: parent
                color: "#1c1c1e"
                radius: 16 * mainWindow.uiScale
                visible: songPicker.isLoadingSong
                z: 200

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 28 * mainWindow.uiScale
                    width: parent.width * 0.75

                    // Spinning ring
                    Item {
                        Layout.alignment: Qt.AlignHCenter
                        width: 56 * mainWindow.uiScale
                        height: 56 * mainWindow.uiScale

                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width
                            height: parent.height
                            radius: width / 2
                            color: "transparent"
                            border.color: "#333333"
                            border.width: 4 * mainWindow.uiScale
                        }

                        Rectangle {
                            id: spinnerArc
                            anchors.centerIn: parent
                            width: parent.width
                            height: parent.height
                            radius: width / 2
                            color: "transparent"
                            border.color: "#2196F3"
                            border.width: 4 * mainWindow.uiScale
                            // Clip to quarter-circle to fake an arc
                            clip: true

                            RotationAnimator on rotation {
                                from: 0; to: 360
                                duration: 900
                                loops: Animation.Infinite
                                running: songPicker.isLoadingSong
                            }
                        }
                    }

                    Text {
                        text: "Loading Song..."
                        color: "#ffffff"
                        font.pixelSize: 20 * mainWindow.uiScale
                        font.bold: true
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Text {
                        text: "Parsing score — this takes a moment"
                        color: "#666666"
                        font.pixelSize: 13 * mainWindow.uiScale
                        Layout.alignment: Qt.AlignHCenter
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        Layout.fillWidth: true
                    }
                }
            }

            // ── Corpus Download Overlay ──
            Rectangle {
                anchors.fill: parent
                color: "#1c1c1e"
                visible: !!appState && !!appState.music21Service && !appState.music21Service.isCorpusReady
                radius: 16 * mainWindow.uiScale
                z: 100

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 24 * mainWindow.uiScale
                    width: parent.width * 0.8

                    Text {
                        text: "📁 REPERTOIRE CORPUS"
                        font.pixelSize: 12 * mainWindow.uiScale
                        font.bold: true
                        font.letterSpacing: 4 * mainWindow.uiScale
                        color: "#2196F3"
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Text {
                        text: "Core library assets missing"
                        font.pixelSize: 22 * mainWindow.uiScale
                        font.bold: true
                        color: "#ffffff"
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Text {
                        text: "To browse thousand of classical pieces and exercises, we need to download the music21 corpus (approx. 80MB)."
                        color: "#888888"
                        font.pixelSize: 14 * mainWindow.uiScale
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        visible: !!appState && !!appState.music21Service && appState.music21Service.corpusProgress === 0 && !appState.music21Service.hasCorpusError
                    }

                    // Progress Area
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 12 * mainWindow.uiScale
                        visible: !!appState && !!appState.music21Service && appState.music21Service.corpusProgress > 0 && !appState.music21Service.hasCorpusError

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 8 * mainWindow.uiScale
                            color: "#333333"
                            radius: 4 * mainWindow.uiScale
                            clip: true

                            Rectangle {
                                width: parent.width * (!!appState && !!appState.music21Service ? appState.music21Service.corpusProgress : 0)
                                height: parent.height
                                color: "#2196F3"
                                radius: 4 * mainWindow.uiScale
                                
                                Behavior on width { NumberAnimation { duration: 200 } }
                            }
                        }

                        Text {
                            text: ((!!appState && !!appState.music21Service) ? Math.floor(appState.music21Service.corpusProgress * 100) : 0) + "% Complete"
                            color: "#2196F3"
                            font.pixelSize: 14 * mainWindow.uiScale
                            font.bold: true
                            font.family: "Monospace"
                            Layout.alignment: Qt.AlignHCenter
                        }
                    }

                    // Status Text
                    Text {
                        text: (!!appState && !!appState.music21Service) ? appState.music21Service.corpusStatus : ""
                        color: (!!appState && !!appState.music21Service && appState.music21Service.hasCorpusError) ? "#FF5252" : "#666666"
                        font.pixelSize: 12 * mainWindow.uiScale
                        Layout.alignment: Qt.AlignHCenter
                    }

                    // Import error (imports work even without the corpus)
                    Text {
                        visible: songPicker.importError.length > 0
                        text: "⚠ " + songPicker.importError
                        color: "#FF7043"
                        font.pixelSize: 12 * mainWindow.uiScale
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }

                    // Action Buttons
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: 20 * mainWindow.uiScale

                        Button {
                            text: "Download Now"
                            visible: !!appState && !!appState.music21Service && appState.music21Service.corpusProgress === 0 && !appState.music21Service.hasCorpusError
                            onClicked: if (appState && appState.music21Service) appState.music21Service.trigger_corpus_download()
                            
                            contentItem: Text {
                                text: parent.text
                                color: "white"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            
                            background: Rectangle {
                                implicitWidth: 160 * mainWindow.uiScale
                                implicitHeight: 45 * mainWindow.uiScale
                                color: parent.pressed ? "#1976D2" : "#2196F3"
                                radius: 8 * mainWindow.uiScale
                            }
                        }

                        Button {
                            text: "Import MIDI Instead"
                            onClicked: midiImportDialog.open()

                            contentItem: Text {
                                text: parent.text
                                color: "#4CAF50"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            background: Rectangle {
                                implicitWidth: 160 * mainWindow.uiScale
                                implicitHeight: 45 * mainWindow.uiScale
                                color: parent.pressed ? "#4CAF5030" : "transparent"
                                border.color: "#4CAF50"
                                radius: 8 * mainWindow.uiScale
                            }
                        }

                        Button {
                            text: "Retry Download"
                            visible: !!appState && !!appState.music21Service && appState.music21Service.hasCorpusError
                            onClicked: if (appState && appState.music21Service) appState.music21Service.trigger_corpus_download()
                            
                            contentItem: Text {
                                text: parent.text
                                color: "white"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            
                            background: Rectangle {
                                implicitWidth: 160 * mainWindow.uiScale
                                implicitHeight: 45 * mainWindow.uiScale
                                color: parent.pressed ? "#D32F2F" : "#F44336"
                                radius: 8 * mainWindow.uiScale
                            }
                        }
                    }
                }
            }
        }
    }
}
