"""
Every QML file must compile.

QML is resolved at runtime, so a bad import, a typo in a property name or a
component that cannot be found does not fail a build — it fails when the user
opens that screen, often as a blank pane with a warning on stderr nobody reads.
The Python suite covered the renderer thoroughly and the QML around it not at
all, which is the wrong way round for a file like EnhancedSheetMusic.qml that
owns the scroll path.

This compiles each component the way the engine does. It does not instantiate
them: most reference the `appState` and `mainWindow` context objects the app
injects, and binding failures against those are a runtime concern, not the
structural breakage this is here to catch.
"""

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine


@pytest.fixture(scope="module")
def engine(qapp):
    """An engine set up with the app's import paths and registered types."""
    from PySide6.QtQml import qmlRegisterType
    from ui.notation_view import NotationView

    # EnhancedSheetMusic.qml does `import ChordCoach 1.0` for NotationView.
    qmlRegisterType(NotationView, "ChordCoach", 1, 0, "NotationView")

    e = QQmlEngine()
    yield e
    e.deleteLater()


def _qml_files(qml_dir):
    return sorted(qml_dir.glob("*.qml"))


def test_there_are_components_to_check(qml_dir):
    """Guards against the glob silently matching nothing and vacuously passing."""
    assert len(_qml_files(qml_dir)) >= 5


def test_every_component_compiles(engine, qml_dir):
    """A compile error in any component is a broken screen in the app."""
    engine.addImportPath(str(qml_dir.parent))

    failures = []
    for path in _qml_files(qml_dir):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        if component.isError():
            failures.append(
                f"\n{path.name}:\n  " +
                "\n  ".join(e.toString() for e in component.errors())
            )

    assert not failures, "QML components failed to compile:" + "".join(failures)


def test_views_compile(engine, qml_dir):
    """The top-level views, which pull the components together."""
    ui_dir = qml_dir.parent
    engine.addImportPath(str(ui_dir))

    failures = []
    for path in sorted(ui_dir.glob("*.qml")):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        if component.isError():
            failures.append(
                f"\n{path.name}:\n  " +
                "\n  ".join(e.toString() for e in component.errors())
            )

    assert not failures, "QML views failed to compile:" + "".join(failures)
