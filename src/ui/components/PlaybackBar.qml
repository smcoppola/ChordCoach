import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root

    property bool isSongMode: false
    property real baseBpm: 120.0

    // Safe access to AppState & services
    readonly property bool hasAppState: typeof appState !== "undefined" && appState !== null
    readonly property bool midiOutEnabled: hasAppState && appState.settingsService ? appState.settingsService.midiOutEnabled : false
    readonly property bool midiConnected: hasAppState ? appState.midiConnected : false
    readonly property bool midiOutputAvailable: midiOutEnabled && midiConnected

    // Playback Service bindings
    readonly property var playback: hasAppState ? appState.playback : null
    readonly property bool isPlaying: playback ? playback.isPlaying : false
    readonly property real playbackBeat: playback ? playback.playbackBeat : 0.0
    readonly property real tempoScale: playback ? playback.tempoScale : 1.0
    readonly property real loopStartBeat: playback ? playback.loopStartBeat : -1.0
    readonly property real loopEndBeat: playback ? playback.loopEndBeat : -1.0
    readonly property string handFilter: playback ? playback.handFilter : "both"
    readonly property bool metronomeEnabled: playback ? playback.metronomeEnabled : false

    visible: isSongMode
    Layout.fillWidth: true
    Layout.maximumWidth: 800 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
    Layout.preferredHeight: 64 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
    Layout.alignment: Qt.AlignHCenter
    radius: 12 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

    color: "#1e1e24"
    border.color: "#33333e"
    border.width: 1

    RowLayout {
        id: layout
        anchors.fill: parent
        anchors.leftMargin: 16 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
        anchors.rightMargin: 16 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
        spacing: 14 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
        enabled: root.midiOutputAvailable

        // 1. Play / Pause Button
        Button {
            id: playPauseBtn
            Layout.preferredWidth: 40 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            Layout.preferredHeight: 40 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

            background: Rectangle {
                color: playPauseBtn.down ? "#1b5e20" : (playPauseBtn.hovered ? "#388e3c" : "#2e7d32")
                radius: 20 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            }

            contentItem: Text {
                text: root.isPlaying ? "❚❚" : "▶"
                color: "#ffffff"
                font.pixelSize: 16 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            onClicked: {
                if (root.playback) {
                    if (root.isPlaying) {
                        root.playback.pause();
                    } else {
                        root.playback.play();
                    }
                }
            }
        }

        // 2. Stop Button
        Button {
            id: stopBtn
            Layout.preferredWidth: 36 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            Layout.preferredHeight: 36 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

            background: Rectangle {
                color: stopBtn.down ? "#b71c1c" : (stopBtn.hovered ? "#d32f2f" : "#442222")
                radius: 6 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            }

            contentItem: Text {
                text: "■"
                color: "#ffffff"
                font.pixelSize: 14 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            onClicked: {
                if (root.playback) root.playback.stop();
            }
        }

        // 3. Live Tempo Slider & Label
        RowLayout {
            spacing: 8 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

            Text {
                text: "Tempo"
                color: "#aaaaaa"
                font.pixelSize: 12 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                font.bold: true
            }

            Slider {
                id: tempoSlider
                Layout.preferredWidth: 120 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                from: 0.25
                to: 1.50
                stepSize: 0.05
                value: root.tempoScale

                onMoved: {
                    if (root.playback) root.playback.tempoScale = value;
                }
            }

            Text {
                text: "×" + root.tempoScale.toFixed(2) + " (" + Math.round(root.baseBpm * root.tempoScale) + " BPM)"
                color: "#4caf50"
                font.pixelSize: 12 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                font.bold: true
                Layout.preferredWidth: 95 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            }
        }

        // Vertical Separator
        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 28 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            color: "#333344"
        }

        // 4. A/B Loop Controls
        RowLayout {
            spacing: 6 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

            Button {
                id: loopABtn
                Layout.preferredHeight: 32 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                background: Rectangle {
                    color: root.loopStartBeat >= 0 ? "#1976d2" : (loopABtn.hovered ? "#333344" : "#2a2a35")
                    radius: 4 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                    border.color: "#444455"
                }
                contentItem: Text {
                    text: root.loopStartBeat >= 0 ? "A: " + root.loopStartBeat.toFixed(1) : "Set A"
                    color: "#ffffff"
                    font.pixelSize: 11 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    if (root.playback) root.playback.setLoopA();
                }
            }

            Button {
                id: loopBBtn
                Layout.preferredHeight: 32 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                background: Rectangle {
                    color: root.loopEndBeat >= 0 ? "#1976d2" : (loopBBtn.hovered ? "#333344" : "#2a2a35")
                    radius: 4 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                    border.color: "#444455"
                }
                contentItem: Text {
                    text: root.loopEndBeat >= 0 ? "B: " + root.loopEndBeat.toFixed(1) : "Set B"
                    color: "#ffffff"
                    font.pixelSize: 11 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    if (root.playback) root.playback.setLoopB();
                }
            }

            Button {
                id: clearLoopBtn
                visible: root.loopStartBeat >= 0 || root.loopEndBeat >= 0
                Layout.preferredHeight: 32 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                background: Rectangle {
                    color: clearLoopBtn.hovered ? "#d32f2f" : "#442222"
                    radius: 4 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                }
                contentItem: Text {
                    text: "Clear Loop"
                    color: "#ffffff"
                    font.pixelSize: 11 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    if (root.playback) root.playback.clearLoop();
                }
            }
        }

        // Vertical Separator
        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 28 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            color: "#333344"
        }

        // 5. Hands Segmented Control
        Row {
            spacing: 2 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

            Repeater {
                model: [
                    { tag: "both", label: "Both" },
                    { tag: "right", label: "RH" },
                    { tag: "left", label: "LH" }
                ]

                delegate: Button {
                    id: handBtn
                    width: 44 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                    height: 32 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

                    background: Rectangle {
                        color: root.handFilter === modelData.tag ? "#7b1fa2" : (handBtn.hovered ? "#333344" : "#2a2a35")
                        radius: 4 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                        border.color: root.handFilter === modelData.tag ? "#ab47bc" : "#444455"
                    }

                    contentItem: Text {
                        text: modelData.label
                        color: "#ffffff"
                        font.pixelSize: 11 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                        font.bold: root.handFilter === modelData.tag
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }

                    onClicked: {
                        if (root.playback) root.playback.handFilter = modelData.tag;
                    }
                }
            }
        }

        // 6. Metronome Toggle
        Button {
            id: metroBtn
            Layout.preferredHeight: 32 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            background: Rectangle {
                color: root.metronomeEnabled ? "#ff8f00" : (metroBtn.hovered ? "#333344" : "#2a2a35")
                radius: 4 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                border.color: root.metronomeEnabled ? "#ffb300" : "#444455"
            }

            contentItem: Text {
                text: "⏱ Metronome"
                color: "#ffffff"
                font.pixelSize: 11 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                font.bold: root.metronomeEnabled
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }

            onClicked: {
                if (root.playback) root.playback.metronomeEnabled = !root.metronomeEnabled;
            }
        }
    }

    // Disabled State Overlay with Tooltip Hint
    Rectangle {
        anchors.fill: parent
        visible: !root.midiOutputAvailable
        color: "#d9111116"
        radius: parent.radius

        RowLayout {
            anchors.centerIn: parent
            spacing: 8 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)

            Text {
                text: "⚠️ Playback unavailable:"
                color: "#ffa726"
                font.pixelSize: 12 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
                font.bold: true
            }

            Text {
                text: !root.midiOutEnabled ? "MIDI Output is disabled in settings." : "No MIDI hardware output device connected."
                color: "#cccccc"
                font.pixelSize: 12 * (typeof mainWindow !== "undefined" ? mainWindow.uiScale : 1.0)
            }
        }
    }
}
