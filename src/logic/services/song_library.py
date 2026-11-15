"""The student's imported songs: storage, import, levels, editing."""
import copy
import hashlib
import json
import re
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QThread
import music21
from music21 import note
from logic.utils.step_schema import CURRENT_SCHEMA_VERSION, migrate_record, compute_barlines, groups_from_steps
from core.bootstrap import get_user_data_dir

USER_SONG_PREFIX = "user::"


class ImportWorker(QThread):
    """Background worker running file import off the UI thread."""
    succeeded = Signal(str, dict)  # song_id, catalog entry
    failed = Signal(str)           # error message

    def __init__(self, service, path: str):
        super().__init__()
        self._service = service
        self._path = path

    def run(self):
        try:
            ext = Path(self._path).suffix.lower()
            if ext in (".xml", ".mxl", ".musicxml"):
                song_id, entry = self._service._do_import_musicxml(self._path)
            else:
                song_id, entry = self._service._do_import_midi(self._path)
            self.succeeded.emit(song_id, entry)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


class SimplifyWorker(QThread):
    """Background worker for non-blocking song difficulty level regeneration."""
    succeeded = Signal(str, dict)
    failed = Signal(str)

    def __init__(self, service, song_id: str):
        super().__init__()
        self._service = service
        self._song_id = song_id

    def run(self):
        try:
            res = self._service._regenerate_level_steps(self._song_id)
            self.succeeded.emit(self._song_id, res)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))


