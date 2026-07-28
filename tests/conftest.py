import os
import sys
import pytest

# Ensure src directory is in sys.path for test resolution
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)


@pytest.fixture
def tmp_user_songs_dir(tmp_path, monkeypatch):
    """Fixture that isolates user_songs directory for tests to avoid writing to live user database."""
    test_user_songs = tmp_path / "user_songs"
    test_user_songs.mkdir(parents=True, exist_ok=True)
    from logic.services.music21_service import Music21Service
    monkeypatch.setattr(Music21Service, "_user_songs_dir", lambda self: test_user_songs)
    return test_user_songs
