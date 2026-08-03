import os
import sys
import pytest

# Ensure src directory is in sys.path for test resolution
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)


def _create_qt_app():
    """
    Creates the process-wide Qt application at conftest import time.

    This must happen before any test module runs. Qt permits exactly one
    application object per process and a QCoreApplication cannot be promoted to
    a QGuiApplication, so if a test creates a bare QCoreApplication first (as
    test_evaluation_regression does for QTimer), any later font or paint call
    crashes with an access violation. Creating the GUI application up front
    satisfies both: QGuiApplication is a QCoreApplication, so
    QCoreApplication.instance() finds it and reuses it.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover - PySide6 always present in dev
        return None

    existing = QGuiApplication.instance()
    if existing is not None:
        return existing
    return QGuiApplication([])


_QT_APP = _create_qt_app()


@pytest.fixture(scope="session")
def qapp():
    """The headless Qt application shared by every test that touches Qt."""
    if _QT_APP is None:
        pytest.skip("PySide6 is unavailable")
    return _QT_APP


@pytest.fixture(scope="session")
def notation_fonts(qapp):
    """Registers the bundled fonts so label metrics match what the app renders."""
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase

    font_dir = Path(src_path) / "resources" / "fonts"
    if font_dir.exists():
        for pattern in ("*.ttf", "*.otf"):
            for font_file in font_dir.glob(pattern):
                QFontDatabase.addApplicationFont(os.fspath(font_file))
    return qapp


@pytest.fixture(scope="session")
def qml_dir():
    """The components directory the app loads QML from."""
    from pathlib import Path
    d = Path(src_path) / "ui" / "components"
    assert d.is_dir(), f"QML component directory not found: {d}"
    return d


@pytest.fixture
def tmp_user_songs_dir(tmp_path, monkeypatch):
    """Fixture that isolates user_songs directory for tests to avoid writing to live user database."""
    test_user_songs = tmp_path / "user_songs"
    test_user_songs.mkdir(parents=True, exist_ok=True)
    from logic.services.music21_service import Music21Service
    monkeypatch.setattr(Music21Service, "_user_songs_dir", lambda self: test_user_songs)
    return test_user_songs