class SongLibrary(QObject):
    """
    The student's imported songs: one JSON record per song on disk, import
    (MIDI and MusicXML), difficulty levels, hand assignment, the note editor's
    load and save, per-song practice preferences, rename, delete, duplicates.

    Turning a score into playable steps is Music21Service's job; the library
    is handed the three functions it needs for that rather than the service.
    """
    songRequested = Signal(str)
    userSongsChanged = Signal()
    importSucceeded = Signal(str)       # song_id
    importFailed = Signal(str)          # error message
    importDuplicate = Signal(str, str)   # existing_song_id, existing_title
    songLevelFailed = Signal(str)        # error message (async level generation)

    USER_SONG_PREFIX = USER_SONG_PREFIX

    SIMPLIFY_LEVELS = {
        1: {"min_gap": 1.0,  "rh_notes": 2, "lh_notes": 1, "rh_span": 7,  "lh_span": 0},
        2: {"min_gap": 0.5,  "rh_notes": 3, "lh_notes": 1, "rh_span": 9,  "lh_span": 0},
        3: {"min_gap": 0.5,  "rh_notes": 4, "lh_notes": 2, "rh_span": 12, "lh_span": 7},
        4: {"min_gap": 0.25, "rh_notes": 5, "lh_notes": 3, "rh_span": 14, "lh_span": 12},
    }

    # Per-note parallel arrays that must survive an edit round trip.
    STEP_NOTE_ARRAYS = (
        "pitches", "spellings", "hands", "fingers", "durations",
        "ties", "beams", "tuplets", "articulations", "velocities",
    )

    _STEP_ARRAY_DEFAULTS = {
        "pitches": 60, "spellings": None, "hands": "right", "fingers": 1,
        "durations": 1.0, "ties": None, "beams": None, "tuplets": None,
        "articulations": (), "velocities": None,
    }

    # A staff cannot be drawn or a bar previewed without these three, and the
    # light _user_songs catalog deliberately carries none of them, so this is a
    # record read. Kept separate from get_user_song_barlines rather than folded
    # into it: that slot has its own caller and merging would orphan it.
    NOTATION_CONTEXT_DEFAULTS = {
        "key_sharps": 0,
        "time_signatures": [{"offset": 0.0, "numerator": 4, "denominator": 4}],
        "bpm": 100.0,
    }

    def __init__(self, extract_steps, build_score, score_difficulty):
        super().__init__()
        self._extract_steps_from_score = extract_steps
        self._build_score_from_groups = build_score
        self._score_difficulty = score_difficulty

        self._user_songs = []
        self._import_worker = None
        self._simplify_worker = None
        self._level_cache = {}

        # Optional collaborators, set after construction.
        self._db = None            # for mastery in the library view
        self._active_song = None   # callable() -> id of the song being practised, or ""

        print(f"SongLibrary: User songs directory = {self._user_songs_dir()}")
        self._load_user_songs()

    def set_database(self, db):
        """The DatabaseManager, so the library view can show mastery."""
        self._db = db

    def set_active_song(self, active_song):
        """`active_song()` returns the id of the song being practised right now, or ""."""
        self._active_song = active_song

    def _song_in_play(self, base_id: str) -> bool:
        """Whether this song (at any difficulty level) is the one being practised."""
        if self._active_song is None:
            return False
        try:
            active = str(self._active_song() or "")
            return bool(active) and self._base_song_id(active) == base_id
        except Exception as e:
            print(f"SongLibrary: Could not check the active song: {e}")
            return False

    def entries(self) -> list:
        """The light catalog entries of every imported song."""
        return self._user_songs

    def cached_steps(self, song_id: str):
        """Steps already generated for a difficulty level, or None."""
        return self._level_cache.get(song_id)

    def load_steps(self, song_id: str) -> dict:
        return self._load_user_song_steps(song_id)

    def _user_songs_dir(self) -> Path:
        p = get_user_data_dir() / "database" / "user_songs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _load_user_songs(self):
        self._user_songs = []
        user_dir = self._user_songs_dir()
        for json_path in user_dir.glob("*.json"):
            try:
                with open(json_path, "r") as f:
                    rec = json.load(f)
                if "id" in rec and "title" in rec:
                    rec = migrate_record(rec)
                    self._user_songs.append({
                        "id": rec["id"],
                        "title": rec["title"],
                        "artist": rec.get("artist", "Imported Song"),
                        "level": rec.get("level", "Imported"),
                        "source_hash": rec.get("source_hash"),
                        # Light metadata for the library view, cached here so
                        # get_user_songs() never has to re-read the (large) records.
                        "key": rec.get("key", ""),
                        "source_type": rec.get("source_type", ""),
                        "hand_mode": rec.get("hand_mode", "auto"),
                        "practice_mode": rec.get("practice_mode", "self_paced"),
                        "imported_at": rec.get("imported_at", ""),
                    })
            except Exception as e:
                print(f"SongLibrary: Error reading user song {json_path}: {e}")
        print(f"SongLibrary: Loaded {len(self._user_songs)} imported user songs")

    @Slot(str)
    def import_file(self, file_url: str):
        path = file_url
        if path.startswith("file:"):
            from PySide6.QtCore import QUrl
            path = QUrl(file_url).toLocalFile()

        try:
            with open(path, "rb") as f:
                src_bytes = f.read()
            src_hash = hashlib.sha1(src_bytes).hexdigest()
            for s in self._user_songs:
                if s.get("source_hash") == src_hash:
                    print(f"SongLibrary: Duplicate import detected for hash {src_hash}")
                    self.importDuplicate.emit(s["id"], s["title"])
                    return
        except Exception as e:
            print(f"SongLibrary: Hash calculation failed: {e}")

        if self._import_worker is not None and self._import_worker.isRunning():
            self.importFailed.emit("Another import is still running")
            return

        self._import_worker = ImportWorker(self, path)
        self._import_worker.succeeded.connect(self._on_import_succeeded)
        self._import_worker.failed.connect(self._on_import_failed)
        self._import_worker.start()

    @Slot(str)
    def import_midi_file(self, file_url: str):
        self.import_file(file_url)

    def _on_import_succeeded(self, song_id: str, entry: dict):
        self._user_songs.append(entry)
        self.userSongsChanged.emit()
        self.importSucceeded.emit(song_id)

    def _on_import_failed(self, error: str):
        print(f"SongLibrary: File import failed: {error}")
        self.importFailed.emit(error)

    @Slot(str)
    def request_song_level(self, song_id: str):
        if song_id in self._level_cache:
            self.songRequested.emit(song_id)
            return

        if self._simplify_worker is not None and self._simplify_worker.isRunning():
            self._simplify_worker.wait()

        self._simplify_worker = SimplifyWorker(self, song_id)
        self._simplify_worker.succeeded.connect(self._on_simplify_succeeded)
        self._simplify_worker.failed.connect(self._on_simplify_failed)
        self._simplify_worker.start()

    def _on_simplify_succeeded(self, song_id: str, res: dict):
        self._level_cache[song_id] = res
        self.songRequested.emit(song_id)

    def _on_simplify_failed(self, error: str):
        print(f"SongLibrary: Async level generation failed: {error}")
        # QML sets a loading spinner when requesting a level — clear it on failure too.
        self.songLevelFailed.emit(error)

    def _do_import_midi(self, path: str):
        from logic.services.midi_ingestor import parse_and_quantize, HAND_ALGO_VERSION
        quantized = parse_and_quantize(path)

        score, key_name, key_sharps = self._build_score_from_groups(
            quantized["groups"],
            time_signatures=quantized.get("time_signatures")
        )
        steps, barlines, extra_meta = self._extract_steps_from_score(score)
        if not steps:
            raise ValueError("No notation steps could be generated from this file")

        difficulty = self._score_difficulty(steps)
        level = f"Grade {difficulty}"
        slug = re.sub(r'[^a-z0-9]+', '-', quantized["title"].lower()).strip('-') or "song"
        song_id = f"{self.USER_SONG_PREFIX}{slug}-{int(time.time())}"

        track_hands_reliable = not quantized.get("single_track", False)
        pristine = copy.deepcopy(quantized["groups"]) if track_hands_reliable else None

        record = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "id": song_id,
            "title": quantized["title"],
            "artist": "Imported MIDI",
            "level": level,
            "key": key_name,
            "key_sharps": key_sharps,
            "bpm": quantized["bpm"],
            "time_signatures": quantized.get("time_signatures") or extra_meta.get("time_signatures"),
            "tempo_map": quantized.get("tempo_map") or extra_meta.get("tempo_map"),
            "pedal_events": quantized.get("pedal_events", []),
            "dynamics": extra_meta.get("dynamics", []),
            "source_type": "midi",
            "track_hands_reliable": track_hands_reliable,
            "pristine_groups": pristine,
            "hand_algo": HAND_ALGO_VERSION,
            "hand_mode": "auto",
            "barlines": barlines,
            "steps": steps,
            "quantized_groups": quantized["groups"],
            "source_file": path,
            "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return self._finalize_import(record, path)

    def _do_import_musicxml(self, path: str):
        score = music21.converter.parse(path)
        steps, barlines, extra_meta = self._extract_steps_from_score(score)
        if not steps:
            raise ValueError("No notation steps could be extracted from MusicXML score")

        try:
            analyzed = score.analyze('key')
            key_name = f"{analyzed.tonic.name} {analyzed.mode.capitalize()}"
            key_sharps = int(analyzed.sharps)
        except Exception:
            key_name, key_sharps = "C Major", 0

        title = Path(path).stem.replace("_", " ").replace("-", " ").strip().title()
        if hasattr(score, 'metadata') and score.metadata and score.metadata.title:
            title = score.metadata.title

        difficulty = self._score_difficulty(steps)
        level = f"Grade {difficulty}"
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or "song"
        song_id = f"{self.USER_SONG_PREFIX}{slug}-{int(time.time())}"

        quantized_groups = groups_from_steps(steps)

        record = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "id": song_id,
            "title": title,
            "artist": getattr(score.metadata, 'composer', 'Imported MusicXML') if hasattr(score, 'metadata') and score.metadata else "Imported MusicXML",
            "level": level,
            "key": key_name,
            "key_sharps": key_sharps,
            "bpm": extra_meta["tempo_map"][0]["bpm"] if extra_meta.get("tempo_map") else 100.0,
            "time_signatures": extra_meta.get("time_signatures"),
            "tempo_map": extra_meta.get("tempo_map"),
            "pedal_events": [],
            "dynamics": extra_meta.get("dynamics", []),
            "source_type": "musicxml",
            "track_hands_reliable": False,
            "pristine_groups": None,
            "hand_algo": 2,
            "hand_mode": "auto",
            "barlines": barlines,
            "steps": steps,
            "quantized_groups": quantized_groups,
            "source_file": path,
            "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return self._finalize_import(record, path)

    def _finalize_import(self, record: dict, source_path: str):
        try:
            with open(source_path, "rb") as f:
                src_bytes = f.read()
            src_hash = hashlib.sha1(src_bytes).hexdigest()
            ext = Path(source_path).suffix.lower()

            sources_dir = self._user_songs_dir() / "sources"
            sources_dir.mkdir(parents=True, exist_ok=True)
            copy_path = sources_dir / f"{src_hash}{ext}"
            if not copy_path.exists():
                with open(copy_path, "wb") as f_out:
                    f_out.write(src_bytes)

            record["source_hash"] = src_hash
            record["source_copy"] = f"sources/{src_hash}{ext}"
        except Exception as e:
            print(f"SongLibrary: Failed to archive source copy: {e}")

        record = migrate_record(record)
        song_id = record["id"]
        out_path = self._user_songs_dir() / f"{song_id.replace(self.USER_SONG_PREFIX, '')}.json"
        with open(out_path, "w") as f:
            json.dump(record, f, indent=2)

        entry = {
            "id": song_id,
            "title": record["title"],
            "artist": record["artist"],
            "level": record["level"],
            "source_hash": record.get("source_hash"),
            # Same light metadata _load_user_songs caches, so a freshly imported
            # song shows complete details in the library without a reload.
            "key": record.get("key", ""),
            "source_type": record.get("source_type", ""),
            "hand_mode": record.get("hand_mode", "auto"),
            "practice_mode": record.get("practice_mode", "self_paced"),
            "imported_at": record.get("imported_at", ""),
        }
        print(f"SongLibrary: Imported '{record['title']}' as {song_id} ({len(record['steps'])} steps)")
        return song_id, entry

    def _regenerate_level_steps(self, song_id: str) -> dict:
        level = 0
        base_id = song_id
        if "::L" in song_id:
            base_id, lv_str = song_id.rsplit("::L", 1)
            try:
                level = int(lv_str)
            except ValueError:
                level = 0

        path = self._user_song_path(base_id)
        with open(path, "r") as f:
            data = json.load(f)

        data = migrate_record(data)
        title = data.get("title", "Imported Song")

        result = {
            "schema_version": data.get("schema_version", CURRENT_SCHEMA_VERSION),
            "id": data.get("id"),
            "steps": data.get("steps", []),
            "title": title,
            "composer": data.get("artist", "Imported MIDI"),
            "artist": data.get("artist", "Imported MIDI"),
            "level": data.get("level"),
            "key": data.get("key", "Unknown Key"),
            "key_sharps": data.get("key_sharps", 0),
            "bpm": data.get("bpm", 100.0),
            "barlines": data.get("barlines", []),
            "time_signatures": data.get("time_signatures"),
            "tempo_map": data.get("tempo_map"),
            "pedal_events": data.get("pedal_events", []),
            "dynamics": data.get("dynamics", []),
            "source_type": data.get("source_type"),
            "source_file": data.get("source_file"),
            "source_hash": data.get("source_hash"),
            "source_copy": data.get("source_copy"),
            "track_hands_reliable": data.get("track_hands_reliable", False),
            "pristine_groups": data.get("pristine_groups"),
        }

        if level and data.get("quantized_groups"):
            groups = [
                {"offset": g["offset"], "duration": g["duration"],
                 "notes": [(int(p), h) for p, h in g["notes"]]}
                for g in data["quantized_groups"]
            ]
            simplified = self._simplify_groups(groups, level)
            score, _kn, _ks = self._build_score_from_groups(
                simplified,
                key_name=data.get("key"),
                key_sharps=data.get("key_sharps"),
                time_signatures=data.get("time_signatures")
            )
            steps, barlines, extra_meta = self._extract_steps_from_score(score)
            result.update({
                "steps": steps,
                "barlines": barlines,
                "title": f"{title} (Level {level})",
            })
            print(f"SongLibrary: Simplified '{title}' to Level {level}: {len(steps)} steps")

        return migrate_record(result)

    def _load_user_song_steps(self, song_id: str) -> dict:
        if song_id in self._level_cache:
            return self._level_cache[song_id]
        res = self._regenerate_level_steps(song_id)
        self._level_cache[song_id] = res
        return res

    def _simplify_groups(self, groups, level: int):
        cfg = self.SIMPLIFY_LEVELS.get(level)
        if not cfg:
            return groups
        min_gap = cfg["min_gap"]

        def aligned(off):
            return abs(off / min_gap - round(off / min_gap)) < 1e-6

        kept = [dict(g) for g in groups if aligned(g["offset"])]
        kept_offsets = {g["offset"] for g in kept}
        for g in groups:
            if aligned(g["offset"]):
                continue
            slot = round(g["offset"] / min_gap) * min_gap
            if slot >= 0 and slot not in kept_offsets:
                moved = dict(g)
                moved["offset"] = slot
                kept.append(moved)
                kept_offsets.add(slot)
        kept.sort(key=lambda g: g["offset"])

        out = []
        for g in kept:
            rh = sorted(p for p, h in g["notes"] if h == "right")
            lh = sorted(p for p, h in g["notes"] if h == "left")
            notes = []
            if rh:
                top = rh[-1]
                within = [p for p in rh if top - p <= cfg["rh_span"]]
                notes += [(p, "right") for p in within[-int(cfg["rh_notes"]):]]
            if lh:
                bottom = lh[0]
                if cfg["lh_span"] > 0:
                    within = [p for p in lh if p - bottom <= cfg["lh_span"]]
                else:
                    within = [bottom]
                notes += [(p, "left") for p in within[:int(cfg["lh_notes"])]]
            if notes:
                out.append({"offset": g["offset"], "duration": g["duration"], "notes": notes})
        return out

    def _user_song_path(self, song_id: str):
        base_id = song_id.rsplit("::L", 1)[0] if "::L" in song_id else song_id
        return self._user_songs_dir() / (base_id.replace(self.USER_SONG_PREFIX, "") + ".json")

    def _apply_hand_mode(self, groups, mode: str, record: dict = None):
        if mode == "manual":
            # Hands were set note by note in the editor. Every other branch here
            # re-infers them, and "auto" in particular restores them wholesale
            # from pristine_groups — which would silently revert the edits on the
            # next level regeneration. Leave them exactly as stored.
            return groups
        if mode in ("right", "left"):
            for g in groups:
                g["notes"] = [(p, mode) for p, _h in g["notes"]]
        elif mode == "split":
            for g in groups:
                g["notes"] = [(p, "right" if p >= 60 else "left") for p, _h in g["notes"]]
        else:
            if record and record.get("track_hands_reliable") and record.get("pristine_groups"):
                pristine = copy.deepcopy(record["pristine_groups"])
                for g_curr, g_orig in zip(groups, pristine):
                    orig_map = dict(g_orig["notes"])
                    g_curr["notes"] = [(p, orig_map.get(p, h)) for p, h in g_curr["notes"]]
            else:
                from logic.services.midi_ingestor import assign_hands
                assign_hands(groups)
        return groups

    def _rebuild_user_song_record(self, record: dict) -> dict:
        from logic.services.midi_ingestor import HAND_ALGO_VERSION
        groups = [
            {"offset": g["offset"], "duration": g["duration"],
             "notes": [(int(p), h) for p, h in g["notes"]]}
            for g in record.get("quantized_groups", [])
        ]
        if not groups:
            return record
        self._apply_hand_mode(groups, record.get("hand_mode", "auto"), record=record)
        score, _kn, _ks = self._build_score_from_groups(
            groups,
            key_name=record.get("key"),
            key_sharps=record.get("key_sharps"),
            time_signatures=record.get("time_signatures"))
        steps, barlines, extra_meta = self._extract_steps_from_score(score)
        record["quantized_groups"] = groups
        record["steps"] = steps
        record["barlines"] = barlines
        record["hand_algo"] = HAND_ALGO_VERSION
        return migrate_record(record)

    def _save_user_song_record(self, record: dict):
        record = migrate_record(record)
        with open(self._user_song_path(record["id"]), "w") as f:
            json.dump(record, f, indent=2)

    @Slot(str, str, result=str)
    @Slot(str, str, str, result=str)
    def get_user_song_pref(self, song_id: str, key: str, default: str = "") -> str:
        """Reads a free-form per-song preference (e.g. practice_mode) from its JSON record."""
        try:
            with open(self._user_song_path(song_id), "r") as f:
                return str(json.load(f).get(key, default))
        except Exception:
            return default

    @Slot(str, str, str)
    def set_user_song_pref(self, song_id: str, key: str, value: str):
        """
        Stores a free-form per-song preference on the song's JSON record.

        Unlike set_user_song_hand_mode this never rebuilds the score — these
        preferences (practice_mode, practice_hands) only affect how the piece is
        practised, not how it is notated, so no cache invalidation is needed.
        """
        try:
            path = self._user_song_path(song_id)
            with open(path, "r") as f:
                record = json.load(f)
            if str(record.get(key, "")) == str(value):
                return
            record[key] = value
            self._save_user_song_record(record)
            if key in ("practice_mode", "practice_hands"):
                self._update_user_song_entry(song_id, **{key: value})
            print(f"SongLibrary: Pref '{key}' for '{record.get('title')}' set to '{value}'")
        except Exception as e:
            print(f"SongLibrary: Failed to set pref '{key}': {e}")

    @Slot(str, result=str)
    def get_user_song_hand_mode(self, song_id: str) -> str:
        try:
            with open(self._user_song_path(song_id), "r") as f:
                return json.load(f).get("hand_mode", "auto")
        except Exception:
            return "auto"

    @Slot(str, str)
    def set_user_song_hand_mode(self, song_id: str, mode: str):
        from logic.services.midi_ingestor import HAND_ALGO_VERSION
        if mode not in ("auto", "split", "right", "left", "manual"):
            print(f"SongLibrary: Unknown hand mode '{mode}' ignored")
            return
        try:
            path = self._user_song_path(song_id)
            with open(path, "r") as f:
                record = json.load(f)
            if (record.get("hand_mode", "auto") == mode
                    and int(record.get("hand_algo", 1)) >= HAND_ALGO_VERSION):
                return
            record["hand_mode"] = mode
            record = self._rebuild_user_song_record(record)
            self._save_user_song_record(record)

            # Invalidate level cache for this song
            base_id = song_id.rsplit("::L", 1)[0] if "::L" in song_id else song_id
            keys_to_del = [k for k in self._level_cache if k == base_id or k.startswith(base_id + "::L")]
            for k in keys_to_del:
                self._level_cache.pop(k, None)

            self._update_user_song_entry(song_id, hand_mode=mode)
            print(f"SongLibrary: Hand mode for '{record.get('title')}' set to '{mode}'")
        except Exception as e:
            print(f"SongLibrary: Failed to set hand mode: {e}")

    @staticmethod
    def _snap_to_grid(value, grid: float, minimum: float) -> float:
        """Quantizes a beat or duration to the grid, never below `minimum`."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = minimum
        return round(max(minimum, round(v / grid) * grid), 4)

    @staticmethod
    def _measure_for_offset(barlines: list, offset: float) -> int:
        """1-based measure number for a beat offset, from the record's barlines."""
        import bisect
        return bisect.bisect_right(barlines, float(offset) + 1e-6) + 1

    @Slot(str, result="QVariantList")
    def get_user_song_notes(self, song_id: str):
        """
        Flattens a song's steps into one row per note for the editor table.

        `step_index`/`note_index` are provenance: save_user_song_notes uses them
        to carry every attribute the table does not show (spelling, finger,
        velocity, articulations) back onto the rebuilt step.
        """
        from logic.utils.pitch_names import pitch_name_with_octave
        try:
            with open(self._user_song_path(song_id), "r") as f:
                record = migrate_record(json.load(f))
        except Exception as e:
            print(f"SongLibrary: Could not read notes for {song_id}: {e}")
            return []

        barlines = record.get("barlines") or []
        rows = []
        for si, step in enumerate(record.get("steps", [])):
            offset = float(step.get("offset", 0.0))
            measure = self._measure_for_offset(barlines, offset)
            pitches = step.get("pitches", [])
            hands = step.get("hands", [])
            durations = step.get("durations", [])
            fingers = step.get("fingers", [])
            for ni, pitch in enumerate(pitches):
                rows.append({
                    "beat": round(offset, 4),
                    "duration": round(float(durations[ni]) if ni < len(durations)
                                      else float(step.get("duration", 1.0)), 4),
                    "hand": hands[ni] if ni < len(hands) else "right",
                    "pitch": int(pitch),
                    "name": pitch_name_with_octave(pitch),
                    "measure": measure,
                    # Display only, and the editor never edits it: the notation
                    # strip colours noteheads by finger, so without it every
                    # previewed note renders in the finger-0 fallback black and
                    # the strip stops matching the sheet being practised.
                    "finger": int(fingers[ni]) if ni < len(fingers) else 1,
                    "step_index": si,
                    "note_index": ni,
                })

        rows.sort(key=lambda r: (r["beat"], r["pitch"]))
        return rows

    @Slot(str, result="QVariantList")
    def get_user_song_barlines(self, song_id: str):
        """
        The song's barline offsets, so the editor can renumber a note's measure
        the moment its beat changes instead of showing a stale one until reload.
        """
        try:
            with open(self._user_song_path(song_id), "r") as f:
                return [float(b) for b in (json.load(f).get("barlines") or [])]
        except Exception:
            return []

    @Slot(str, result="QVariantMap")
    def get_user_song_notation_context(self, song_id: str):
        """
        Key signature, metre and tempo for the editor's notation strip.

        Always returns a usable map — an unreadable song, or one stored without
        a metre, still yields 4/4 in C at 100bpm — so the strip has no null
        branch and renders a plausible staff instead of nothing.
        """
        import copy
        ctx = copy.deepcopy(self.NOTATION_CONTEXT_DEFAULTS)
        try:
            with open(self._user_song_path(self._base_song_id(song_id)), "r") as f:
                record = migrate_record(json.load(f))
        except Exception as e:
            print(f"SongLibrary: Could not read notation context for {song_id}: {e}")
            return ctx

        try:
            ctx["key_sharps"] = int(record.get("key_sharps") or 0)
        except (TypeError, ValueError):
            pass
        try:
            bpm = float(record.get("bpm") or 0.0)
            if bpm > 0:
                ctx["bpm"] = bpm
        except (TypeError, ValueError):
            pass

        signatures = []
        for ts in (record.get("time_signatures") or []):
            try:
                num = int(ts.get("numerator", 4))
                den = int(ts.get("denominator", 4))
                if num > 0 and den > 0:
                    signatures.append({
                        "offset": float(ts.get("offset", 0.0)),
                        "numerator": num,
                        "denominator": den,
                    })
            except (TypeError, ValueError, AttributeError):
                continue
        if signatures:
            signatures.sort(key=lambda s: s["offset"])
            ctx["time_signatures"] = signatures
        return ctx

    @Slot(str, "QVariantList", result=str)
    def save_user_song_notes(self, song_id: str, notes) -> str:
        """
        Rebuilds a song's steps from the editor's flat note list.

        Returns "" on success, or a human-readable reason it was refused.
        """
        from logic.services.midi_ingestor import GRID

        base_id = self._base_song_id(song_id)

        if self._song_in_play(base_id):
            return "Stop practising this song before editing it."

        try:
            with open(self._user_song_path(base_id), "r") as f:
                record = migrate_record(json.load(f))
        except Exception as e:
            return f"Could not read the song file: {e}"

        orig_steps = record.get("steps", [])
        expected = sum(len(s.get("pitches", [])) for s in orig_steps)
        if not expected:
            return "That song has no notes to edit."

        buckets: dict = {}
        seen: set = set()
        hand_changed = False

        for row in (notes or []):
            try:
                si = int(row.get("step_index", -1))
                ni = int(row.get("note_index", -1))
            except (TypeError, ValueError, AttributeError):
                continue
            if not (0 <= si < len(orig_steps)):
                continue
            src = orig_steps[si]
            if not (0 <= ni < len(src.get("pitches", []))):
                continue
            if (si, ni) in seen:
                continue
            seen.add((si, ni))

            beat = self._snap_to_grid(row.get("beat"), GRID, 0.0)
            duration = self._snap_to_grid(row.get("duration"), GRID, GRID)
            hand = "left" if str(row.get("hand", "")).lower().startswith("l") else "right"

            # Carry every per-note attribute across, then overwrite the three
            # the editor owns. Everything the table does not show — spelling,
            # finger, velocity, articulations — rides along untouched.
            entry = {}
            for arr in self.STEP_NOTE_ARRAYS:
                values = src.get(arr) or []
                entry[arr] = values[ni] if ni < len(values) else self._STEP_ARRAY_DEFAULTS[arr]

            orig_beat = round(float(src.get("offset", 0.0)), 4)
            orig_dur = round(float(entry["durations"]), 4)
            orig_hand = entry["hands"]

            entry["durations"] = duration
            entry["hands"] = hand
            if hand != orig_hand:
                hand_changed = True

            if beat != orig_beat or duration != orig_dur:
                # Ties, beams and tuplets encode a relationship to neighbouring
                # notes that moving or resizing invalidates. The renderer treats
                # None as a plain note.
                entry["ties"] = None
                entry["beams"] = None
                entry["tuplets"] = None

            buckets.setdefault(beat, []).append(entry)

        # Editing is modify-only, so a count mismatch means the list is not the
        # one we handed out. Refuse rather than silently dropping notes.
        if len(seen) != expected:
            return (f"That edit doesn't match the song "
                    f"({expected} notes expected, {len(seen)} received). Nothing was saved.")

        # Rests hang off the step's offset rather than off any note, so they are
        # reattached by offset — including to offsets whose notes all moved away,
        # which keeps the silence where the arrangement put it.
        rests_by_offset: dict = {}
        for step in orig_steps:
            rests = step.get("rests") or []
            if rests:
                rests_by_offset.setdefault(round(float(step.get("offset", 0.0)), 4), []).extend(rests)

        new_steps = []
        for offset in sorted(set(buckets) | set(rests_by_offset)):
            entries = sorted(buckets.get(offset, []), key=lambda e: e["pitches"])
            step = {"offset": offset}
            for arr in self.STEP_NOTE_ARRAYS:
                step[arr] = [e[arr] for e in entries]
            step["duration"] = max(step["durations"]) if step["durations"] else GRID
            step["rests"] = rests_by_offset.get(offset, [])
            new_steps.append(step)

        end_beat = max(
            (s["offset"] + (max(s["durations"]) if s["durations"] else 0.0) for s in new_steps),
            default=0.0,
        )

        record["steps"] = new_steps
        # Keeps difficulty levels and hand modes working off the edited material.
        # Per-note durations flatten to max() here — the same trade-off levels
        # >= 1 already make; level 0 keeps the full-fidelity steps above.
        record["quantized_groups"] = groups_from_steps(new_steps)
        record["barlines"] = compute_barlines(record.get("time_signatures") or [], end_beat)
        if hand_changed:
            record["hand_mode"] = "manual"

        try:
            self._save_user_song_record(record)
        except Exception as e:
            return f"Could not save the song file: {e}"

        # Also covers _load_user_song_steps, which reads the same _level_cache.
        self._invalidate_level_cache(base_id)
        if hand_changed:
            self._update_user_song_entry(base_id, hand_mode="manual")
        self.userSongsChanged.emit()
        print(f"SongLibrary: Saved {expected} edited notes for '{record.get('title')}'")
        return ""

    def _base_song_id(self, song_id: str) -> str:
        """Strips the `::L<n>` difficulty suffix; ids themselves are never renamed."""
        return song_id.rsplit("::L", 1)[0] if "::L" in song_id else song_id

    def _update_user_song_entry(self, song_id: str, **fields):
        """Keeps the light in-memory catalog entry in sync with the JSON record."""
        base_id = self._base_song_id(song_id)
        for entry in self._user_songs:
            if entry.get("id") == base_id:
                entry.update(fields)
                return entry
        return None

    def _invalidate_level_cache(self, song_id: str):
        base_id = self._base_song_id(song_id)
        for k in [k for k in self._level_cache if k == base_id or k.startswith(base_id + "::L")]:
            self._level_cache.pop(k, None)

    def _sweep_orphan_sources(self):
        """
        Deletes archived source copies no remaining record references.

        Covers both the copy freed by the delete that triggered this sweep and
        orphans left behind before source copies were reference-counted.
        """
        sources_dir = self._user_songs_dir() / "sources"
        if not sources_dir.is_dir():
            return
        referenced = {s.get("source_hash") for s in self._user_songs if s.get("source_hash")}
        for src in sources_dir.iterdir():
            if not src.is_file():
                continue
            if src.stem not in referenced:
                try:
                    src.unlink()
                    print(f"SongLibrary: Removed orphaned source copy {src.name}")
                except Exception as e:
                    print(f"SongLibrary: Could not remove source copy {src.name}: {e}")

    @Slot(result="QVariantList")
    def get_user_songs(self):
        """Full library listing for LibraryView, with mastery joined in one query."""
        masteries = {}
        if self._db is not None and self._user_songs:
            try:
                masteries = self._db.get_song_masteries([s["id"] for s in self._user_songs])
            except Exception as e:
                print(f"SongLibrary: Mastery lookup failed: {e}")

        songs = []
        for entry in self._user_songs:
            stats = masteries.get(entry["id"], {})
            songs.append({
                "id": entry["id"],
                "title": entry.get("title", "Untitled"),
                "artist": entry.get("artist", ""),
                "level": entry.get("level", "Imported"),
                "key": entry.get("key", ""),
                "imported_at": entry.get("imported_at", ""),
                "source_type": entry.get("source_type", ""),
                "source_hash": entry.get("source_hash") or "",
                "hand_mode": entry.get("hand_mode", "auto"),
                "practice_mode": entry.get("practice_mode", "self_paced"),
                "mastery": float(stats.get("mastery", 0.0)),
                "play_count": int(stats.get("play_count", 0)),
                "last_played": stats.get("last_played") or "",
            })
        songs.sort(key=lambda s: str(s["title"]).lower())
        return songs

    @Slot(result="QVariantList")
    def get_user_song_summaries(self):
        """
        Compact library listing for the AI coach context and the dashboard strip.

        Each entry is {id, title, grade, mastery, last_played}. `grade` is the
        numeric part of the "Grade N" level string (0 when unknown) and mastery
        is 0 for songs the student has never played.

        Sorted so the interesting songs come first: in progress (mastery 1-79),
        then never played, then mastered — each group by descending mastery and
        then title, so the order is stable.
        """
        masteries = {}
        if self._db is not None and self._user_songs:
            try:
                masteries = self._db.get_song_masteries([s["id"] for s in self._user_songs])
            except Exception as e:
                print(f"SongLibrary: Mastery lookup failed: {e}")

        summaries = []
        for entry in self._user_songs:
            stats = masteries.get(entry["id"], {})
            mastery = float(stats.get("mastery", 0.0) or 0.0)
            summaries.append({
                "id": entry["id"],
                "title": entry.get("title", "Untitled"),
                "grade": self._grade_number(entry.get("level", "")),
                "mastery": mastery,
                "last_played": stats.get("last_played") or "",
            })

        def rank(s):
            m = s["mastery"]
            if m >= 80:
                group = 2          # mastered — least in need of attention
            elif m >= 1:
                group = 0          # in progress
            else:
                group = 1          # never played
            return (group, -m, str(s["title"]).lower())

        summaries.sort(key=rank)
        return summaries

    @staticmethod
    def _grade_number(level: str) -> int:
        """Pulls N out of a 'Grade N' level string; 0 when there isn't one."""
        match = re.search(r"Grade\s+(\d+)", str(level or ""))
        return int(match.group(1)) if match else 0

    @Slot(str, str, str)
    def rename_user_song(self, song_id: str, title: str, artist: str):
        """Retitles an imported song. The id (and therefore its levels) never changes."""
        title = (title or "").strip()
        artist = (artist or "").strip()
        if not title:
            print("SongLibrary: Refusing to rename a song to an empty title")
            return
        try:
            with open(self._user_song_path(song_id), "r") as f:
                record = json.load(f)
            record["title"] = title
            if artist:
                record["artist"] = artist
            self._save_user_song_record(record)

            # Cached level steps carry the old title with them
            self._invalidate_level_cache(song_id)
            self._update_user_song_entry(song_id, title=title, artist=record.get("artist", ""))
            self.userSongsChanged.emit()
            print(f"SongLibrary: Renamed {record.get('id')} to '{title}'")
        except Exception as e:
            print(f"SongLibrary: Rename failed for {song_id}: {e}")

    @Slot(str, result=str)
    def delete_user_song(self, song_id: str) -> str:
        """
        Deletes an imported song and its now-unreferenced source copy.

        Returns "" on success, or a human-readable reason it was refused.
        """
        base_id = self._base_song_id(song_id)
        entry = next((s for s in self._user_songs if s.get("id") == base_id), None)
        if entry is None:
            return "That song is no longer in your library."

        if self._song_in_play(base_id):
            return "Stop practising this song before deleting it."

        try:
            path = self._user_song_path(base_id)
            if path.exists():
                path.unlink()
        except Exception as e:
            print(f"SongLibrary: Failed to delete {base_id}: {e}")
            return f"Could not delete the song file: {e}"

        self._user_songs = [s for s in self._user_songs if s.get("id") != base_id]
        self._invalidate_level_cache(base_id)
        # Reference-counted: the sweep only removes copies nothing points at any more
        self._sweep_orphan_sources()
        self.userSongsChanged.emit()
        print(f"SongLibrary: Deleted user song {base_id} ('{entry.get('title')}')")
        return ""

    @Slot(result="QVariantList")
    def find_duplicates(self):
        """
        Groups library records that share a source file (same SHA-1).

        New imports are blocked by the check in import_file; this exists to clean
        up copies made before that landed.
        """
        by_hash = {}
        for entry in self._user_songs:
            src_hash = entry.get("source_hash")
            if not src_hash:
                continue
            by_hash.setdefault(src_hash, []).append({
                "id": entry["id"],
                "title": entry.get("title", "Untitled"),
                "artist": entry.get("artist", ""),
                "level": entry.get("level", "Imported"),
                "imported_at": entry.get("imported_at", ""),
            })

        groups = []
        for src_hash, songs in by_hash.items():
            if len(songs) < 2:
                continue
            songs.sort(key=lambda s: str(s.get("imported_at", "")))
            groups.append({"source_hash": src_hash, "count": len(songs), "songs": songs})
        groups.sort(key=lambda g: -g["count"])
        return groups
