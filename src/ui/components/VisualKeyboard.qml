import QtQuick 2.15
import QtQuick.Layouts 1.15
import QtQuick.Controls 2.15

Rectangle {
    id: root
    height: 150 * mainWindow.uiScale
    color: "transparent"

    property var targetKeys: []
    property real keySpacing: 1
    property real keyWidth: (width - (87 * keySpacing)) / 88

    function getColorForPitch(pitch) {
        var colors = [
            "#FF5252", "#FF9800", "#FFC107", "#CDDC39", 
            "#4CAF50", "#00BFA5", "#00BCD4", "#2196F3", 
            "#3F51B5", "#9C27B0", "#E040FB", "#E91E63"
        ];
        return colors[pitch % 12];
    }

    function setTargetKeys(keys) {
        root.targetKeys = []; // Force change signal
        root.targetKeys = keys;
        console.log("VisualKeyboard targetKeys updated via function:", keys);
        mathOverlay.requestPaint();
    }

    function getIntervalName(halfSteps) {
        var names = {
            1: "Minor 2nd", 2: "Major 2nd", 3: "Minor 3rd", 4: "Major 3rd",
            5: "Perfect 4th", 6: "Tritone", 7: "Perfect 5th", 8: "Minor 6th",
            9: "Major 6th", 10: "Minor 7th", 11: "Major 7th", 12: "Octave"
        };
        return names[halfSteps] || (halfSteps + " half-steps");
    }

    signal archClicked()

    Row {
        id: keyboardRow
        anchors.centerIn: parent
        spacing: root.keySpacing

        Repeater {
            model: 88 // Standard piano keys (A0 to C8)
            delegate: Rectangle {
                width: root.keyWidth
                height: 120 * mainWindow.uiScale
                color: isBlackKey(index) ? "black" : "white"
                border.color: "#333"
                border.width: 1

                function isBlackKey(idx) {
                    let pattern = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0];
                    return pattern[(idx + 9) % 12] === 1;
                }
                
                // Determine if this specific key is a target
                // MIDI note 21 is A0 (the 0th index of 88 keys)
                property bool isTarget: {
                    var midiPitch = index + 21;
                    for (var i = 0; i < root.targetKeys.length; i++) {
                        if (root.targetKeys[i] === midiPitch) return true;
                    }
                    return false;
                }

                property string pitchColor: isTarget ? root.getColorForPitch(index + 21) : "#00BCD4"

                Rectangle {
                    anchors.fill: parent
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: isTarget ? Qt.darker(pitchColor, 1.2) : (isBlackKey(index) ? "#333" : "#FFF") }
                        GradientStop { position: 1.0; color: isTarget ? pitchColor : (isBlackKey(index) ? "#000" : "#EEE") }
                    }
                }

                Rectangle {
                    anchors.bottom: parent.bottom
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.max(2, parent.width - (4 * mainWindow.uiScale))
                    height: 10 * mainWindow.uiScale
                    radius: 5 * mainWindow.uiScale
                    color: pitchColor
                    visible: isTarget
                }
            }
        }
    }
    
    // Canvas overlay to draw the half-step math arches
    Canvas {
        id: mathOverlay
        anchors.fill: keyboardRow
        z: 10
        
        onPaint: {
            var ctx = getContext("2d");
            ctx.clearRect(0, 0, width, height);
            
            if (!root.targetKeys || root.targetKeys.length < 2) return;
            
            // Sort keys lowest to highest safely handling QVariantList
            var arr = [];
            for (var k = 0; k < root.targetKeys.length; k++) {
                arr.push(root.targetKeys[k]);
            }
            var sortedKeys = arr.sort((a, b) => a - b);
            console.log("Drawing Math Arches for targetKeys:", sortedKeys);
            
            ctx.lineWidth = 2 * mainWindow.uiScale;
            ctx.strokeStyle = "#4CAF50"; // Green for the arch
            ctx.fillStyle = "#FFFFFF";
            ctx.font = "bold " + Math.round(14 * mainWindow.uiScale) + "px sans-serif";
            ctx.textAlign = "center";
            
            for (var i = 0; i < sortedKeys.length - 1; i++) {
                // Calculate physical X positions 
                // Index is MIDI Pitch - 21. Each key takes up (keyWidth + keySpacing) horizontal pixels.
                var p1_idx = sortedKeys[i] - 21;
                var p2_idx = sortedKeys[i+1] - 21;
                
                var x1 = (p1_idx * (root.keyWidth + root.keySpacing)) + (root.keyWidth / 2);
                var x2 = (p2_idx * (root.keyWidth + root.keySpacing)) + (root.keyWidth / 2);
                var diff = sortedKeys[i+1] - sortedKeys[i];
                
                var midX = x1 + ((x2 - x1) / 2);
                var archHeight = 35 * mainWindow.uiScale; 
                var yStart = 40 * mainWindow.uiScale; // Start the arch slightly down the physical key
                
                // Draw Arch
                ctx.beginPath();
                ctx.moveTo(x1, yStart);
                ctx.quadraticCurveTo(midX, yStart - archHeight, x2, yStart);
                ctx.stroke();
                
                // Draw Math Text
                ctx.fillText("+" + diff, midX, yStart - (archHeight/2) - 5);
            }
        }
        
        // ToolTip for clicked arches
        ToolTip {
            id: intervalToolTip
            delay: 0
            timeout: 2000
            contentItem: Text {
                text: intervalToolTip.text
                color: "#ffffff"
                font.pixelSize: 14 * mainWindow.uiScale
                font.bold: true
            }
            background: Rectangle {
                color: "#4CAF50"
                radius: 4 * mainWindow.uiScale
                border.color: "#388E3C"
                border.width: 1
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onMouseXChanged: {
                if (!root.targetKeys || root.targetKeys.length < 2) {
                    cursorShape = Qt.ArrowCursor;
                    return;
                }
                var sorted = root.targetKeys.slice().sort((a,b)=>a-b);
                var overArch = false;
                for (var i = 0; i < sorted.length - 1; i++) {
                    var x1 = ((sorted[i] - 21) * (root.keyWidth + root.keySpacing)) + (root.keyWidth / 2);
                    var x2 = ((sorted[i+1] - 21) * (root.keyWidth + root.keySpacing)) + (root.keyWidth / 2);
                    if (mouseX > x1 + 5 && mouseX < x2 - 5 && mouseY > 0 && mouseY < 50 * mainWindow.uiScale) {
                        overArch = true;
                        break;
                    }
                }
                cursorShape = overArch ? Qt.PointingHandCursor : Qt.ArrowCursor;
            }
            onClicked: {
                if (!root.targetKeys || root.targetKeys.length < 2) return;
                var sorted = root.targetKeys.slice().sort((a,b)=>a-b);
                
                for (var i = 0; i < sorted.length - 1; i++) {
                    var x1 = ((sorted[i] - 21) * (root.keyWidth + root.keySpacing)) + (root.keyWidth / 2);
                    var x2 = ((sorted[i+1] - 21) * (root.keyWidth + root.keySpacing)) + (root.keyWidth / 2);
                    
                    // Allow clicking in the upper area above the keys between x1 and x2
                    if (mouseX > x1 + 5 && mouseX < x2 - 5 && mouseY > 0 && mouseY < 50 * mainWindow.uiScale) {
                        var diff = sorted[i+1] - sorted[i];
                        var ix = mouseX;
                        var iy = mouseY;
                        intervalToolTip.show(root.getIntervalName(diff));
                        intervalToolTip.x = ix - (intervalToolTip.width / 2);
                        intervalToolTip.y = iy - intervalToolTip.height - 10;
                        root.archClicked();
                        break;
                    }
                }
            }
        }
    }
}
