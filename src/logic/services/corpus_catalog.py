"""The corpus song browser: catalogue, search, recents, corpus download."""
import json
import re
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, Property, QThread
import music21
from music21 import corpus
from core.bootstrap import get_user_data_dir

USER_SONG_PREFIX = "user::"


class CorpusDownloadWorker(QThread):
    """Background worker to download the music21 corpus without locking the UI."""
    progress = Signal(float)
    finished = Signal(bool)
    status = Signal(str)

    def __init__(self):
        super().__init__()
        self.auto_retry_done = False

    def run(self):
        from logic.utils.corpus_manager import CorpusManager
        try:
            self.status.emit("Connecting to PyPI...")
            if CorpusManager.download_and_extract(progress_callback=self.progress.emit):
                self.finished.emit(True)
                return
        except Exception as e:
            print(f"CorpusDownloadWorker: First attempt failed: {e}")
            if not self.auto_retry_done:
                self.auto_retry_done = True
                self.status.emit("Connection lost. Retrying once...")
                time.sleep(2)
                try:
                    if CorpusManager.download_and_extract(progress_callback=self.progress.emit):
                        self.finished.emit(True)
                        return
                except Exception as e2:
                    print(f"CorpusDownloadWorker: Retry failed: {e2}")

        self.finished.emit(False)


