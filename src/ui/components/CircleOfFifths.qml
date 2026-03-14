import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    
    property string activeKey: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.currentKey : "C"
    property var majorKeys: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.majorOrder : []
    property var minorKeys: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.minorOrder : []
    
    // Internal state for rotation and animation
    property real rotationAngle: 0
    property string hoveredKey: ""
    property var activeMidiPitches: ({})
    
    implicitWidth: 240 * mainWindow.uiScale
    implicitHeight: 240 * mainWindow.uiScale

    // Map of MIDI pitch to key name for highlighting logic
    function getNoteName(pitch) {
        const names = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
        return names[pitch % 12]
    }

    Connections {
        target: (typeof appState !== "undefined" && appState) ? appState.circleOfFifths : null
        function onNoteActive(pitch) {
            let note = root.getNoteName(pitch)
            root.activeMidiPitches[note] = Date.now()
            canvas.requestPaint()
            highlightTimer.restart()
        }
    }

    Timer {
        id: highlightTimer
        interval: 500
        onTriggered: canvas.requestPaint()
    }

    // Help properly format keys for display
    function formatKey(key) {
        return key.replace('b', '♭')
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
                
                // Styling
                var isCurrent = (majKey === root.activeKey)
                var isActiveNote = (Date.now() - (root.activeMidiPitches[majKey] || 0) < 400)
                
                ctx.fillStyle = isCurrent ? "#2196F3" : (isActiveNote ? "#4CAF50" : "#2a2a2a")
                ctx.fill()
                ctx.strokeStyle = "#444444"
                ctx.lineWidth = 1
                ctx.stroke()
                
                // Label
                ctx.save()
                ctx.rotate(angle + 15 * Math.PI / 180)
                ctx.fillStyle = isCurrent ? "#ffffff" : "#bbbbbb"
                ctx.font = "bold " + (14 * mainWindow.uiScale) + "px Inter"
                ctx.textAlign = "center"
                ctx.fillText(root.formatKey(majKey), outerRadius * 0.82, 5)
                ctx.restore()
                
                // ── Draw Inner Ring (Minor) ──
                ctx.beginPath()
                ctx.arc(0, 0, innerRadius, angle, nextAngle)
                ctx.arc(0, 0, holeRadius, nextAngle, angle, true)
                ctx.closePath()
                
                isActiveNote = (Date.now() - (root.activeMidiPitches[minKey.replace('#', 's')] || 0) < 400) // normalize for simplicity
                
                ctx.fillStyle = isActiveNote ? "#4CAF50" : "#1e1e1e"
                ctx.fill()
                ctx.stroke()
                
                // Label
                ctx.save()
                ctx.rotate(angle + 15 * Math.PI / 180)
                ctx.fillStyle = "#888888"
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
            // (Calculation: -rotationAngle relative to C at -90deg)
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
