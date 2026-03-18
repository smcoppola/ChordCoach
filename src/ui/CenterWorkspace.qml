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
