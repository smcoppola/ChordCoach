import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    
    // Properties
    property string targetChordName: ""
    property string chordType: "" // e.g. "Major", "Minor"
    property string formulaText: "" // e.g. "Root + 4 + 3"
    property bool isActive: false
    
    visible: isActive && targetChordName !== "" && formulaText !== ""
    
    // Dynamic styling based on chord type
    property bool isMinor: (chordType || "").toLowerCase() === "minor"
    
    Layout.alignment: Qt.AlignHCenter
    Layout.fillWidth: true
    Layout.maximumWidth: 600 * mainWindow.uiScale
    Layout.preferredHeight: 120 * mainWindow.uiScale
    Layout.margins: 10 * mainWindow.uiScale
    
    color: "#222222"
    radius: 8 * mainWindow.uiScale
    
    // The beginner guide emphasizes circling the Minor formula in red
    border.color: isMinor ? "#F44336" : "#4CAF50" 
    border.width: isMinor ? 3 : 1
    
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 15 * mainWindow.uiScale
        spacing: 5 * mainWindow.uiScale
        
        Text {
            Layout.alignment: Qt.AlignHCenter
            text: {
                var ct = (chordType || "").toUpperCase();
                if (ct === "PENTASCALE") return "PENTASCALE";
                return ct + " CHORD";
            }
            font.pixelSize: 14 * mainWindow.uiScale
            font.bold: true
            font.letterSpacing: 2 * mainWindow.uiScale
            color: root.isMinor ? "#F44336" : "#4CAF50"
        }
        
        Text {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            text: formulaText
            font.pixelSize: 26 * mainWindow.uiScale
            font.bold: true
            color: "#FFFFFF"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }
    }
}
