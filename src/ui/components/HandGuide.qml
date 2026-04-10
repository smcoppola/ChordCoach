import QtQuick 2.15

Item {
    id: root
    width: 110 * mainWindow.uiScale
    height: 110 * mainWindow.uiScale
    
    property string handType: "right" // "right" or "left"
    property real uiScale: mainWindow ? mainWindow.uiScale : 1.0

    Image {
        id: handImage
        anchors.fill: parent
        source: "../resources/hand_guide_alpha.png"
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        
        // Horizontal flip for left hand
        mirror: root.handType === "left"
        
        // Smoothing for resizing
        smooth: true
    }
}
