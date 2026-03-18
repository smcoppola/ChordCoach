import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#e6000000" // 90% opacity black background
    
    // Properties tied to backend CircleOfFifthsService state
    property bool showBaseRing: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialShowBase : false
    property bool showMajorText: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialShowMajor : false
    property bool showMinorRing: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialShowMinor : false
    property string highlightKey: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.tutorialHighlightKey : ""

    property real rotationAngle: 0
    property var activeMidiPitches: ({})

    // Animation settings
    Behavior on showBaseRing { NumberAnimation { duration: 500 } }
    Behavior on showMajorText { NumberAnimation { duration: 500 } }
    Behavior on showMinorRing { NumberAnimation { duration: 500 } }

    MouseArea {
        anchors.fill: parent
        // Just consume mouse input to prevent clicks falling through to the CenterWorkspace beneath
        onClicked: {} 
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 20 * mainWindow.uiScale

        // Title / Narrative Card
        Rectangle {
            Layout.preferredWidth: 400 * mainWindow.uiScale
            Layout.preferredHeight: 60 * mainWindow.uiScale
            color: "#1c1c1e"
            radius: 8
            border.color: "#333333"
            
            Text {
                anchors.centerIn: parent
                text: {
                    if (!showBaseRing) return "Initializing Lesson...";
                    if (highlightKey) return "Highlighting: " + highlightKey;
                    return "Watch & Listen to the Outline";
                }
                color: "#ffffff"
                font.pixelSize: 16 * mainWindow.uiScale
                font.bold: true
            }
        }

        // The Canvas
        Canvas {
            id: canvas
            width: 360 * mainWindow.uiScale
            height: 360 * mainWindow.uiScale
            Layout.preferredWidth: width
            Layout.preferredHeight: height
            antialiasing: true
            
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onVisibleChanged: if (visible) requestPaint()
            
            property var majorKeys: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.majorOrder : []
            property var minorKeys: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths.minorOrder : []

            Connections {
                target: (typeof appState !== "undefined" && appState && appState.circleOfFifths) ? appState.circleOfFifths : null
                function onTutorialShowBaseChanged() { canvas.requestPaint() }
                function onTutorialShowMajorChanged() { canvas.requestPaint() }
                function onTutorialShowMinorChanged() { canvas.requestPaint() }
                function onTutorialHighlightKeyChanged() { canvas.requestPaint() }
            }

            onPaint: {
                console.log("CircleOfFifthsTutorial Canvas onPaint triggered. Size: " + width + "x" + height);
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
                
                if (!root.showBaseRing) {
                    console.log("Canvas aborting: showBaseRing is false");
                    ctx.restore()
                    return; // Don't draw anything until triggered
                }

                if (!canvas.majorKeys || canvas.majorKeys.length < 12 || !canvas.minorKeys || canvas.minorKeys.length < 12) {
                    console.log("Canvas aborting: Keys not fully loaded. Major length: " + (canvas.majorKeys ? canvas.majorKeys.length : "null") + ", Minor length: " + (canvas.minorKeys ? canvas.minorKeys.length : "null"));
                    ctx.restore()
                    return; // Data not fully loaded
                }
                
                console.log("Canvas proceeding to draw segments...");

                // Draw segments
                for (var i = 0; i < 12; i++) {
                    var angle = (i * 30 - 105) * Math.PI / 180 // Center C at top center
                    var nextAngle = ((i + 1) * 30 - 105) * Math.PI / 180
                    
                    var majKey = canvas.majorKeys[i]
                    var minKey = canvas.minorKeys[i]
                    
                    // ── Draw Outer Ring (Major) ──
                    ctx.beginPath()
                    ctx.arc(0, 0, outerRadius, angle, nextAngle)
                    ctx.arc(0, 0, innerRadius, nextAngle, angle, true)
                    ctx.closePath()
                    
                    var isHighlighted = (root.highlightKey === majKey)
                    
                    ctx.fillStyle = isHighlighted ? "#FFD700" : "#2a2a2a" // Gold highlight
                    ctx.fill()
                    ctx.strokeStyle = "#444444"
                    ctx.lineWidth = 1
                    ctx.stroke()
                    
                    // Label
                    if (root.showMajorText) {
                        ctx.save()
                        ctx.rotate(angle + 15 * Math.PI / 180)
                        ctx.fillStyle = isHighlighted ? "#000000" : "#ffffff"
                        ctx.font = "bold " + (16 * mainWindow.uiScale) + "px Inter"
                        ctx.textAlign = "center"
                        ctx.fillText(majKey.replace('b', '♭'), outerRadius * 0.82, 6)
                        ctx.restore()
                    }
                    
                    // ── Draw Inner Ring (Minor) ──
                    if (root.showMinorRing) {
                        ctx.beginPath()
                        ctx.arc(0, 0, innerRadius, angle, nextAngle)
                        ctx.arc(0, 0, holeRadius, nextAngle, angle, true)
                        ctx.closePath()
                        
                        var isMinorHighlighted = (root.highlightKey === minKey || root.highlightKey === minKey + "m")
                        ctx.fillStyle = isMinorHighlighted ? "#FFD700" : "#1e1e1e"
                        ctx.fill()
                        ctx.stroke()
                        
                        // Label
                        ctx.save()
                        ctx.rotate(angle + 15 * Math.PI / 180)
                        ctx.fillStyle = isMinorHighlighted ? "#000000" : "#888888"
                        ctx.font = (13 * mainWindow.uiScale) + "px Inter"
                        ctx.textAlign = "center"
                        ctx.fillText(minKey.replace('b', '♭'), innerRadius * 0.72, 5)
                        ctx.restore()
                    }
                }
                
                ctx.restore()
            }
        }
    }
}
