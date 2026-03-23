import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "./components" as Components

Rectangle {
    id: root
    color: "#121212"

    signal returnToDashboard()

    // ── Shared lesson state (mirrors ChordTrainerView) ──────────────────────
    property bool isActive: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isActive : false
    property bool isLoading: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isLoading : false
    property bool isLessonComplete: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isLessonComplete : false
    property bool isPausedForSpeech: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isPausedForSpeech : false
    property bool isWaitingForAi: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isWaitingForAi : false
    property bool isWaitingForUserContinue: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.isWaitingForUserContinue : false
    property string exerciseName: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.exerciseName : ""
    property string loadingStatusText: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.loadingStatusText : ""
    property real estimatedGenerationMs: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer.estimatedGenerationMs : 0.0
    property bool isReconnecting: (typeof appState !== "undefined" && appState !== null) ? appState.isReconnecting : false

    // ── Circle-specific state ────────────────────────────────────────────────
    property bool showCircle: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialShowBase : false
    property string highlightKey: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialHighlightKey : ""
    property bool showMajor: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialShowMajor : false
    property bool showMinor: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialShowMinor : false
    property var highlightedChords: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.highlightedChords : []
    property var arrows: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.arrows : []
    property int tutorialStage: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialStage : 0

    // ── AI transcript ────────────────────────────────────────────────────────
    property string transcriptText: ""
    property bool isAiSpeaking: isPausedForSpeech

    Connections {
        target: (typeof appState !== "undefined" && appState !== null) ? appState : null
        function onAiTranscriptReceived(textMsg) {
            root.transcriptText = textMsg;
        }
    }

    // ── Loading animation progress ───────────────────────────────────────────
    property real loadingProgress: 0.0
    NumberAnimation {
        id: loadingAnim
        target: root
        property: "loadingProgress"
        from: 0.0; to: 1.0
        duration: Math.max(1000, root.estimatedGenerationMs)
        easing.type: Easing.OutCubic
    }
    onIsLoadingChanged: {
        if (isLoading) { loadingProgress = 0.0; loadingAnim.restart(); }
        else { loadingAnim.stop(); loadingProgress = 0.0; }
    }

    // ── Success/Fail flash animation ─────────────────────────────────────────
    Rectangle {
        id: bgFlash
        anchors.fill: parent
        color: "transparent"
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

    // ── Signal Connections ───────────────────────────────────────────────────
    Connections {
        target: (typeof appState !== "undefined" && appState !== null) ? appState.chordTrainer : null
        
        function onChordFailed() {
            if (root.isActive) {
                failFlash.start();
            }
        }
        
        function onChordSuccess(chordName, latencyMs) {
            if (root.isActive) {
                successFlash.start();
                visualKeyboard.setTargetKeys([]); // Clear template guide on success
            }
        }

        function onMidiOutRequested(pitches) {
            if (root.isActive) {
                var arr = [];
                for (var i = 0; i < pitches.length; i++) {
                    arr.push(pitches[i]);
                }
                visualKeyboard.setTargetKeys(arr);
                // Removed clear timer to keep lit until played
            }
        }
    }

    // ── Main Layout ──────────────────────────────────────────────────────────
    ColumnLayout {
        id: mainLayout
        anchors.fill: parent
        anchors.margins: 32 * mainWindow.uiScale
        spacing: 16 * mainWindow.uiScale

        // ── Header ──────────────────────────────────────────────────────────
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: "CIRCLE OF FIFTHS"
            color: "#2196F3"
            font.pixelSize: 16 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 3 * mainWindow.uiScale
        }

        // ── AI Coach Transcript ──────────────────────────────────────────────
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.maximumWidth: 680 * mainWindow.uiScale
            spacing: 14 * mainWindow.uiScale
            visible: root.transcriptText.length > 0

            // Pulsing dot
            Rectangle {
                id: aiPulse
                Layout.alignment: Qt.AlignVCenter
                width: 12 * mainWindow.uiScale; height: 12 * mainWindow.uiScale
                radius: 6 * mainWindow.uiScale
                color: root.isAiSpeaking ? "#00BCD4" : "#444444"

                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 2; height: parent.height * 2
                    radius: width / 2
                    color: "transparent"
                    border.width: root.isAiSpeaking ? 3 : 0
                    border.color: "#00BCD4"
                    opacity: 0.0
                    SequentialAnimation on opacity {
                        running: root.isAiSpeaking
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.6; duration: 500 }
                        NumberAnimation { to: 0.0; duration: 500 }
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
                font.pixelSize: 17 * mainWindow.uiScale
                font.italic: true
                font.weight: root.isAiSpeaking ? Font.Bold : Font.Normal
                wrapMode: Text.WordWrap
                lineHeight: 1.3
            }
        }

        // ── Circle Canvas area (center hero) ─────────────────────────────────
        Item {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            Layout.fillHeight: true

            // The canvas itself — centered
            CircleCanvas {
                id: circleCanvas
                anchors.centerIn: parent
                size: Math.min(parent.width, parent.height) * 0.90
                showBase: root.showCircle
                showMajor: root.showMajor
                showMinor: root.showMinor
                highlightKey: root.highlightKey
                highlightedChords: root.highlightedChords
            }

            // Entrance shimmer when circle first appears
            Rectangle {
                anchors.centerIn: parent
                width: circleCanvas.width + 20
                height: circleCanvas.height + 20
                radius: width / 2
                color: "transparent"
                border.width: 2
                border.color: "#2196F3"
                opacity: 0.0
                visible: root.showCircle

                SequentialAnimation on opacity {
                    running: root.showCircle
                    NumberAnimation { to: 0.6; duration: 1000; easing.type: Easing.OutQuad }
                    NumberAnimation { to: 0.0; duration: 800; easing.type: Easing.InQuad }
                }
                SequentialAnimation on scale {
                    running: root.showCircle
                    NumberAnimation { from: 0.85; to: 1.05; duration: 1000; easing.type: Easing.OutQuad }
                    NumberAnimation { from: 1.05; to: 1.0; duration: 400 }
                }
            }

            // "Initializing..." placeholder shown before the circle appears
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 20
                visible: !root.showCircle && !root.isLoading

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "🎵"
                    font.pixelSize: 64 * mainWindow.uiScale
                }

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Preparing your lesson..."
                    color: "#555555"
                    font.pixelSize: 18 * mainWindow.uiScale
                    font.italic: true
                }
            }
        }

        // ── Virtual Keyboard (shared, 30% height of chord trainer) ──────────
        Components.VisualKeyboard {
            id: visualKeyboard
            Layout.fillWidth: true
            Layout.preferredHeight: 130 * mainWindow.uiScale
            visible: root.isActive || root.isLoading
        }
    }

    // ── Manual Progression Control (blur overlay + centered button) ────────
    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: root.isWaitingForUserContinue ? 0.55 : 0.0
        visible: root.isWaitingForUserContinue
        z: 99

        Behavior on opacity { NumberAnimation { duration: 300 } }

        MouseArea {
            anchors.fill: parent
            // Block clicks from passing through to elements below
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: 220 * mainWindow.uiScale
        height: 56 * mainWindow.uiScale
        radius: 28 * mainWindow.uiScale
        color: continueMouseArea.pressed ? "#1E88E5" : "#2196F3"
        visible: root.isWaitingForUserContinue
        z: 100
        scale: root.isWaitingForUserContinue ? 1.0 : 0.8
        opacity: root.isWaitingForUserContinue ? 1.0 : 0.0

        Behavior on scale { NumberAnimation { duration: 250; easing.type: Easing.OutBack } }
        Behavior on opacity { NumberAnimation { duration: 250 } }

        Text {
            anchors.centerIn: parent
            text: "CONTINUE  ▶"
            color: "white"
            font.pixelSize: 16 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2
        }

        MouseArea {
            id: continueMouseArea
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                if (appState && appState.chordTrainer) {
                    appState.chordTrainer.continueCircleTutorial()
                }
            }
        }
    }

    // ── Loading Overlay ──────────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: "#121212"
        visible: root.isLoading || !root.showCircle
        z: 110

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 36

            Rectangle {
                id: loadingSpinner
                Layout.alignment: Qt.AlignHCenter
                width: 100 * mainWindow.uiScale; height: 100 * mainWindow.uiScale
                radius: 50 * mainWindow.uiScale
                color: "transparent"
                border.width: 3; border.color: "#2196F3"
                SequentialAnimation on scale {
                    loops: Animation.Infinite; running: loadingSpinner.visible
                    NumberAnimation { from: 0.5; to: 1.5; duration: 1500; easing.type: Easing.OutCubic }
                }
                SequentialAnimation on opacity {
                    loops: Animation.Infinite; running: loadingSpinner.visible
                    NumberAnimation { from: 1.0; to: 0.0; duration: 1500; easing.type: Easing.OutCubic }
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: root.loadingStatusText || "PREPARING CIRCLE OF FIFTHS LESSON..."
                color: "#555555"
                font.pixelSize: 13 * mainWindow.uiScale
                font.letterSpacing: 2
                font.bold: true
            }
        }
    }

    // ── Lesson Complete Overlay ──────────────────────────────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: Math.min(700 * mainWindow.uiScale, parent.width * 0.9)
        height: Math.min(320 * mainWindow.uiScale, parent.height * 0.8)
        color: "#1c1c1e"
        border.color: "#00BCD4"; border.width: 1
        radius: 12
        visible: root.isLessonComplete
        z: 120

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 20

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "LESSON COMPLETE"
                font.pixelSize: 32 * mainWindow.uiScale
                font.bold: true
                color: "#ffffff"
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "You've completed the Circle of Fifths introduction!"
                color: "#aaaaaa"
                font.pixelSize: 16 * mainWindow.uiScale
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Item { Layout.preferredHeight: 12 }

            Button {
                text: "RETURN TO DASHBOARD"
                Layout.alignment: Qt.AlignHCenter
                background: Rectangle {
                    implicitWidth: 220 * mainWindow.uiScale; implicitHeight: 50 * mainWindow.uiScale
                    color: parent.down ? "#333333" : (parent.hovered ? "#444444" : "#2a2a2a")
                    radius: 8; border.color: "#333333"
                }
                contentItem: Text {
                    text: parent.text; color: "#ffffff"
                    font.pixelSize: 14 * mainWindow.uiScale; font.bold: true
                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                }
                onClicked: root.returnToDashboard()
            }
        }
    }

    // ── Inner CircleCanvas component (self-contained) ─────────────────────
    component CircleCanvas: Item {
        id: circleRoot

        property real size: 400
        property bool showBase: false
        property bool showMajor: false
        property bool showMinor: false
        property string highlightKey: ""
        property var highlightedChords: []
        property var revealedKeys: []
        property real rotationAngle: 0

        width: size; height: size

        property var majorKeys: ["C", "G", "D", "A", "E", "B", "Gb", "Db", "Ab", "Eb", "Bb", "F"]
        property var minorKeys: ["A", "E", "B", "F#", "C#", "G#", "Eb", "Bb", "F", "C", "G", "D"]

        // Smooth rotation when highlightKey changes
        property real targetAngle: 0
        onHighlightKeyChanged: {
            if (!highlightKey || !majorKeys || majorKeys.length < 12) return;
            var idx = majorKeys.indexOf(highlightKey);
            if (idx >= 0) {
                var newRawAngle = -idx * 30;
                var diff = (newRawAngle - circleRoot.rotationAngle) % 360;
                
                // Shortest path interpolation
                if (diff > 180) diff -= 360;
                else if (diff < -180) diff += 360;
                
                targetAngle = circleRoot.rotationAngle + diff;
                spinAnim.to = targetAngle;
                spinAnim.restart();
            }
        }
        NumberAnimation {
            id: spinAnim; target: circleRoot; property: "rotationAngle"
            duration: 1000; easing.type: Easing.OutCubic
        }

        Connections {
            target: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths : null
            function onTutorialShowBaseChanged() { theCanvas.requestPaint(); focusIndicator.requestPaint() }
            function onTutorialShowMajorChanged() { theCanvas.requestPaint() }
            function onTutorialShowMinorChanged() { theCanvas.requestPaint() }
            function onTutorialHighlightKeyChanged() { theCanvas.requestPaint() }
            function onHighlightedChordsChanged() { theCanvas.requestPaint() }
            function onArrowsChanged() { theCanvas.requestPaint() }
            function onTutorialRevealedKeysChanged() {
                var newKeys = appState.circleOfFifths.tutorialRevealedKeys;
                if (!newKeys) newKeys = [];
                circleRoot.revealedKeys = newKeys;
                theCanvas.requestPaint();
            }
        }

        Canvas {
            id: theCanvas
            anchors.fill: parent
            rotation: circleRoot.rotationAngle
            antialiasing: true

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()

                if (!circleRoot.showBase) return;
                if (!circleRoot.majorKeys || circleRoot.majorKeys.length < 12 ||
                    !circleRoot.minorKeys || circleRoot.minorKeys.length < 12) return;

                var W = width, H = height;
                var cx = W / 2, cy = H / 2;
                var outerR = W * 0.44;
                var innerR = W * 0.28;
                var holeR  = W * 0.15;

                // chord-color map for neighborhood highlighting
                var chordColorMap = {};
                var hlChords = circleRoot.highlightedChords || [];
                var neighborColors = ["#FFD700", "#26C6DA", "#FF7043", "#42A5F5"];
                for (var ci = 0; ci < hlChords.length && ci < neighborColors.length; ci++) {
                    chordColorMap[hlChords[ci]] = neighborColors[ci];
                }

                ctx.save();
                ctx.translate(cx, cy);

                for (var i = 0; i < 12; i++) {
                    var a1 = (i * 30 - 105) * Math.PI / 180;
                    var a2 = ((i + 1) * 30 - 105) * Math.PI / 180;
                    var majKey = circleRoot.majorKeys[i];
                    var minKey = circleRoot.minorKeys[i];

                    // Check if this specific key should be revealed
                    var isRevealed = false;
                    var rKeys = circleRoot.revealedKeys || [];
                    if (rKeys.length === 0 || rKeys.indexOf("ALL") >= 0) {
                        isRevealed = true; // Show all if empty or 'ALL'
                    } else if (rKeys.indexOf(majKey) >= 0 || rKeys.indexOf(minKey + "m") >= 0) {
                        isRevealed = true;
                    }

                    // Only draw the structural wedge if it is revealed, creating a piecemeal build-up effect
                    if (isRevealed) {
                        // ── Outer ring (major) ──
                        ctx.beginPath();
                        ctx.arc(0, 0, outerR, a1, a2);
                        ctx.arc(0, 0, innerR, a2, a1, true);
                        ctx.closePath();

                        var isSingleHL = (circleRoot.highlightKey === majKey);
                        var neighborColor = chordColorMap[majKey];

                        if (neighborColor) {
                            ctx.fillStyle = neighborColor;
                        } else if (isSingleHL) {
                            ctx.fillStyle = "#FFD700";
                        } else {
                            ctx.fillStyle = "#2a2a2a";
                        }
                        ctx.fill();
                        ctx.strokeStyle = "#555555"; ctx.lineWidth = 1; ctx.stroke();
                    }


                    if (circleRoot.showMajor && isRevealed) {
                        ctx.save();
                        ctx.rotate(a1 + 15 * Math.PI / 180);
                        ctx.fillStyle = (isSingleHL || neighborColor) ? "#000000" : "#e0e0e0";
                        ctx.font = "bold " + Math.round(16 * mainWindow.uiScale) + "px Cinzel";
                        ctx.textAlign = "center";
                        ctx.fillText(majKey.replace('b', '♭'), outerR * 0.82, 6);
                        ctx.restore();
                    }

                    // ── Inner ring (minor) ──
                    if (circleRoot.showMinor && isRevealed) {
                        ctx.beginPath();
                        ctx.arc(0, 0, innerR, a1, a2);
                        ctx.arc(0, 0, holeR, a2, a1, true);
                        ctx.closePath();

                        var isMinHL = (circleRoot.highlightKey === minKey || circleRoot.highlightKey === minKey + "m");
                        ctx.fillStyle = isMinHL ? "#FFD700" : "#1e1e1e";
                        ctx.fill();
                        ctx.strokeStyle = "#444444"; ctx.lineWidth = 1; ctx.stroke();

                        ctx.save();
                        ctx.rotate(a1 + 15 * Math.PI / 180);
                        ctx.fillStyle = isMinHL ? "#000000" : "#bbbbbb";
                        ctx.font = Math.round(13 * mainWindow.uiScale) + "px Cinzel";
                        ctx.textAlign = "center";
                        ctx.fillText(minKey.replace('b', '♭') + "m", innerR * 0.77, 4);
                        ctx.restore();
                    }
                }

                // ── Draw Arrows (if any) ──
                var arrowList = circleRoot.arrows || [];
                if (arrowList.length > 0) {
                    ctx.save();
                    ctx.translate(cx, cy);
                    
                    for (var j = 0; j < arrowList.length; j++) {
                        var arrow = arrowList[j];
                        var fromIdx = circleRoot.majorKeys.indexOf(arrow.from);
                        var toIdx = circleRoot.majorKeys.indexOf(arrow.to);
                        
                        if (fromIdx >= 0 && toIdx >= 0) {
                            // Calculate center angles for the two wedges
                            var fromAngle = (fromIdx * 30 - 90) * Math.PI / 180;
                            var toAngle = (toIdx * 30 - 90) * Math.PI / 180;
                            
                            // Draw arrow just outside the outer ring
                            var arrowR = outerR + 25;
                            var startX = Math.cos(fromAngle) * arrowR;
                            var startY = Math.sin(fromAngle) * arrowR;
                            var endX = Math.cos(toAngle) * arrowR;
                            var endY = Math.sin(toAngle) * arrowR;
                            
                            // Draw the curved arc
                            ctx.beginPath();
                            ctx.arc(0, 0, arrowR, fromAngle, toAngle, fromAngle > toAngle);
                            ctx.strokeStyle = arrow.color || "#4CAF50";
                            ctx.lineWidth = 4;
                            ctx.stroke();
                            
                            // Draw the arrowhead
                            var headlen = 12;
                            // Determine direction of the arrowhead
                            var angleDir = (toAngle > fromAngle) ? 1 : -1;
                            if (Math.abs(toIdx - fromIdx) > 6) {
                                // Wrapping around 12 o'clock, invert direction
                                angleDir *= -1;
                            }
                            // Tangent angle at the end point
                            var tangent = toAngle + (angleDir * Math.PI / 2);
                            
                            ctx.beginPath();
                            ctx.moveTo(endX, endY);
                            ctx.lineTo(endX - headlen * Math.cos(tangent - Math.PI / 6), 
                                       endY - headlen * Math.sin(tangent - Math.PI / 6));
                            ctx.lineTo(endX - headlen * Math.cos(tangent + Math.PI / 6), 
                                       endY - headlen * Math.sin(tangent + Math.PI / 6));
                            ctx.closePath();
                            ctx.fillStyle = arrow.color || "#4CAF50";
                            ctx.fill();
                        }
                    }
                    ctx.restore();
                }

                ctx.restore();
            }
        }

        Canvas {
            id: focusIndicator
            anchors.fill: parent
            antialiasing: true

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                if (!circleRoot.showBase) return;

                var W = width, H = height;
                var cx = W / 2, cy = H / 2;
                var outerR = W * 0.44;

                // Focus indicator at 12 o'clock (fixed, non-rotating)
                ctx.beginPath();
                ctx.moveTo(cx - 12, cy - outerR - 8);
                ctx.lineTo(cx + 12, cy - outerR - 8);
                ctx.lineTo(cx, cy - outerR + 6);
                ctx.closePath();
                ctx.fillStyle = "#2196F3";
                ctx.fill();
            }
        }
    }
}
