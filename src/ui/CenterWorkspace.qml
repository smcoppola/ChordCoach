import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: root
    color: "#121212"
    
    StackView {
        id: workspaceStack
        anchors.fill: parent
        initialItem: dashboardComponent
        
        replaceEnter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 } }
        replaceExit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 200 } }
    }

    function goHome() {
        if (appState && appState.appCoordinator) {
            appState.appCoordinator.stopSession();
        }
        workspaceStack.replace(dashboardComponent);
    }

    function showLibrary() {
        workspaceStack.replace(libraryComponent);
    }
    // ── Watch for isCircleOfFifthsMode changes to route automatically ──────

    // ── Watch for isCircleOfFifthsMode changes to route automatically ──────
    Connections {
        target: (typeof appState !== "undefined" && appState !== null && appState.chordTrainer) ? appState.chordTrainer : null

        function onIsCircleOfFifthsModeChanged(active) {
            if (active) {
                workspaceStack.replace(circleViewComponent);
            } else {
                if (workspaceStack.currentItem && workspaceStack.currentItem.toString().indexOf("CircleOfFifthsView") >= 0) {
                    workspaceStack.replace(dashboardComponent);
                }
            }
        }
    }

    // ── Global Signal Relay for Repertoire Catalog ──
    Connections {
        target: (typeof appState !== "undefined" && appState !== null && appState.music21Service) ? appState.music21Service : null
        
        function onSongRequested(songId) {
            console.log("CenterWorkspace: Song requested via global signal: " + songId);
            if (appState && appState.chordTrainer) {
                // Important: Python handles the heavy lifting, we just route the view
                appState.chordTrainer.start_song(songId);
                
                // Ensure we are not stuck in a transition
                if (workspaceStack.depth > 0) {
                    workspaceStack.replace(trainerViewComponent);
                } else {
                    workspaceStack.push(trainerViewComponent);
                }
            }
        }
    }
    
    Component {
        id: dashboardComponent
        DashboardView {
            onStartLesson: function(minutes) {
                if (appState && appState.chordTrainer) {
                    appState.chordTrainer.start_lesson_plan(minutes);
                    if (!appState.chordTrainer.isCircleOfFifthsMode) {
                        workspaceStack.replace(trainerViewComponent);
                    }
                }
            }
            onStartSpecificDrill: function(track, milestoneId) {
                if (appState && appState.chordTrainer) {
                    appState.chordTrainer.start_single_drill(track, milestoneId);
                    if (!appState.chordTrainer.isCircleOfFifthsMode) {
                        workspaceStack.replace(trainerViewComponent);
                    }
                }
            }
            onStartReview: {
                if (appState && appState.chordTrainer) {
                    appState.chordTrainer.start_review_session();
                    workspaceStack.replace(trainerViewComponent);
                }
            }
            onFreePractice: {
                workspaceStack.replace(trainerViewComponent);
            }
            onOpenLibrary: {
                workspaceStack.replace(libraryComponent);
            }
        }
    }

    Component {
        id: libraryComponent
        LibraryView {
            onReturnToDashboard: {
                workspaceStack.replace(dashboardComponent);
            }
        }
    }
    
    Component {
        id: trainerViewComponent
        ChordTrainerView {
            onReturnToDashboard: {
                workspaceStack.replace(dashboardComponent);
            }
        }
    }

    Component {
        id: circleViewComponent
        CircleOfFifthsView {
            onReturnToDashboard: {
                workspaceStack.replace(dashboardComponent);
            }
        }
    }
}
