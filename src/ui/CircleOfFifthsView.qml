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
                    NumberAnimation { to: 0.6; duration: 600; easing.type: Easing.OutQuad }
                    NumberAnimation { to: 0.0; duration: 800; easing.type: Easing.InQuad }
                }
                SequentialAnimation on scale {
                    running: root.showCircle
                    NumberAnimation { from: 0.85; to: 1.05; duration: 600; easing.type: Easing.OutQuad }
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
                Layout.alignment: Qt.AlignHCenter
                width: 100 * mainWindow.uiScale; height: 100 * mainWindow.uiScale
                radius: 50 * mainWindow.uiScale
                color: "transparent"
                border.width: 3; border.color: "#2196F3"
                SequentialAnimation on scale {
                    loops: Animation.Infinite; running: parent.visible
                    NumberAnimation { from: 0.5; to: 1.5; duration: 1500; easing.type: Easing.OutCubic }
                }
                SequentialAnimation on opacity {
                    loops: Animation.Infinite; running: parent.visible
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
        property real rotationAngle: 0

        width: size; height: size

        property var majorKeys: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.majorOrder : []
        property var minorKeys: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.minorOrder : []

        // Smooth rotation when highlightKey changes
        property real targetAngle: 0
        onHighlightKeyChanged: {
            if (!highlightKey || !majorKeys || majorKeys.length < 12) return;
            var idx = majorKeys.indexOf(highlightKey);
            if (idx >= 0) {
                targetAngle = -idx * 30;
                spinAnim.to = targetAngle;
                spinAnim.restart();
            }
        }
        NumberAnimation {
            id: spinAnim; target: circleRoot; property: "rotationAngle"
            duration: 600; easing.type: Easing.OutCubic
        }

        Connections {
            target: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths : null
            function onTutorialShowBaseChanged() { theCanvas.requestPaint() }
            function onTutorialShowMajorChanged() { theCanvas.requestPaint() }
            function onTutorialShowMinorChanged() { theCanvas.requestPaint() }
            function onTutorialHighlightKeyChanged() { theCanvas.requestPaint() }
            function onHighlightedChordsChanged() { theCanvas.requestPaint() }
        }

        Canvas {
            id: theCanvas
            anchors.fill: parent
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
                ctx.rotate(circleRoot.rotationAngle * Math.PI / 180);

                for (var i = 0; i < 12; i++) {
                    var a1 = (i * 30 - 105) * Math.PI / 180;
                    var a2 = ((i + 1) * 30 - 105) * Math.PI / 180;
                    var majKey = circleRoot.majorKeys[i];
                    var minKey = circleRoot.minorKeys[i];

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

                    if (circleRoot.showMajor) {
                        ctx.save();
                        ctx.rotate(a1 + 15 * Math.PI / 180);
                        ctx.fillStyle = (isSingleHL || neighborColor) ? "#000000" : "#e0e0e0";
                        ctx.font = "bold " + Math.round(16 * mainWindow.uiScale) + "px Inter";
                        ctx.textAlign = "center";
                        ctx.fillText(majKey.replace('b', '♭'), outerR * 0.82, 6);
                        ctx.restore();
                    }

                    // ── Inner ring (minor) ──
                    if (circleRoot.showMinor) {
                        ctx.beginPath();
                        ctx.arc(0, 0, innerR, a1, a2);
                        ctx.arc(0, 0, holeR, a2, a1, true);
                        ctx.closePath();

                        var isMinHL = (circleRoot.highlightKey === minKey || circleRoot.highlightKey === minKey + "m");
                        ctx.fillStyle = isMinHL ? "#FFD700" : "#1e1e1e";
                        ctx.fill();
                        ctx.stroke();

                        ctx.save();
                        ctx.rotate(a1 + 15 * Math.PI / 180);
                        ctx.fillStyle = isMinHL ? "#000000" : "#777777";
                        ctx.font = Math.round(13 * mainWindow.uiScale) + "px Inter";
                        ctx.textAlign = "center";
                        ctx.fillText(minKey.replace('b', '♭'), innerR * 0.72, 5);
                        ctx.restore();
                    }
                }

                ctx.restore();

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
