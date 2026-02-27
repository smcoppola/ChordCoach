import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import "./components" as Components

ApplicationWindow {
    id: mainWindow
    visible: true
    visibility: "Maximized"
    width: 1280
    height: 800
    title: qsTr("ChordCoach Companion")
    color: "#121212"
    
    // Global scaling factor based on reference resolution 1280x800
    readonly property real uiScale: Math.min(width / 1280, height / 800)
    
    property bool showSettings: false
    property bool showOnboarding: {
        if (typeof appState !== "undefined" && appState && appState.settingsService) {
            return !appState.settingsService.hasCompletedOnboarding;
        }
        return false;
    }

    // Main horizontal split
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // 1. DASHBOARD SIDEBAR
        LeftSidebar {
            Layout.preferredWidth: 260 * mainWindow.uiScale
            Layout.fillHeight: true
            onOpenSettings: mainWindow.showSettings = true
            onOpenOnboarding: {
                onboardingOverlay.show();
            }
        }

        // 2. MAIN WORKSPACE
        CenterWorkspace {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
    
    // ── Settings Dialog ──
    Popup {
        id: settingsPopup
        modal: true
        visible: mainWindow.showSettings
        anchors.centerIn: parent
        width: parent.width * 0.8
        height: parent.height * 0.85
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: mainWindow.showSettings = false
        
        background: Rectangle {
            color: "#1c1c1e"
            radius: 12
            border.color: "#333333"
            border.width: 1
        }
        
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 0
            
            // Close bar
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                Layout.leftMargin: 16
                Layout.rightMargin: 8
                
                Text {
                    text: "Settings"
                    color: "#ffffff"
                    font.pixelSize: 18
                    font.bold: true
                    Layout.fillWidth: true
                }
                
                Rectangle {
                    width: 32; height: 32; radius: 16
                    color: closeMA.containsMouse ? "#333333" : "transparent"
                    
                    Text {
                        anchors.centerIn: parent
                        text: "✕"
                        color: "#888888"
                        font.pixelSize: 16
                    }
                    MouseArea {
                        id: closeMA
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: mainWindow.showSettings = false
                    }
                }
            }
            
            Rectangle { Layout.fillWidth: true; height: 1; color: "#333333" }
            
            // Embed existing SettingsView inside the popup
            SettingsView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                onRecalibrateRequested: {
                    mainWindow.showSettings = false;
                    onboardingOverlay.show();
                }
            }
        }
    }
    
    // ── Onboarding Overlay ──
    Components.OnboardingOverlay {
        id: onboardingOverlay
        anchors.fill: parent
        
        Component.onCompleted: {
            if (mainWindow.showOnboarding) {
                onboardingOverlay.show();
            }
        }
    }
}
