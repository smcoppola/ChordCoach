import QtQuick 2.15
import QtQuick.Layouts 1.15

Item {
    id: root
    clip: true
    Layout.fillWidth: true
    Layout.fillHeight: true
    
    property int startPitch: 21 // A0
    property int endPitch: 108  // C8
    property int numWhiteKeys: 52
    
    // Dictionary to track active pitches map
    property var activeKeys: ({})
    
    // Array to track target pitches for the chord trainer
    property var targetKeys: []
    
    Connections {
        target: (typeof appState !== "undefined" && appState) ? appState : null
        function onMidiNoteReceived(pitch, isOn) {
            // Re-assign dictionary so QML registers the change
            var newActive = Object.assign({}, activeKeys);
            if (isOn) {
                newActive[pitch] = true;
            } else {
                delete newActive[pitch];
            }
            activeKeys = newActive;
        }
    }
    
    function getColorForPitch(pitch) {
        var colors = [
            "#FF5252", // C - Red
            "#FF9800", // C# - Orange
            "#FFC107", // D - Yellow
            "#CDDC39", // D# - Lime
            "#4CAF50", // E - Green
            "#00BFA5", // F - Mint
            "#00BCD4", // F# - Cyan
            "#2196F3", // G - Blue
            "#3F51B5", // G# - Indigo
            "#9C27B0", // A - Purple
            "#E040FB", // A# - Magenta
            "#E91E63", // B - Pink
        ];
        return colors[pitch % 12];
    }
    
    function isBlackKey(pitch) {
        var n = pitch % 12;
        return n === 1 || n === 3 || n === 6 || n === 8 || n === 10;
    }
    
    function whiteIndex(pitch) {
        // C=0, C#=0, D=1, D#=1, E=2, F=3, F#=3, G=4, G#=4, A=5, A#=5, B=6
        var offsets = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6];
        var octave = Math.floor(pitch / 12);
        var baseKey = pitch % 12;
        var globalIndex = (octave * 7) + offsets[baseKey];
        // C0 (pitch 12) is index 7. A0 (pitch 21) is 1. * 7 + offsets[9] = 7 + 5 = 12
        // We subtract 12 to make A0 the 0th index white key on the screen.
        return globalIndex - 12; 
    }
    
    function blackOffsetRatio(pitch) {
        var n = pitch % 12;
        if (n === 1 || n === 6) return 0.65; // C#, F#
        if (n === 3 || n === 10) return 0.75; // D#, A#
        if (n === 8) return 0.55; // G#
        return 0.65; // fallback
    }

    Repeater {
        model: endPitch - startPitch + 1
        
        Rectangle {
            property int pitch: startPitch + index
            property bool isBlack: root.isBlackKey(pitch)
            property int wIndex: root.whiteIndex(pitch)
            property bool isActive: root.activeKeys[pitch] === true
            property bool isTarget: root.targetKeys.includes(pitch)
            property string targetColor: root.getColorForPitch(pitch)
            
            z: isBlack ? 2 : 1
            
            // A black key is visually placed precisely on the "crack" between its two natural neighbors.
            property real whiteKeyWidth: root.width / root.numWhiteKeys
            width: isBlack ? whiteKeyWidth * 0.6 : whiteKeyWidth
            height: isBlack ? root.height * 0.65 : root.height
            
            x: {
                if (!isBlack) {
                    return wIndex * whiteKeyWidth;
                } else {
                    // It's a black key. We want to place its center exactly on the right edge of the white key 'wIndex'.
                    // wIndex corresponds to the natural note just below this black key. 
                    // e.g. for C#, wIndex is the index of C. The right edge of C is (wIndex + 1) * whiteKeyWidth
                    var rightEdgeOfNatural = (wIndex + 1) * whiteKeyWidth;
                    return rightEdgeOfNatural - (width / 2);
                }
            }
            y: 0
            
            // Pressed keys get a light green highlight unless they are the target, then they get a bright target color.
            // Target keys that are not pressed get a faded target color.
            color: isActive ? (isTarget ? Qt.lighter(targetColor, 1.2) : "#4CAF50") : (isTarget ? Qt.darker(targetColor, 1.5) : (isBlack ? "#222222" : "#f5f5f5"))
            border.color: isBlack ? "#111111" : "#cccccc"
            border.width: 1
            
            radius: 3
            
            // 3D lip illusion
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: isBlack ? 15 : 20
                color: isActive ? (isTarget ? targetColor : "#388E3C") : (isTarget ? Qt.darker(targetColor, 1.2) : (isBlack ? "#111111" : "#e0e0e0"))
                radius: 3
            }
        }
    }
}