class CorpusCatalog(QObject):
    """
    The built-in music21 corpus as the song browser sees it: the category
    tree, search, recently played pieces, and the one-time corpus download.

    Imported songs belong to SongLibrary; the browser shows them under
    "My Songs", so the catalog is handed a `user_songs` callable to list them.
    """
    corpusProgressChanged = Signal(float)
    corpusStatusChanged = Signal(str)
    corpusReady = Signal()
    corpusError = Signal()

    def __init__(self, project_root=None, user_songs=None):
        super().__init__()
        self._project_root = project_root
        self._user_songs = user_songs or (lambda: [])
        self._catalog = {}
        self._recent_songs = []
        self._flat_catalog = []

        self._corpus_progress = 0.0
        self._corpus_status = ""
        self._corpus_ready = False
        self._corpus_error = False
        self._download_worker = None

        self._setup_local_corpus()
        self._load_catalog()
        self._load_recents()

    def tree(self):
        """The whole category tree, as loaded from music21_catalog.json."""
        return self._catalog

    @Property(float, notify=corpusProgressChanged)
    def corpusProgress(self): return self._corpus_progress

    @Property(str, notify=corpusStatusChanged)
    def corpusStatus(self): return self._corpus_status

    @Property(bool, notify=corpusReady)
    def isCorpusReady(self): return self._corpus_ready

    @Property(bool, notify=corpusError)
    def hasCorpusError(self): return self._corpus_error

    @Slot()
    def trigger_corpus_download(self):
        if self._download_worker and self._download_worker.isRunning():
            return
        self._corpus_error = False
        self.corpusError.emit()
        self._download_worker = CorpusDownloadWorker()
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.status.connect(self._on_download_status)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_progress(self, progress: float):
        self._corpus_progress = progress
        self.corpusProgressChanged.emit(progress)

    def _on_download_status(self, status: str):
        self._corpus_status = status
        self.corpusStatusChanged.emit(status)

    def _on_download_finished(self, success: bool):
        if success:
            from logic.utils.corpus_manager import CorpusManager
            CorpusManager.configure_environment()
            self._corpus_ready = True
            self._corpus_status = "Corpus Ready"
            self.corpusReady.emit()
            self._load_catalog()
        else:
            self._corpus_error = True
            self.corpusError.emit()

    def _setup_local_corpus(self):
        from logic.utils.corpus_manager import CorpusManager
        if CorpusManager.is_corpus_present():
            self._corpus_ready = True
        else:
            print("Music21Service: Core corpus not found locally.")

    def _load_catalog(self):
        cat_file = get_user_data_dir() / "database" / "music21_catalog.json"
        if not cat_file.exists():
            if self._project_root:
                cat_file = Path(self._project_root) / "database" / "music21_catalog.json"
            else:
                cat_file = Path(__file__).parent.parent.parent.parent / "database" / "music21_catalog.json"
        try:
            if cat_file.exists():
                with open(cat_file, "r") as f:
                    self._catalog = json.load(f)
                self._flat_catalog = self._flatten_catalog(self._catalog)
                print(f"Music21Service: Loaded hierarchical catalog with {len(self._flat_catalog)} tracks from {cat_file}")
            else:
                print(f"Music21Service: Catalog file not found at {cat_file}")
                self._catalog = {}
                self._flat_catalog = []
        except Exception as e:
            print(f"Music21Service: Error loading catalog from {cat_file}: {e}")
            self._catalog = {}
            self._flat_catalog = []

    def _flatten_catalog(self, node):
        songs = []
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    if item.get("isCategory") and "children" in item:
                        songs.extend(self._flatten_catalog(item["children"]))
                    else:
                        songs.append(item)
        elif isinstance(node, dict):
            for v in node.values():
                songs.extend(self._flatten_catalog(v))
        return songs

    @Slot(list, result="QVariantList")
    def get_catalog_level(self, path):
        if path and path[0] == "My Songs":
            return list(reversed(self._user_songs()))

        node = self._catalog
        for segment in path:
            if isinstance(node, dict) and segment in node:
                node = node[segment]
            elif isinstance(node, list):
                found = False
                for item in node:
                    if isinstance(item, dict) and item.get("id") == segment:
                        node = item.get("children", [])
                        found = True
                        break
                if not found:
                    return []
            else:
                return []

        if isinstance(node, list):
            return node

        if isinstance(node, dict):
            def natural_sort_key(s):
                return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

            if len(path) == 0:
                keys = sorted(node.keys(), key=natural_sort_key)
            else:
                keys = sorted(node.keys())
            entries = [{"id": k, "isCategory": True} for k in keys]
            if len(path) == 0 and self._user_songs():
                entries.insert(0, {"id": "My Songs", "isCategory": True})
            return entries

        return []

    def _load_recents(self):
        try:
            p = get_user_data_dir() / "database" / "recent_songs.json"
            if p.exists():
                with open(p, "r") as f:
                    self._recent_songs = json.load(f)
        except Exception:
            self._recent_songs = []

    def _save_recents(self):
        try:
            p = get_user_data_dir() / "database" / "recent_songs.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w") as f:
                json.dump(self._recent_songs, f)
        except Exception:
            pass

    @Slot(result="QVariantList")
    def get_recent_songs(self):
        res = []
        lookup = {s['id']: s for s in self._flat_catalog}
        lookup.update({s['id']: s for s in self._user_songs()})
        for sid in self._recent_songs:
            if sid in lookup:
                res.append(lookup[sid])
        return res[:5]

    def get_recent_corpus_ids(self, limit: int = 5) -> list:
        """Recently played corpus pieces (imported songs excluded), newest first."""
        ids = [sid for sid in self._recent_songs
               if not str(sid).startswith(USER_SONG_PREFIX)]
        return ids[:limit]

    @Slot(str, result="QVariantList")
    def search_catalog(self, query):
        if not query or len(query) < 2:
            return []
        q = query.lower()
        matches = []
        for song in self._user_songs() + self._flat_catalog:
            title = song.get("title", "").lower()
            artist = song.get("artist", "").lower()
            if q in title or q in artist:
                matches.append(song)
            if len(matches) >= 50:
                break
        return matches

    @Slot(str)
    def mark_song_played(self, song_id):
        if song_id in self._recent_songs:
            self._recent_songs.remove(song_id)
        self._recent_songs.insert(0, song_id)
        self._recent_songs = self._recent_songs[:10]
        self._save_recents()

    @Slot(result="QVariantList")
    def get_catalog(self):
        return self.get_catalog_level([])
