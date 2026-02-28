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
    
    Component {
        id: dashboardComponent
        DashboardView {
            onStartLesson: {
                if (appState && appState.chordTrainer) {
                    appState.chordTrainer.start_lesson_plan();
                    workspaceStack.replace(trainerViewComponent);
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
}
