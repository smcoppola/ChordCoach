import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#121212"
    
    // The chord trainer is the sole workspace view
    ChordTrainerView {
        anchors.fill: parent
    }
}
