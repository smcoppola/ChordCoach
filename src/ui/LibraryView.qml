// Phase 5 — the library screen: imported songs with rename/delete/dedupe,
// drag-and-drop import, and read-only corpus browsing.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import "components"
import "components/grade_colors.js" as GradeColors

Rectangle {
    id: root
    color: "#121212"

    signal returnToDashboard()

    property real uiScale: (typeof mainWindow !== "undefined" && mainWindow) ? mainWindow.uiScale : 1.0
    readonly property var music21: (typeof appState !== "undefined" && appState) ? appState.music21Service : null

    property int currentTab: 0            // 0 = My Songs, 1 = Corpus
    property string searchQuery: ""
    property var userSongs: []
    property var duplicateGroups: []
    property var catalogPath: []
    property bool isLoadingSong: false
    property string statusMessage: ""
    property bool dragActive: false
    property int activeImportIndex: -1

    readonly property var visibleSongs: {
        var q = searchQuery.toLowerCase();
        if (q.length === 0)
            return userSongs;
        return userSongs.filter(function (s) {
            return ("" + (s.title || "")).toLowerCase().indexOf(q) >= 0
                || ("" + (s.artist || "")).toLowerCase().indexOf(q) >= 0;
        });
    }

    Component.onCompleted: refresh()

    function refresh() {
        if (!music21)
            return;
        userSongs = music21.get_user_songs();
        duplicateGroups = music21.find_duplicates();
    }

    // Same routing the dashboard picker uses: imported songs get the difficulty
    // chooser, catalog songs load straight away.
    function requestSongWithDifficulty(songId) {
        if (songId.indexOf("user::") === 0) {
            difficultyPicker.pendingSongId = songId;
            difficultyPicker.open();
        } else {
            music21.mark_song_played(songId);
            root.isLoadingSong = true;
            music21.songRequested(songId);
        }
    }

    function fileNameOf(url) {
        var s = "" + url;
        var cut = s.lastIndexOf("/");
        return decodeURIComponent(cut >= 0 ? s.substring(cut + 1) : s);
    }

    function shortDate(stamp) {
        if (!stamp)
            return "";
        return ("" + stamp).substring(0, 10);
    }

    // ── Sequential import queue (the Python worker is single-flight) ──
    function enqueueUrls(urls) {
        for (var i = 0; i < urls.length; i++) {
            importQueue.append({
                "name": fileNameOf(urls[i]),
                "url": "" + urls[i],
                "status": "pending",
                "detail": "",
                "songId": ""
            });
        }
        startNextImport();
    }

    function startNextImport() {
        if (activeImportIndex >= 0 || !music21)
            return;
        for (var i = 0; i < importQueue.count; i++) {
            if (importQueue.get(i).status === "pending") {
                activeImportIndex = i;
                importQueue.setProperty(i, "status", "working");
                music21.import_file(importQueue.get(i).url);
                return;
            }
        }
    }

    function finishImport(status, detail, songId) {
        if (activeImportIndex < 0)
            return;
        importQueue.setProperty(activeImportIndex, "status", status);
        importQueue.setProperty(activeImportIndex, "detail", detail || "");
        importQueue.setProperty(activeImportIndex, "songId", songId || "");
        activeImportIndex = -1;
        startNextImport();
    }

    ListModel { id: importQueue }

    Connections {
        target: root.music21

        // Finally consumed: cards appear the moment an import lands
        function onUserSongsChanged() { root.refresh(); }

        function onImportSucceeded(songId) { root.finishImport("ok", "", songId); }
        function onImportFailed(error) { root.finishImport("failed", error, ""); }
        function onImportDuplicate(existingSongId, existingTitle) {
            root.finishImport("duplicate", existingTitle, existingSongId);
        }
        // Async level generation failed — never leave the spinner up
        function onSongLevelFailed(error) {
            root.isLoadingSong = false;
            root.statusMessage = "Could not build that difficulty level: " + error;
        }
    }

    FileDialog {
        id: importDialog
        title: "Import Music Files"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Music files (*.mid *.midi *.xml *.mxl *.musicxml)", "MIDI files (*.mid *.midi)", "MusicXML files (*.xml *.mxl *.musicxml)"]
        onAccepted: root.enqueueUrls(selectedFiles)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24 * root.uiScale
        spacing: 16 * root.uiScale

        // ── Header ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 16 * root.uiScale

            PillButton {
                text: "← BACK"
                accent: "#2196F3"
                onClicked: root.returnToDashboard()
            }

            ColumnLayout {
                spacing: 2
                Text {
                    text: "MUSIC LIBRARY"
                    color: "#666666"
                    font.pixelSize: 11 * root.uiScale
                    font.bold: true
                    font.letterSpacing: 3 * root.uiScale
                }
                Text {
                    text: root.userSongs.length + (root.userSongs.length === 1 ? " imported song" : " imported songs")
                    color: "#ffffff"
                    font.pixelSize: 20 * root.uiScale
                    font.bold: true
                }
            }

            Item { Layout.fillWidth: true }

            PillButton {
                text: "⧉  " + root.duplicateGroups.length + (root.duplicateGroups.length === 1 ? " DUPLICATE" : " DUPLICATES")
                accent: "#FF9800"
                visible: root.duplicateGroups.length > 0
                onClicked: duplicatesDialog.open()
            }

            PillButton {
                text: "⬆  IMPORT MUSIC"
                accent: "#4CAF50"
                onClicked: importDialog.open()
            }
        }

        // ── Tabs ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 8 * root.uiScale

            Repeater {
                model: ["My Songs", "Corpus"]
                delegate: Rectangle {
                    property bool isActive: root.currentTab === index
                    Layout.preferredWidth: tabLabel.implicitWidth + 32 * root.uiScale
                    Layout.preferredHeight: 34 * root.uiScale
                    radius: 17 * root.uiScale
                    color: isActive ? "#2196F320" : (tabMouse.containsMouse ? "#2a2a2a" : "transparent")
                    border.color: isActive ? "#2196F3" : "#333333"

                    Text {
                        id: tabLabel
                        anchors.centerIn: parent
                        text: modelData
                        color: isActive ? "#2196F3" : "#888888"
                        font.pixelSize: 13 * root.uiScale
                        font.bold: true
                    }

                    MouseArea {
                        id: tabMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.currentTab = index;
                            root.searchQuery = "";
                            librarySearchInput.text = "";
                            root.catalogPath = [];
                        }
                    }
                }
            }

            Item { Layout.fillWidth: true }

            // Search
            Rectangle {
                Layout.preferredWidth: 320 * root.uiScale
                Layout.preferredHeight: 38 * root.uiScale
                color: "#2a2a2a"
                radius: 8 * root.uiScale
                border.color: librarySearchInput.activeFocus ? "#2196F3" : "#444444"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12 * root.uiScale
                    anchors.rightMargin: 12 * root.uiScale
                    spacing: 10

                    Text { text: "🔍"; font.pixelSize: 14 * root.uiScale; opacity: 0.6 }

                    TextInput {
                        id: librarySearchInput
                        Layout.fillWidth: true
                        color: "white"
                        font.pixelSize: 13 * root.uiScale
                        selectByMouse: true
                        clip: true
                        onTextChanged: root.searchQuery = text

                        Text {
                            text: root.currentTab === 0 ? "Filter your songs..." : "Search the corpus..."
                            color: "#666666"
                            font.pixelSize: 13 * root.uiScale
                            visible: parent.text.length === 0 && !parent.activeFocus
                        }
                    }

                    Text {
                        text: "✕"
                        color: "#666666"
                        font.pixelSize: 13 * root.uiScale
                        visible: librarySearchInput.text.length > 0
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: librarySearchInput.text = ""
                        }
                    }
                }
            }
        }

        // ── Status banner ──
        Text {
            Layout.fillWidth: true
            visible: root.statusMessage.length > 0
            text: "⚠ " + root.statusMessage
            color: "#FF7043"
            font.pixelSize: 12 * root.uiScale
            wrapMode: Text.WordWrap

            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.statusMessage = ""
            }
        }

        // ── Corpus breadcrumbs ──
        RowLayout {
            Layout.fillWidth: true
            spacing: 10 * root.uiScale
            visible: root.currentTab === 1 && root.catalogPath.length > 0 && root.searchQuery.length === 0

            PillButton {
                text: "← UP"
                accent: "#2196F3"
                onClicked: root.catalogPath = root.catalogPath.slice(0, -1)
            }

            Text {
                Layout.fillWidth: true
                text: root.catalogPath.join("  ›  ")
                color: "#888888"
                font.pixelSize: 12 * root.uiScale
                elide: Text.ElideRight
            }
        }

        // ── My Songs ──
        ScrollView {
            id: mySongsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.currentTab === 0
            clip: true

            Flow {
                width: mySongsScroll.availableWidth
                spacing: 16 * root.uiScale

                Repeater {
                    model: root.visibleSongs
                    delegate: songCardComponent
                }
            }
        }

        // Empty state
        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            visible: root.currentTab === 0 && root.visibleSongs.length === 0
            spacing: 8 * root.uiScale

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: root.userSongs.length === 0 ? "🎼" : "🔍"
                font.pixelSize: 40 * root.uiScale
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: root.userSongs.length === 0
                      ? "Drop MIDI or MusicXML files here to build your library"
                      : "No songs match \"" + root.searchQuery + "\""
                color: "#666666"
                font.pixelSize: 14 * root.uiScale
            }
        }

        // ── Corpus (read-only browse of the shipped catalog) ──
        ScrollView {
            id: corpusScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: root.currentTab === 1
            clip: true

            ColumnLayout {
                width: corpusScroll.availableWidth
                spacing: 10 * root.uiScale

                Repeater {
                    model: {
                        if (!root.music21 || root.currentTab !== 1)
                            return [];
                        if (root.searchQuery.length >= 2)
                            return root.music21.search_catalog(root.searchQuery);
                        return root.music21.get_catalog_level(root.catalogPath);
                    }

                    delegate: SongRow {
                        entry: modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: implicitHeight
                        onActivated: {
                            if (modelData.isCategory) {
                                root.catalogPath = root.catalogPath.concat([modelData.id]);
                            } else {
                                root.requestSongWithDifficulty(modelData.id);
                            }
                        }
                    }
                }
            }
        }

        // ── Import queue strip ──
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 44 * root.uiScale + queueRow.implicitHeight
            visible: importQueue.count > 0
            color: "#1c1c1e"
            radius: 10 * root.uiScale
            border.color: "#333333"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12 * root.uiScale
                spacing: 6 * root.uiScale

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "IMPORTING"
                        color: "#666666"
                        font.pixelSize: 10 * root.uiScale
                        font.bold: true
                        font.letterSpacing: 2 * root.uiScale
                        Layout.fillWidth: true
                    }
                    Text {
                        text: "CLEAR"
                        color: "#666666"
                        font.pixelSize: 10 * root.uiScale
                        font.bold: true
                        visible: root.activeImportIndex < 0
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: importQueue.clear()
                        }
                    }
                }

                ColumnLayout {
                    id: queueRow
                    Layout.fillWidth: true
                    spacing: 4 * root.uiScale

                    Repeater {
                        model: importQueue
                        delegate: RowLayout {
                            Layout.fillWidth: true
                            spacing: 10 * root.uiScale

                            Text {
                                text: {
                                    if (model.status === "working") return "◍";
                                    if (model.status === "ok") return "✓";
                                    if (model.status === "duplicate") return "⧉";
                                    if (model.status === "failed") return "✗";
                                    return "○";
                                }
                                color: {
                                    if (model.status === "ok") return "#4CAF50";
                                    if (model.status === "duplicate") return "#FF9800";
                                    if (model.status === "failed") return "#F44336";
                                    return "#888888";
                                }
                                font.pixelSize: 13 * root.uiScale

                                RotationAnimator on rotation {
                                    from: 0; to: 360
                                    duration: 900
                                    loops: Animation.Infinite
                                    running: model.status === "working"
                                }
                            }

                            Text {
                                text: model.name
                                color: "#cccccc"
                                font.pixelSize: 12 * root.uiScale
                                elide: Text.ElideMiddle
                                Layout.maximumWidth: 320 * root.uiScale
                            }

                            Text {
                                text: {
                                    if (model.status === "duplicate") return "already in your library as \"" + model.detail + "\"";
                                    if (model.status === "failed") return model.detail;
                                    if (model.status === "working") return "parsing…";
                                    return "";
                                }
                                color: model.status === "failed" ? "#FF7043" : "#888888"
                                font.pixelSize: 11 * root.uiScale
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }

                            Text {
                                text: "OPEN"
                                color: "#2196F3"
                                font.pixelSize: 10 * root.uiScale
                                font.bold: true
                                visible: model.status === "duplicate" && model.songId !== ""
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.requestSongWithDifficulty(model.songId)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── Song card (My Songs) ─────────────────────────────────────────
    Component {
        id: songCardComponent

        Rectangle {
            id: card
            required property var modelData

            width: 340 * root.uiScale
            height: 172 * root.uiScale
            radius: 12 * root.uiScale
            color: cardMouse.containsMouse ? "#1f1f22" : "#1c1c1e"
            border.color: cardMouse.containsMouse ? "#2196F3" : "#333333"
            border.width: 1

            MouseArea {
                id: cardMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14 * root.uiScale
                spacing: 6 * root.uiScale

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8 * root.uiScale

                    Text {
                        text: card.modelData.title || "Untitled"
                        color: "#ffffff"
                        font.pixelSize: 15 * root.uiScale
                        font.bold: true
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }

                    Rectangle {
                        width: 62 * root.uiScale
                        height: 20 * root.uiScale
                        radius: 4 * root.uiScale
                        color: GradeColors.forGrade(card.modelData.level)
                        Text {
                            anchors.centerIn: parent
                            text: card.modelData.level || ""
                            color: "white"
                            font.pixelSize: 9 * root.uiScale
                            font.bold: true
                        }
                    }
                }

                Text {
                    text: card.modelData.artist || "Unknown"
                    color: "#888888"
                    font.pixelSize: 11 * root.uiScale
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6 * root.uiScale

                    Badge { text: card.modelData.source_type === "musicxml" ? "XML" : "MIDI"; accent: "#9C27B0" }
                    Badge { text: card.modelData.key || "—"; accent: "#2196F3"; visible: !!card.modelData.key }
                    Badge {
                        accent: "#607D8B"
                        text: {
                            var m = card.modelData.hand_mode;
                            if (m === "right") return "RH";
                            if (m === "left") return "LH";
                            if (m === "split") return "SPLIT";
                            return "AUTO";
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: card.modelData.last_played ? ("played " + root.shortDate(card.modelData.last_played)) : ""
                        color: "#666666"
                        font.pixelSize: 10 * root.uiScale
                    }
                }

                // Mastery — hidden until Phase 4 has recorded a completion
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    visible: card.modelData.play_count > 0

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "MASTERY"
                            color: "#666666"
                            font.pixelSize: 9 * root.uiScale
                            font.bold: true
                            font.letterSpacing: 1.5 * root.uiScale
                            Layout.fillWidth: true
                        }
                        Text {
                            text: Math.round(card.modelData.mastery) + "%"
                            color: "#4CAF50"
                            font.pixelSize: 9 * root.uiScale
                            font.bold: true
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 4 * root.uiScale
                        radius: 2 * root.uiScale
                        color: "#333333"

                        Rectangle {
                            width: parent.width * Math.max(0, Math.min(1, card.modelData.mastery / 100))
                            height: parent.height
                            radius: 2 * root.uiScale
                            color: "#4CAF50"
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6 * root.uiScale

                    PillButton {
                        text: "▶  PLAY"
                        accent: "#4CAF50"
                        onClicked: root.requestSongWithDifficulty(card.modelData.id)
                    }
                    PillButton {
                        text: "⚙  LEVELS"
                        accent: "#2196F3"
                        onClicked: {
                            difficultyPicker.pendingSongId = card.modelData.id;
                            difficultyPicker.open();
                        }
                    }
                    Item { Layout.fillWidth: true }
                    PillButton {
                        text: "RENAME"
                        accent: "#888888"
                        onClicked: renameDialog.show(card.modelData)
                    }
                    PillButton {
                        text: "DELETE"
                        accent: "#F44336"
                        onClicked: deleteDialog.show(card.modelData)
                    }
                }
            }
        }
    }

    // ── Small reusable bits ──────────────────────────────────────────
    component Badge : Rectangle {
        id: badge
        property string text: ""
        property color accent: "#666666"
        implicitWidth: badgeLabel.implicitWidth + 12 * root.uiScale
        implicitHeight: 18 * root.uiScale
        radius: 4 * root.uiScale
        color: Qt.rgba(badge.accent.r, badge.accent.g, badge.accent.b, 0.15)
        border.color: badge.accent

        Text {
            id: badgeLabel
            anchors.centerIn: parent
            text: badge.text
            color: badge.accent
            font.pixelSize: 9 * root.uiScale
            font.bold: true
        }
    }

    component PillButton : Rectangle {
        id: pill
        property string text: ""
        property color accent: "#2196F3"
        signal clicked()

        implicitWidth: buttonLabel.implicitWidth + 22 * root.uiScale
        implicitHeight: 30 * root.uiScale
        radius: 15 * root.uiScale
        color: buttonMouse.containsMouse ? Qt.rgba(pill.accent.r, pill.accent.g, pill.accent.b, 0.2) : "transparent"
        border.color: pill.accent
        border.width: 1

        Text {
            id: buttonLabel
            anchors.centerIn: parent
            text: pill.text
            color: pill.accent
            font.pixelSize: 10 * root.uiScale
            font.bold: true
        }

        MouseArea {
            id: buttonMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: pill.clicked()
        }
    }

    // ── Difficulty / hand-mode chooser (shared with the dashboard picker) ──
    SongDifficultyDialog {
        id: difficultyPicker
        anchors.centerIn: parent
        onPlayStarted: root.isLoadingSong = true
    }

    // ── Rename dialog ────────────────────────────────────────────────
    Popup {
        id: renameDialog
        anchors.centerIn: parent
        width: 420 * root.uiScale
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property string songId: ""

        function show(song) {
            songId = song.id;
            titleField.text = song.title || "";
            artistField.text = song.artist || "";
            open();
            titleField.focusField();
        }

        function commit() {
            if (titleField.text.trim().length === 0)
                return;
            root.music21.rename_user_song(renameDialog.songId, titleField.text, artistField.text);
            renameDialog.close();
        }

        background: Rectangle {
            color: "#1c1c1e"
            radius: 12 * root.uiScale
            border.color: "#2196F3"
        }

        contentItem: ColumnLayout {
            spacing: 12 * root.uiScale

            Text {
                text: "RENAME SONG"
                color: "#666666"
                font.pixelSize: 11 * root.uiScale
                font.bold: true
                font.letterSpacing: 3 * root.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 6 * root.uiScale
            }

            Text {
                text: "The song keeps its id, so its levels and progress carry over."
                color: "#666666"
                font.pixelSize: 10 * root.uiScale
                Layout.alignment: Qt.AlignHCenter
            }

            LabeledField { id: titleField; label: "TITLE" }
            LabeledField { id: artistField; label: "ARTIST" }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: 8 * root.uiScale
                spacing: 10 * root.uiScale

                PillButton {
                    text: "CANCEL"
                    accent: "#888888"
                    onClicked: renameDialog.close()
                }
                PillButton {
                    text: "SAVE"
                    accent: "#4CAF50"
                    onClicked: renameDialog.commit()
                }
            }
        }
    }

    component LabeledField : Rectangle {
        id: field
        property string label: ""
        property alias text: fieldInput.text

        Layout.fillWidth: true
        Layout.leftMargin: 16 * root.uiScale
        Layout.rightMargin: 16 * root.uiScale
        implicitHeight: 46 * root.uiScale
        color: "#2a2a2a"
        radius: 8 * root.uiScale
        border.color: fieldInput.activeFocus ? "#2196F3" : "#444444"

        function focusField() { fieldInput.forceActiveFocus(); }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 12 * root.uiScale
            anchors.rightMargin: 12 * root.uiScale
            anchors.topMargin: 5 * root.uiScale
            anchors.bottomMargin: 5 * root.uiScale
            spacing: 0

            Text {
                text: field.label
                color: "#666666"
                font.pixelSize: 9 * root.uiScale
                font.bold: true
                font.letterSpacing: 1.5 * root.uiScale
            }

            TextInput {
                id: fieldInput
                Layout.fillWidth: true
                color: "white"
                font.pixelSize: 14 * root.uiScale
                selectByMouse: true
                clip: true
                onAccepted: renameDialog.commit()
            }
        }
    }

    // ── Delete confirmation ──────────────────────────────────────────
    Popup {
        id: deleteDialog
        anchors.centerIn: parent
        width: 420 * root.uiScale
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property string songId: ""
        property string songTitle: ""

        function show(song) {
            songId = song.id;
            songTitle = song.title || song.id;
            open();
        }

        background: Rectangle {
            color: "#1c1c1e"
            radius: 12 * root.uiScale
            border.color: "#F44336"
        }

        contentItem: ColumnLayout {
            spacing: 12 * root.uiScale

            Text {
                text: "DELETE SONG"
                color: "#F44336"
                font.pixelSize: 11 * root.uiScale
                font.bold: true
                font.letterSpacing: 3 * root.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 6 * root.uiScale
            }

            Text {
                text: "Remove \"" + deleteDialog.songTitle + "\" from your library? This deletes the imported score and its archived source file."
                color: "#cccccc"
                font.pixelSize: 13 * root.uiScale
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
                Layout.leftMargin: 20 * root.uiScale
                Layout.rightMargin: 20 * root.uiScale
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: 8 * root.uiScale
                spacing: 10 * root.uiScale

                PillButton {
                    text: "KEEP IT"
                    accent: "#888888"
                    onClicked: deleteDialog.close()
                }
                PillButton {
                    text: "DELETE"
                    accent: "#F44336"
                    onClicked: {
                        var err = root.music21.delete_user_song(deleteDialog.songId);
                        deleteDialog.close();
                        root.statusMessage = err ? err : "";
                    }
                }
            }
        }
    }

    // ── Duplicate cleanup ────────────────────────────────────────────
    Popup {
        id: duplicatesDialog
        anchors.centerIn: parent
        width: 520 * root.uiScale
        height: Math.min(root.height * 0.8, 560 * root.uiScale)
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        background: Rectangle {
            color: "#1c1c1e"
            radius: 12 * root.uiScale
            border.color: "#FF9800"
        }

        contentItem: ColumnLayout {
            spacing: 10 * root.uiScale

            Text {
                text: "DUPLICATE SONGS"
                color: "#FF9800"
                font.pixelSize: 11 * root.uiScale
                font.bold: true
                font.letterSpacing: 3 * root.uiScale
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: 6 * root.uiScale
            }

            Text {
                text: "These songs came from the same file. Delete the copies you don't want to keep."
                color: "#888888"
                font.pixelSize: 12 * root.uiScale
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                Layout.fillWidth: true
                Layout.leftMargin: 16 * root.uiScale
                Layout.rightMargin: 16 * root.uiScale
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 12 * root.uiScale
                Layout.rightMargin: 12 * root.uiScale
                clip: true

                ColumnLayout {
                    width: duplicatesDialog.width - 40 * root.uiScale
                    spacing: 12 * root.uiScale

                    Repeater {
                        model: root.duplicateGroups
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 4 * root.uiScale

                            Text {
                                text: modelData.count + " copies · " + ("" + modelData.source_hash).substring(0, 8)
                                color: "#666666"
                                font.pixelSize: 10 * root.uiScale
                                font.bold: true
                            }

                            Repeater {
                                model: modelData.songs
                                delegate: Rectangle {
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 44 * root.uiScale
                                    radius: 8 * root.uiScale
                                    color: "#2a2a2a"
                                    border.color: "#444444"

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 12 * root.uiScale
                                        anchors.rightMargin: 12 * root.uiScale
                                        spacing: 10 * root.uiScale

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 0
                                            Text {
                                                text: modelData.title
                                                color: "#ffffff"
                                                font.pixelSize: 12 * root.uiScale
                                                font.bold: true
                                                Layout.fillWidth: true
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                text: (index === 0 ? "oldest · " : "") + (modelData.imported_at || "")
                                                color: "#666666"
                                                font.pixelSize: 10 * root.uiScale
                                            }
                                        }

                                        PillButton {
                                            text: "DELETE"
                                            accent: "#F44336"
                                            onClicked: {
                                                var err = root.music21.delete_user_song(modelData.id);
                                                root.statusMessage = err ? err : "";
                                                if (root.duplicateGroups.length === 0)
                                                    duplicatesDialog.close();
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            PillButton {
                text: "DONE"
                accent: "#888888"
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: 10 * root.uiScale
                onClicked: duplicatesDialog.close()
            }
        }
    }

    // ── Drag-and-drop import ─────────────────────────────────────────
    DropArea {
        anchors.fill: parent

        onEntered: function (drag) {
            drag.accepted = drag.hasUrls;
            root.dragActive = drag.hasUrls;
        }
        onExited: root.dragActive = false
        onDropped: function (drop) {
            root.dragActive = false;
            if (drop.hasUrls) {
                root.enqueueUrls(drop.urls);
                drop.accept();
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 12 * root.uiScale
        radius: 16 * root.uiScale
        visible: root.dragActive
        color: "#2196F318"
        border.color: "#2196F3"
        border.width: 2 * root.uiScale
        z: 150

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 10 * root.uiScale

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "⬇"
                color: "#2196F3"
                font.pixelSize: 42 * root.uiScale
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Drop MIDI or MusicXML files"
                color: "#ffffff"
                font.pixelSize: 20 * root.uiScale
                font.bold: true
            }
        }
    }

    // ── Song loading overlay ─────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: "#121212E0"
        visible: root.isLoadingSong
        z: 200

        MouseArea { anchors.fill: parent }

        ColumnLayout {
            anchors.centerIn: parent
            spacing: 20 * root.uiScale

            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                width: 56 * root.uiScale
                height: 56 * root.uiScale
                radius: width / 2
                color: "transparent"
                border.color: "#2196F3"
                border.width: 4 * root.uiScale
                clip: true

                RotationAnimator on rotation {
                    from: 0; to: 360
                    duration: 900
                    loops: Animation.Infinite
                    running: root.isLoadingSong
                }
            }

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Loading Song…"
                color: "#ffffff"
                font.pixelSize: 18 * root.uiScale
                font.bold: true
            }
        }
    }
}
