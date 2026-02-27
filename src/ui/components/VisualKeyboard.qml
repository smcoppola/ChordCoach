import QtQuick
import QtQuick.Layouts

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
    }
}
