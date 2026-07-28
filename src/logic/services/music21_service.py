import os
import sys
import copy
import hashlib
import json
import re
import time
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, Property, QThread  # type: ignore
import music21
from music21 import corpus, note, chord, stream
from logic.utils.fingering_optimizer import inject_fingering_to_stream, distribute_chord_fingers
from logic.utils.step_schema import CURRENT_SCHEMA_VERSION, migrate_record, compute_barlines, groups_from_steps
from core.bootstrap import get_user_data_dir


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


class Music21Service(QObject):
    """
    Handles accessing the music21 corpus and parsing scores into UI-friendly steps.
    """
    songRequested = Signal(str)
    corpusProgressChanged = Signal(float)
    corpusStatusChanged = Signal(str)
    corpusReady = Signal()
    corpusError = Signal()
    userSongsChanged = Signal()
    importSucceeded = Signal(str)       # song_id
    importFailed = Signal(str)          # error message
    importDuplicate = Signal(str, str)   # existing_song_id, existing_title

    USER_SONG_PREFIX = "user::"

    SIMPLIFY_LEVELS = {
        1: {"min_gap": 1.0,  "rh_notes": 2, "lh_notes": 1, "rh_span": 7,  "lh_span": 0},
        2: {"min_gap": 0.5,  "rh_notes": 3, "lh_notes": 1, "rh_span": 9,  "lh_span": 0},
        3: {"min_gap": 0.5,  "rh_notes": 4, "lh_notes": 2, "rh_span": 12, "lh_span": 7},
        4: {"min_gap": 0.25, "rh_notes": 5, "lh_notes": 3, "rh_span": 14, "lh_span": 12},
    }

    def __init__(self, project_root=None):
        super().__init__()
        self._project_root = project_root
        self._catalog = {}
        self._recent_songs = []
        self._flat_catalog = []

        self._corpus_progress = 0.0
        self._corpus_status = ""
        self._corpus_ready = False
        self._corpus_error = False
        self._download_worker = None

        self._user_songs = []
        self._import_worker = None
        self._simplify_worker = None
        self._level_cache = {}

        self._setup_local_corpus()
        self._load_catalog()
        self._load_recents()
        self._load_user_songs()

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
            return list(reversed(self._user_songs))

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
            if len(path) == 0 and self._user_songs:
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
        lookup.update({s['id']: s for s in self._user_songs})
        for sid in self._recent_songs:
            if sid in lookup:
                res.append(lookup[sid])
        return res[:5]

    @Slot(str, result="QVariantList")
    def search_catalog(self, query):
        if not query or len(query) < 2:
            return []
        q = query.lower()
        matches = []
        for song in self._user_songs + self._flat_catalog:
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
                    })
            except Exception as e:
                print(f"Music21Service: Error reading user song {json_path}: {e}")
        print(f"Music21Service: Loaded {len(self._user_songs)} imported user songs")

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
                    print(f"Music21Service: Duplicate import detected for hash {src_hash}")
                    self.importDuplicate.emit(s["id"], s["title"])
                    return
        except Exception as e:
            print(f"Music21Service: Hash calculation failed: {e}")

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
        print(f"Music21Service: File import failed: {error}")
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
        print(f"Music21Service: Async level generation failed: {error}")

    def load_song_as_steps(self, piece_name: str) -> dict:
        if piece_name in self._level_cache:
            return self._level_cache[piece_name]

        if piece_name.startswith(self.USER_SONG_PREFIX):
            return self._load_user_song_steps(piece_name)

        try:
            tune_index = None
            if "::" in piece_name:
                base_path, idx_str = piece_name.split("::")
                piece_name = base_path
                try:
                    tune_index = int(idx_str)
                except Exception:
                    tune_index = None

            print(f"Music21Service: Loading '{piece_name}'" + (f" (Tune {tune_index})" if tune_index else "") + "...")
            score = corpus.parse(piece_name)

            if isinstance(score, stream.Opus):
                if tune_index is not None:
                    try:
                        score = score.getScoreByNumber(tune_index)
                    except Exception:
                        score = score[0]
                else:
                    score = score[0]

            if not isinstance(score, (stream.Score, stream.Part, stream.Stream)):
                for el in score:
                    if isinstance(el, (stream.Score, stream.Part, stream.Stream)):
                        score = el
                        break

            title = "Unknown Piece"
            composer = "Unknown Composer"

            flat_lookup = {}
            def build_lookup(node):
                if isinstance(node, list):
                    for item in node:
                        if isinstance(item, dict):
                            if item.get("isCategory") and "children" in item:
                                build_lookup(item["children"])
                            else:
                                flat_lookup[item["id"]] = item
                elif isinstance(node, dict):
                    for v in node.values():
                        build_lookup(v)
            build_lookup(self._catalog)

            full_id = f"{piece_name}::{tune_index}" if tune_index else piece_name
            if full_id in flat_lookup:
                title = flat_lookup[full_id]['title']
                composer = flat_lookup[full_id].get('artist', "Unknown Composer")
            else:
                if hasattr(score, 'metadata') and score.metadata:
                    title = (score.metadata.title or
                             score.metadata.movementName or
                             score.metadata.workTitle or
                             "Unknown Piece")
                    composer = (score.metadata.composer or "Unknown Composer")

            if title == "Unknown Piece" or ".mxl" in title.lower() or ".xml" in title.lower():
                title = os.path.basename(piece_name).replace(".mxl", "").replace(".xml", "").replace(".abc", "").replace(".krn", "").replace("_", " ").title()

            try:
                analyzed_key = score.analyze('key')
                key_name = f"{analyzed_key.tonic.name} {analyzed_key.mode.capitalize()}"
                key_sharps = analyzed_key.sharps
            except Exception:
                key_name = "Unknown Key"
                key_sharps = 0

            steps, barlines, extra_meta = self._extract_steps_from_score(score)

            rec = {
                "steps": steps,
                "title": title,
                "composer": composer,
                "key": key_name,
                "key_sharps": key_sharps,
                "barlines": barlines,
                "time_signatures": extra_meta.get("time_signatures"),
                "tempo_map": extra_meta.get("tempo_map"),
                "dynamics": extra_meta.get("dynamics"),
            }
            rec = migrate_record(rec)
            print(f"Music21Service: Loaded {len(steps)} steps for '{title}' in {key_name}.")
            return rec
        except Exception as e:
            print(f"Music21Service: Error loading {piece_name}: {e}")
            import traceback
            traceback.print_exc()
            return {"steps": [], "title": "Error", "key": "Direct Error"}

    def _extract_steps_from_score(self, score):
        parts = getattr(score, 'parts', None)
        all_parts = list(parts) if parts else [score]

        time_signatures = []
        for part_obj in all_parts:
            try:
                for ts in part_obj.getTimeSignatures():
                    time_signatures.append({
                        "offset": float(ts.offset),
                        "numerator": int(ts.numerator),
                        "denominator": int(ts.denominator)
                    })
            except Exception:
                for ts in part_obj.flatten().getElementsByClass(music21.meter.TimeSignature):
                    time_signatures.append({
                        "offset": float(ts.offset),
                        "numerator": int(ts.numerator),
                        "denominator": int(ts.denominator)
                    })
        time_signatures.sort(key=lambda s: s["offset"])
        dedup_ts = {}
        for ts in time_signatures:
            dedup_ts[ts["offset"]] = ts
        time_signatures = [dedup_ts[k] for k in sorted(dedup_ts.keys())]
        if not time_signatures or time_signatures[0]["offset"] > 0:
            time_signatures.insert(0, {"offset": 0.0, "numerator": 4, "denominator": 4})

        tempo_map = []
        for mm in score.flatten().getElementsByClass(music21.tempo.MetronomeMark):
            try:
                bpm_val = float(mm.getQuarterBPM())
                tempo_map.append({"offset": float(mm.offset), "bpm": round(bpm_val, 2)})
            except Exception:
                pass
        tempo_map.sort(key=lambda tm: tm["offset"])
        dedup_tm = {}
        for tm in tempo_map:
            dedup_tm[tm["offset"]] = tm
        tempo_map = [dedup_tm[k] for k in sorted(dedup_tm.keys())]

        dynamics = []
        offset_map = {}

        for i, part_obj in enumerate(all_parts):
            flattened = part_obj.flatten()
            clefs = flattened.getElementsByClass(music21.clef.Clef)
            hand_tag = "left" if (clefs and isinstance(clefs[0], music21.clef.BassClef)) else ("left" if i > 0 else "right")

            for dyn in flattened.getElementsByClass(music21.dynamics.Dynamic):
                dynamics.append({
                    "offset": float(dyn.offset),
                    "mark": str(dyn.value),
                    "hand": hand_tag
                })

            has_native_fingering = any(
                isinstance(a, music21.articulations.Fingering)
                for el in flattened.notesAndRests
                for a in getattr(el, 'articulations', [])
            )
            if not has_native_fingering:
                inject_fingering_to_stream(part_obj, hand=hand_tag)

        for part_index, part_obj in enumerate(all_parts):
            flattened = part_obj.flatten()
            clefs = flattened.getElementsByClass(music21.clef.Clef)
            hand_tag = "left" if (clefs and isinstance(clefs[0], music21.clef.BassClef)) else ("left" if part_index > 0 else "right")

            for el in flattened.notesAndRests:
                dur = float(el.duration.quarterLength)
                off = float(el.offset)

                if off not in offset_map:
                    offset_map[off] = {
                        'pitches': [], 'spellings': [], 'hands': [], 'fingers': [],
                        'durations': [], 'duration': dur, 'ties': [], 'beams': [],
                        'tuplets': [], 'articulations': [], 'velocities': [], 'rests': []
                    }

                if isinstance(el, music21.note.Rest):
                    offset_map[off]['rests'].append({'duration': dur, 'hand': hand_tag})
                    continue

                pitches = []
                spellings = []
                if isinstance(el, note.Note):
                    pitches.append(el.pitch.midi)
                    spellings.append((el.pitch.step, el.pitch.alter))
                elif isinstance(el, chord.Chord):
                    pitches.extend([p.midi for p in el.pitches])
                    spellings.extend([(p.step, p.alter) for p in el.pitches])
                else:
                    continue

                beam_type = None
                if hasattr(el, 'beams') and el.beams and len(el.beams.beamsList) > 0:
                    b1 = el.beams.getByNumber(1)
                    if b1 is not None:
                        beam_type = b1.type

                tuplet_info = None
                if hasattr(el, 'duration') and el.duration and el.duration.tuplets:
                    t = el.duration.tuplets[0]
                    pos_raw = str(t.type).lower()
                    pos = "start" if "start" in pos_raw else ("stop" if ("stop" in pos_raw or "end" in pos_raw) else "continue")
                    tuplet_info = {
                        "actual": int(t.numberNotesActual),
                        "normal": int(t.numberNotesNormal),
                        "pos": pos
                    }

                art_names = []
                if hasattr(el, 'articulations') and el.articulations:
                    for a in el.articulations:
                        if isinstance(a, music21.articulations.Fingering):
                            continue
                        art_names.append(a.__class__.__name__.lower())

                vel_val = None
                if hasattr(el, 'volume') and el.volume and el.volume.velocity is not None:
                    vel_val = int(el.volume.velocity)

                fingerings = []
                ties = []
                if isinstance(el, music21.chord.Chord):
                    internal_notes = sorted(el.notes, key=lambda n: n.pitch.midi)
                    for n in internal_notes:
                        ties.append(n.tie.type if hasattr(n, 'tie') and n.tie else None)
                        f_val = 1
                        for a in n.articulations:
                            if isinstance(a, music21.articulations.Fingering):
                                f_val = a.fingerNumber
                                break
                        fingerings.append(f_val)
                else:
                    ties.append(el.tie.type if hasattr(el, 'tie') and el.tie else None)
                    fingerings = [a.fingerNumber for a in el.articulations if isinstance(a, music21.articulations.Fingering)]

                for i, pitch_val in enumerate(pitches):
                    found = False
                    for existing_pitch in offset_map[off]['pitches']:
                        if existing_pitch == pitch_val:
                            found = True
                            break
                    if not found:
                        f_val = fingerings[i] if i < len(fingerings) else (fingerings[0] if fingerings else 1)
                        t_val = ties[i] if i < len(ties) else None
                        s_val = spellings[i] if i < len(spellings) else None
                        offset_map[off]['pitches'].append(pitch_val)
                        offset_map[off]['spellings'].append(s_val)
                        offset_map[off]['hands'].append(hand_tag)
                        offset_map[off]['fingers'].append(f_val)
                        offset_map[off]['durations'].append(dur)
                        offset_map[off]['ties'].append(t_val)
                        offset_map[off]['beams'].append(beam_type)
                        offset_map[off]['tuplets'].append(tuplet_info)
                        offset_map[off]['articulations'].append(art_names)
                        offset_map[off]['velocities'].append(vel_val)

        for off in offset_map:
            step = offset_map[off]
            step['duration'] = max(step['durations']) if step['durations'] else step['duration']
            for h_tag in ["right", "left"]:
                h_indices = [i for i, h in enumerate(step['hands']) if h == h_tag]
                if len(h_indices) <= 1:
                    continue
                h_pitches = [step['pitches'][i] for i in h_indices]
                m21_pitches = [music21.pitch.Pitch(p) for p in h_pitches]
                anchor = 5 if h_tag == "right" else 1
                new_fingers = distribute_chord_fingers(m21_pitches, anchor, h_tag)
                pitch_to_finger = {p.midi: f for p, f in zip(sorted(m21_pitches, key=lambda x: x.midi), new_fingers)}
                for idx in h_indices:
                    p_midi = step['pitches'][idx]
                    step['fingers'][idx] = pitch_to_finger.get(p_midi, 1)

        sorted_offsets = sorted(offset_map.keys())
        steps = []
        for off in sorted_offsets:
            step_data = offset_map[off]
            paired = sorted(list(zip(
                step_data['pitches'],
                step_data['spellings'],
                step_data['hands'],
                step_data['fingers'],
                step_data['durations'],
                step_data['ties'],
                step_data['beams'],
                step_data['tuplets'],
                step_data['articulations'],
                step_data['velocities']
            )), key=lambda x: x[0])

            steps.append({
                'offset': off,
                'pitches': [p[0] for p in paired],
                'spellings': [p[1] for p in paired],
                'hands': [p[2] for p in paired],
                'fingers': [p[3] for p in paired],
                'durations': [p[4] for p in paired],
                'duration': max([p[4] for p in paired]) if paired else step_data['duration'],
                'ties': [p[5] for p in paired],
                'beams': [p[6] for p in paired],
                'tuplets': [p[7] for p in paired],
                'articulations': [p[8] for p in paired],
                'velocities': [p[9] for p in paired],
                'rests': step_data['rests']
            })

        barlines_set = set()
        for part_obj in all_parts:
            for m in part_obj.getElementsByClass(music21.stream.Measure):
                if float(m.offset) > 0:
                    barlines_set.add(float(m.offset))
        barlines = sorted(list(barlines_set))
        if not barlines:
            max_off = round(sorted_offsets[-1] + offset_map[sorted_offsets[-1]]['duration'], 4) if sorted_offsets else 0.0
            barlines = compute_barlines(time_signatures, max_off)

        extra_meta = {
            "time_signatures": time_signatures,
            "tempo_map": tempo_map,
            "dynamics": dynamics,
        }
        return steps, barlines, extra_meta

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
            print(f"Music21Service: Failed to archive source copy: {e}")

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
        }
        print(f"Music21Service: Imported '{record['title']}' as {song_id} ({len(record['steps'])} steps)")
        return song_id, entry

    def _build_score_from_groups(self, groups, key_name=None, key_sharps=None, time_signatures=None):
        from music21 import pitch as m21pitch, clef as m21clef, meter, key as m21key, duration as m21duration

        if key_name is None or key_sharps is None:
            probe = stream.Stream()
            for g in groups:
                g_dur = float(g.get("duration", 0.25))
                for p, _h in g["notes"]:
                    probe.append(note.Note(pitch=m21pitch.Pitch(midi=p), quarterLength=g_dur))
            try:
                analyzed = probe.analyze('key')
                key_name = f"{analyzed.tonic.name} {analyzed.mode.capitalize()}"
                key_sharps = int(analyzed.sharps)
            except Exception:
                key_name, key_sharps = "C Major", 0

        score = stream.Score()
        p_rh = stream.Part()
        p_lh = stream.Part()
        p_rh.insert(0, m21clef.TrebleClef())
        p_lh.insert(0, m21clef.BassClef())

        if time_signatures:
            for ts in time_signatures:
                ts_obj = meter.TimeSignature(f"{ts['numerator']}/{ts['denominator']}")
                p_rh.insert(float(ts.get("offset", 0.0)), ts_obj)
                p_lh.insert(float(ts.get("offset", 0.0)), meter.TimeSignature(f"{ts['numerator']}/{ts['denominator']}"))
        else:
            p_rh.insert(0, meter.TimeSignature('4/4'))
            p_lh.insert(0, meter.TimeSignature('4/4'))

        try:
            ks = m21key.KeySignature(key_sharps)
            p_rh.insert(0, ks)
            p_lh.insert(0, ks)
        except Exception:
            pass

        for hand_tag, part_obj in [("right", p_rh), ("left", p_lh)]:
            m_curr = stream.Measure(number=1)
            m_curr.offset = 0.0
            last_off = 0.0

            for g in groups:
                off = float(g["offset"])
                dur = float(g["duration"])
                pitches = [p for p, h in g["notes"] if h == hand_tag]

                if pitches:
                    if off > last_off:
                        r_dur = off - last_off
                        m_curr.append(note.Rest(quarterLength=r_dur))
                    if len(pitches) == 1:
                        el = note.Note(pitch=m21pitch.Pitch(midi=pitches[0]), quarterLength=dur)
                    else:
                        m21_pitches = [m21pitch.Pitch(midi=p) for p in pitches]
                        el = chord.Chord(m21_pitches, quarterLength=dur)
                    m_curr.append(el)
                    last_off = off + dur

            part_obj.append(m_curr)

        score.append(p_rh)
        score.append(p_lh)

        try:
            score = score.makeNotation()
        except Exception as e:
            print(f"Music21Service: makeNotation warning: {e}")

        return score, key_name, key_sharps

    def _score_difficulty(self, steps: list) -> int:
        if not steps:
            return 1
        onset_diffs = []
        for i in range(1, len(steps)):
            d = steps[i]['offset'] - steps[i - 1]['offset']
            if d > 0:
                onset_diffs.append(d)
        avg_gap = (sum(onset_diffs) / len(onset_diffs)) if onset_diffs else 1.0
        events_per_beat = (1.0 / avg_gap) if avg_gap > 0 else 1.0

        chord_sizes = [len(s['pitches']) for s in steps]
        avg_chord_size = (sum(chord_sizes) / len(chord_sizes)) if chord_sizes else 1.0

        polyphonic_count = sum(1 for s in steps if len(set(s['hands'])) > 1 or len(s['pitches']) > 2)
        poly = polyphonic_count / len(steps)

        both_hands_count = sum(1 for s in steps if "right" in s['hands'] and "left" in s['hands'])
        both_hands = both_hands_count / len(steps)

        spans = []
        for s in steps:
            for h_tag in ("right", "left"):
                hp = [p for p, h in zip(s['pitches'], s['hands']) if h == h_tag]
                if len(hp) >= 2:
                    spans.append(max(hp) - min(hp))
        wide = (sum(1 for sp in spans if sp > 12) / len(spans)) if spans else 0.0

        raw = (1.0 + min(events_per_beat, 3.0) * 1.2 + (avg_chord_size - 1.0) * 0.5
               + poly * 1.5 + both_hands * 1.5 + wide * 1.5)
        return max(1, min(10, round(raw)))

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
            print(f"Music21Service: Simplified '{title}' to Level {level}: {len(steps)} steps")

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
        if mode not in ("auto", "split", "right", "left"):
            print(f"Music21Service: Unknown hand mode '{mode}' ignored")
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

            print(f"Music21Service: Hand mode for '{record.get('title')}' set to '{mode}'")
        except Exception as e:
            print(f"Music21Service: Failed to set hand mode: {e}")
