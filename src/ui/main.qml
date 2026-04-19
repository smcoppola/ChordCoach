import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
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
    readonly property real uiScale: {
        var s = Math.min(width / 1280, height / 800)
        return Math.max(0.7, s) // Scale floor: prevent elements from becoming unuseably small
    }
    
    property bool showSettings: false
    property bool showOnboarding: {
        if (typeof appState !== "undefined" && appState && appState.settingsService) {
            return !appState.settingsService.hasCompletedOnboarding;
        }
        return false;
    }

    // Main horizontal split
    RowLayout {
        id: mainContent
        anchors.fill: parent
        spacing: 0
        layer.enabled: settingsPopup.visible || onboardingOverlay.visible

        // 1. DASHBOARD SIDEBAR
        LeftSidebar {
            id: sidebar
            Layout.preferredWidth: sidebar.collapsed ? 64 * mainWindow.uiScale : 260 * mainWindow.uiScale
            Layout.fillHeight: true
            onOpenSettings: mainWindow.showSettings = true
            onGoHome: centerWorkspace.goHome()
            onOpenOnboarding: {
                onboardingOverlay.show();
            }
            
            Behavior on Layout.preferredWidth {
                NumberAnimation { duration: 300; easing.type: Easing.OutCubic }
            }
        }

        // 2. MAIN WORKSPACE
        CenterWorkspace {
            id: centerWorkspace
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
    
    // ── Global Background Blur for Popups ──
    FastBlur {
        anchors.fill: mainContent
        source: mainContent
        radius: (settingsPopup.visible || onboardingOverlay.visible) ? (20 * mainWindow.uiScale) : 0
        visible: radius > 0
        z: 40 // Above layout, below popups
        Behavior on radius { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
    }
    
    // ── Settings Dialog ──
    Popup {
        id: settingsPopup
        width: Math.min(mainWindow.width * 0.8, 900 * mainWindow.uiScale)
        height: Math.min(mainWindow.height * 0.8, 700 * mainWindow.uiScale)
        modal: true
        visible: mainWindow.showSettings
        anchors.centerIn: parent
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
                    font.pixelSize: 18 * mainWindow.uiScale
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
                        font.pixelSize: 16 * mainWindow.uiScale
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
        
        onCompleted: {
            appState.settingsService.markOnboardingComplete();
            mainWindow.showOnboarding = false;
        }
        
        Component.onCompleted: {
            if (mainWindow.showOnboarding) {
                onboardingOverlay.show();
            }
        }
    }


    Connections {
        target: (typeof appState !== "undefined" && appState !== null && appState.gemini) ? appState.gemini : null
        function onApiKeyInvalid() {
            mainWindow.showSettings = false;
            onboardingOverlay.show();
            onboardingOverlay.phase = -1;
        }
    }

    // ── MIDI Disconnected Banner ──
    Rectangle {
        id: midiWarningBanner
        width: parent.width
        height: 48 * mainWindow.uiScale
        color: "#F44336" // Red
        anchors.bottom: parent.bottom
        visible: (typeof appState !== "undefined" && appState) ? (!appState.midiConnected && appState.midiInitialSearchDone) : false
        z: 999 // Ensure it's above most content

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            spacing: 15

            Text {
                text: "⚠️"
                font.pixelSize: 24 * mainWindow.uiScale
                color: "white"
            }

            Text {
                text: "No MIDI device detected. Please connect your keyboard."
                color: "white"
                font.pixelSize: 16 * mainWindow.uiScale
                font.bold: true
                Layout.fillWidth: true
            }

            Text {
                text: "Polling for devices..."
                color: "white"
                font.pixelSize: 14 * mainWindow.uiScale
                font.italic: true
            }

            ProgressBar {
                id: pollingProgress
                indeterminate: true
                Layout.preferredWidth: 100 * mainWindow.uiScale
                background: Rectangle { color: "#ffffff33"; radius: 2 }
                contentItem: Item {
                    Rectangle {
                        id: barIndicator
                        width: parent.width
                        height: parent.height
                        color: "white"
                        radius: 2
                        NumberAnimation on x {
                            from: -barIndicator.width; to: barIndicator.width
                            duration: 1500
                            loops: Animation.Infinite
                        }
                    }
                }
            }
        }
        
        // Entance animation
        Behavior on opacity { NumberAnimation { duration: 300 } }
        Behavior on anchors.bottomMargin { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
    }
}
