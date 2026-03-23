import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    
    property string activeKey: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.currentKey : "C"
    property var majorKeys: ["C", "G", "D", "A", "E", "B", "Gb", "Db", "Ab", "Eb", "Bb", "F"]
    property var minorKeys: ["A", "E", "B", "F#", "C#", "G#", "Eb", "Bb", "F", "C", "G", "D"]
    property string detectedChord: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.detectedChord : ""
    
    // Internal state for rotation and animation
    property real rotationAngle: 0
    
    implicitWidth: 240 * mainWindow.uiScale
    implicitHeight: 240 * mainWindow.uiScale

    // Extract the root key from a chord name (e.g. "Am" → "A", "C#dim" → "C#", "Gb" → "Gb")
    function chordRoot(chordName) {
        if (!chordName) return "";
        // Handle two-char roots like C#, Eb, Gb, etc.
        if (chordName.length >= 2 && (chordName[1] === '#' || chordName[1] === 'b')) {
            return chordName.substring(0, 2);
        }
        return chordName[0];
    }

    // Help properly format keys for display
    function formatKey(key) {
        return key.replace('b', '♭');
    }

    Connections {
        target: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths : null
        function onDetectedChordChanged(chord) {
            canvas.requestPaint();
            chordFadeTimer.restart();
        }
        function onKeyChanged() {
            canvas.requestPaint();
        }
    }

    Timer {
        id: chordFadeTimer
        interval: 2000
        onTriggered: canvas.requestPaint()
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        smooth: true
        
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            
            var centerX = width / 2
            var centerY = height / 2
            var outerRadius = width * 0.45
            var innerRadius = width * 0.28
            var holeRadius = width * 0.15
            
            ctx.save()
            ctx.translate(centerX, centerY)
            ctx.rotate(root.rotationAngle * Math.PI / 180)
            
            var detRoot = root.chordRoot(root.detectedChord);
            var isMinorChord = root.detectedChord.indexOf("m") > 0 && root.detectedChord.indexOf("maj") < 0;
            
            // Draw segments
            for (var i = 0; i < 12; i++) {
                var angle = (i * 30 - 105) * Math.PI / 180 // Center C at top center
                var nextAngle = ((i + 1) * 30 - 105) * Math.PI / 180
                
                var majKey = root.majorKeys[i]
                var minKey = root.minorKeys[i]
                
                // ── Draw Outer Ring (Major) ──
                ctx.beginPath()
                ctx.arc(0, 0, outerRadius, angle, nextAngle)
                ctx.arc(0, 0, innerRadius, nextAngle, angle, true)
                ctx.closePath()
                
                // Styling — highlight if this key matches the detected chord root (major chord)
                var isCurrent = (majKey === root.activeKey)
                var isDetected = (majKey === detRoot && !isMinorChord && root.detectedChord !== "")
                
                if (isDetected) {
                    ctx.fillStyle = "#FFD700" // Gold for detected chord
                } else if (isCurrent) {
                    ctx.fillStyle = "#2196F3" // Blue for active key
                } else {
                    ctx.fillStyle = "#2a2a2a"
                }
                ctx.fill()
                ctx.strokeStyle = "#444444"
                ctx.lineWidth = 1
                ctx.stroke()
                
                // Label
                ctx.save()
                ctx.rotate(angle + 15 * Math.PI / 180)
                ctx.fillStyle = (isDetected || isCurrent) ? "#000000" : "#bbbbbb"
                ctx.font = "bold " + (14 * mainWindow.uiScale) + "px Inter"
                ctx.textAlign = "center"
                ctx.fillText(root.formatKey(majKey), outerRadius * 0.82, 5)
                ctx.restore()
                
                // ── Draw Inner Ring (Minor) ──
                ctx.beginPath()
                ctx.arc(0, 0, innerRadius, angle, nextAngle)
                ctx.arc(0, 0, holeRadius, nextAngle, angle, true)
                ctx.closePath()
                
                // Highlight minor ring if detected chord is minor and matches this key
                var isMinorDetected = (isMinorChord && detRoot === minKey && root.detectedChord !== "")
                
                ctx.fillStyle = isMinorDetected ? "#FFD700" : "#1e1e1e"
                ctx.fill()
                ctx.stroke()
                
                // Label
                ctx.save()
                ctx.rotate(angle + 15 * Math.PI / 180)
                ctx.fillStyle = isMinorDetected ? "#000000" : "#888888"
                ctx.font = (11 * mainWindow.uiScale) + "px Inter"
                ctx.textAlign = "center"
                ctx.fillText(root.formatKey(minKey), innerRadius * 0.72, 4)
                ctx.restore()
            }
            
            ctx.restore()
            
            // Draw "Focus Indicator" at 12 o'clock (non-rotating)
            ctx.beginPath()
            ctx.moveTo(centerX - 10, centerY - outerRadius - 5)
            ctx.lineTo(centerX + 10, centerY - outerRadius - 5)
            ctx.lineTo(centerX, centerY - outerRadius + 5)
            ctx.closePath()
            ctx.fillStyle = "#2196F3"
            ctx.fill()
        }
    }

    MouseArea {
        anchors.fill: parent
        property real lastAngle: 0
        
        onPressed: {
            lastAngle = Math.atan2(mouse.y - height / 2, mouse.x - width / 2) * 180 / Math.PI
        }
        
        onPositionChanged: {
            if (pressed) {
                var currentAngle = Math.atan2(mouse.y - height / 2, mouse.x - width / 2) * 180 / Math.PI
                var delta = currentAngle - lastAngle
                root.rotationAngle += delta
                lastAngle = currentAngle
            }
        }
        
        onReleased: {
            // Snap to nearest 30 degree segment
            var snapped = Math.round(root.rotationAngle / 30) * 30
            snapAnim.to = snapped
            snapAnim.start()
            
            // Logic to update active key based on top position
            var index = (360 - (snapped % 360)) / 30
            index = Math.round(index) % 12
            if (typeof appState !== "undefined" && appState && appState.circleOfFifths) {
                appState.circleOfFifths.currentKey = root.majorKeys[index]
            }
        }
    }

    NumberAnimation {
        id: snapAnim
        target: root
        property: "rotationAngle"
        duration: 200
        easing.type: Easing.OutBack
    }
}
