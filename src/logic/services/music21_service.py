from PySide6.QtCore import QObject, Signal, Slot, Property, QThread # type: ignore
import music21
from music21 import corpus, note, chord, stream
from logic.utils.fingering_optimizer import inject_fingering_to_stream, distribute_chord_fingers
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
            # First attempt
            self.status.emit("Connecting to PyPI...")
            if CorpusManager.download_and_extract(progress_callback=self.progress.emit):
                self.finished.emit(True)
                return
        except Exception as e:
            print(f"CorpusDownloadWorker: First attempt failed: {e}")
            if not self.auto_retry_done:
                self.auto_retry_done = True
                self.status.emit("Connection lost. Retrying once...")
                import time
                time.sleep(2)
                try:
                    if CorpusManager.download_and_extract(progress_callback=self.progress.emit):
                        self.finished.emit(True)
                        return
                except Exception as e2:
                    print(f"CorpusDownloadWorker: Retry failed: {e2}")
        
        self.finished.emit(False)

class MidiImportWorker(QThread):
    """Background worker running the MIDI import pipeline off the UI thread."""
    succeeded = Signal(str, dict)  # song_id, catalog entry
    failed = Signal(str)           # error message

    def __init__(self, service, path: str):
        super().__init__()
        self._service = service
        self._path = path

    def run(self):
        try:
            song_id, entry = self._service._do_import(self._path)
            self.succeeded.emit(song_id, entry)
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
    importSucceeded = Signal(str)  # song_id
    importFailed = Signal(str)     # error message
    
    def __init__(self, project_root=None):
        super().__init__()
        self._project_root = project_root
        self._catalog = {}
        self._recent_songs = [] # List of song IDs
        self._flat_catalog = [] # Cached flattened list for search
        
        # Corpus state
        self._corpus_progress = 0.0
        self._corpus_status = ""
        self._corpus_ready = False
        self._corpus_error = False
        self._download_worker = None
        
        self._user_songs = [] # User-imported MIDI songs (catalog entries)
        self._import_worker = None

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
        """Starts the corpus download if not already in progress."""
        if self._download_worker and self._download_worker.isRunning():
            return
            
        self._corpus_error = False
        self.corpusError.emit()
        
        self._download_worker = CorpusDownloadWorker()
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.status.connect(self._on_download_status)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_progress(self, p):
        self._corpus_progress = p
        self.corpusProgressChanged.emit(p)

    def _on_download_status(self, s):
        self._corpus_status = s
        self.corpusStatusChanged.emit(s)

    def _on_download_finished(self, success):
        if success:
            from logic.utils.corpus_manager import CorpusManager
            CorpusManager.configure_environment()
            self._corpus_ready = True
            self._corpus_status = "Corpus Ready"
            self.corpusReady.emit()
            # If the catalog was waiting for the corpus, we might want to re-load it or index it
            if not self._catalog:
                self._load_catalog()
        else:
            self._corpus_error = True
            self._corpus_status = "Download Failed"
            self.corpusError.emit()

    def _setup_local_corpus(self):
        """Checks if the corpus is present and configures the environment."""
        from logic.utils.corpus_manager import CorpusManager
        if CorpusManager.is_corpus_present():
            CorpusManager.configure_environment()
            self._corpus_ready = True
            self._corpus_status = "Corpus Ready"
        else:
            self._corpus_ready = False
            self._corpus_status = "Corpus Missing"
            
    def _load_catalog(self):
        """Loads the hierarchical catalog from the local cache."""
        try:
            import json
            import os
            from pathlib import Path
            if self._project_root:
                db_path = Path(self._project_root) / "database" / "music21_catalog.json"
            else:
                # Fallback for dev/standalone testing if root not provided
                db_path = Path(__file__).parent.parent.parent.parent / "database" / "music21_catalog.json"
                
            if os.path.exists(db_path):
                with open(db_path, "r") as f:
                    self._catalog = json.load(f)
                print(f"Music21Service: Loaded hierarchical catalog with {len(self._catalog)} levels from {db_path}")
            else:
                print(f"Music21Service: Catalog cache not found at {db_path}. Re-indexing...")
                from logic.utils.corpus_indexer import index_corpus
                self._catalog = index_corpus()
            
            # Populate search cache
            self._flat_catalog = self._flatten_catalog(self._catalog)
        except Exception as e:
            print(f"Music21Service: Error loading catalog: {e}")
            self._catalog = {}

    def _flatten_catalog(self, node):
        """Recursively flattens the hierarchical catalog into a list of songs."""
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
        """
        Returns the contents of the catalog at the specified path (list of keys/items).
        Supports navigating through dict keys and searching within lists for 'isCategory' objects.
        """
        # User-imported songs live in a virtual "My Songs" category
        if path and path[0] == "My Songs":
            return list(reversed(self._user_songs))

        node = self._catalog
        for segment in path:
            if isinstance(node, dict) and segment in node:
                node = node[segment]
            elif isinstance(node, list):
                # Look for an item with this ID (a collection/book)
                found = False
                for item in node:
                    if isinstance(item, dict) and item.get("id") == segment:
                        node = item.get("children", [])
                        found = True
                        break
                if not found: return []
            else:
                return []
        
        # If node is a list, it's a final song list or a tune list
        if isinstance(node, list):
            return node
            
        # If node is a dict, return its keys (Categories)
        if isinstance(node, dict):
            import re
            def natural_sort_key(s):
                return [int(text) if text.isdigit() else text.lower()
                        for text in re.split('([0-9]+)', s)]
            
            if len(path) == 0:
                # Top level: Grade Sort
                keys = sorted(node.keys(), key=natural_sort_key)
            else:
                # Sub levels: Alphabetical Sort
                keys = sorted(node.keys())
            entries = [{"id": k, "isCategory": True} for k in keys]
            if len(path) == 0 and self._user_songs:
                entries.insert(0, {"id": "My Songs", "isCategory": True})
            return entries
            
        return []

    def _load_recents(self):
        import json
        try:
            p = get_user_data_dir() / "database" / "recent_songs.json"
            if p.exists():
                with open(p, "r") as f:
                    self._recent_songs = json.load(f)
        except:
            self._recent_songs = []

    def _save_recents(self):
        import json
        try:
            p = get_user_data_dir() / "database" / "recent_songs.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w") as f:
                json.dump(self._recent_songs, f)
        except:
            pass

    @Slot(result="QVariantList")
    def get_recent_songs(self):
        """Returns the full metadata for the 5 most recent songs."""
        res = []
        lookup = {s['id']: s for s in self._flat_catalog}
        lookup.update({s['id']: s for s in self._user_songs})
        for sid in self._recent_songs:
            if sid in lookup:
                res.append(lookup[sid])
        return res[:5]

    @Slot(str, result="QVariantList")
    def search_catalog(self, query):
        """Performs a case-insensitive search across titles and artists."""
        if not query or len(query) < 2:
            return []
            
        q = query.lower()
        matches = []
        for song in self._user_songs + self._flat_catalog:
            title = song.get("title", "").lower()
            artist = song.get("artist", "").lower()
            if q in title or q in artist:
                matches.append(song)
            if len(matches) >= 50: # Cap for performance
                break
        return matches

    @Slot(str)
    def mark_song_played(self, song_id):
        if song_id in self._recent_songs:
            self._recent_songs.remove(song_id)
        self._recent_songs.insert(0, song_id)
        self._recent_songs = self._recent_songs[:10] # Keep last 10
        self._save_recents()

    @Slot(result="QVariantList")
    def get_catalog(self):
        return self.get_catalog_level([])
        
    def load_song_as_steps(self, piece_name: str) -> dict:
        """
        Parses a piece from the music21 corpus and returns a dictionary with
        rhythmic steps and metadata (title, key).
        Supports "filename::index" for tune selection.
        """
        if piece_name.startswith(self.USER_SONG_PREFIX):
            return self._load_user_song_steps(piece_name)

        try:
            import os
            # Handle Tune Selection (path::index)
            tune_index = None
            if "::" in piece_name:
                base_path, idx_str = piece_name.split("::")
                piece_name = base_path
                try:
                    tune_index = int(idx_str)
                except:
                    tune_index = None

            print(f"Music21Service: Loading '{piece_name}'" + (f" (Tune {tune_index})" if tune_index else "") + "...")
            score = corpus.parse(piece_name)
            
            # Extract specific tune if it's an Opus
            if isinstance(score, stream.Opus):
                if tune_index is not None:
                    try:
                        score = score.getScoreByNumber(tune_index)
                    except:
                        score = score[0]
                else:
                    score = score[0]
            
            # Ensure we are working with a Stream/Score
            if not isinstance(score, (stream.Score, stream.Part, stream.Stream)):
                for el in score:
                    if isinstance(el, (stream.Score, stream.Part, stream.Stream)):
                        score = el
                        break
            
            # Extract Metadata
            title = "Unknown Piece"
            composer = "Unknown Composer"
            
            # SYNC: Lookup catalog title first for consistency
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
                # Fallback to metadata extraction
                if score.metadata:
                    title = (score.metadata.title or 
                             score.metadata.movementName or 
                             score.metadata.workTitle or 
                             "Unknown Piece")
                    composer = (score.metadata.composer or "Unknown Composer")
            
            # Final cleanup
            if title == "Unknown Piece" or ".mxl" in title.lower() or ".xml" in title.lower():
                title = os.path.basename(piece_name).replace(".mxl", "").replace(".xml", "").replace(".abc", "").replace(".krn", "").replace("_", " ").title()
            
            # Analyze Key
            try:
                analyzed_key = score.analyze('key')
                key_name = f"{analyzed_key.tonic.name} {analyzed_key.mode.capitalize()}"
                key_sharps = analyzed_key.sharps
            except:
                key_name = "Unknown Key"
                key_sharps = 0
                
            steps, barlines = self._extract_steps_from_score(score)

            print(f"Music21Service: Loaded {len(steps)} steps for '{title}' in {key_name}.")
            return {
                "steps": steps,
                "title": title,
                "composer": composer,
                "key": key_name,
                "key_sharps": key_sharps,
                "barlines": barlines
            }
            
        except Exception as e:
            print(f"Music21Service: Error loading {piece_name}: {e}")
            import traceback
            traceback.print_exc()
            return {"steps": [], "title": "Error", "key": "Direct Error"}

    def _extract_steps_from_score(self, score):
        """
        Flattens a music21 score into offset-keyed steps plus barline offsets.
        Injects fingerings. Shared by corpus loading and MIDI import.
        Returns (steps, barlines).
        """
        parts = getattr(score, 'parts', None)
        all_parts = parts if parts else [score]

        barlines = set()
        for part in all_parts:
            for m in part.getElementsByClass(music21.stream.Measure):
                if float(m.offset) > 0:
                    barlines.add(float(m.offset))

        offset_map = {}

        # Inject fingerings
        for i, part in enumerate(all_parts):
            flattened = part.flatten()
            clefs = flattened.getElementsByClass(music21.clef.Clef)
            hand = "left" if (clefs and isinstance(clefs[0], music21.clef.BassClef)) else ("right" if i == 0 else "left")
            inject_fingering_to_stream(part, hand=hand)

        # Extract steps
        part_index = 0
        for part in all_parts:
            flattened = part.flatten()
            clefs = flattened.getElementsByClass(music21.clef.Clef)
            hand_tag = "left" if (clefs and isinstance(clefs[0], music21.clef.BassClef)) else ("left" if part_index > 0 else "right")

            for el in flattened.notesAndRests:
                dur = float(el.duration.quarterLength)
                off = float(el.offset)

                if off not in offset_map:
                    offset_map[off] = {'pitches': [], 'spellings': [], 'hands': [], 'fingers': [], 'duration': dur, 'ties': [], 'beams': [], 'rests': []}

                if isinstance(el, music21.note.Rest):
                    offset_map[off]['rests'].append({'duration': dur, 'hand': hand_tag})
                    continue

                pitches = []
                spellings = []  # (step_letter, alter) tuples e.g. ('F', -1) for F-flat
                if isinstance(el, note.Note):
                    pitches.append(el.pitch.midi)
                    spellings.append((el.pitch.step, el.pitch.alter))
                elif isinstance(el, chord.Chord):
                    pitches.extend([p.midi for p in el.pitches])
                    spellings.extend([(p.step, p.alter) for p in el.pitches])
                else: continue

                beam_type = None
                if hasattr(el, 'beams') and el.beams and len(el.beams.beamsList) > 0:
                    b1 = el.beams.getByNumber(1)
                    if b1 is not None:
                        beam_type = b1.type

                fingerings = []
                ties = []
                if isinstance(el, music21.chord.Chord):
                    internal_notes = sorted(el.notes, key=lambda n: n.pitch.midi)
                    for n in internal_notes:
                        ties.append(n.tie.type if hasattr(n, 'tie') and n.tie else None)
                        f_val = 1
                        for a in n.articulations:
                            if isinstance(a, music21.articulations.Fingering):
                                f_val = a.fingerNumber; break
                        fingerings.append(f_val)
                else:
                    ties.append(el.tie.type if hasattr(el, 'tie') and el.tie else None)
                    fingerings = [a.fingerNumber for a in el.articulations if isinstance(a, music21.articulations.Fingering)]

                for i, pitch_val in enumerate(pitches):
                    found = False
                    for existing_pitch in offset_map[off]['pitches']:
                        if existing_pitch == pitch_val:
                            found = True; break
                    if not found:
                        f_val = fingerings[i] if i < len(fingerings) else (fingerings[0] if fingerings else 1)
                        t_val = ties[i] if i < len(ties) else None
                        s_val = spellings[i] if i < len(spellings) else None
                        offset_map[off]['pitches'].append(pitch_val)
                        offset_map[off]['spellings'].append(s_val)
                        offset_map[off]['hands'].append(hand_tag)
                        offset_map[off]['fingers'].append(f_val)
                        offset_map[off]['ties'].append(t_val)
                        offset_map[off]['beams'].append(beam_type)
            part_index += 1

        # Re-balance chord fingerings per hand
        for off in offset_map:
            step = offset_map[off]
            for h_tag in ["right", "left"]:
                h_indices = [i for i, h in enumerate(step['hands']) if h == h_tag]
                if len(h_indices) <= 1: continue
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
                step_data['ties'],
                step_data['beams']
            )), key=lambda x: x[0])

            steps.append({
                'offset': off,
                'pitches': [p[0] for p in paired],
                'spellings': [p[1] for p in paired],
                'hands': [p[2] for p in paired],
                'fingers': [p[3] for p in paired],
                'ties': [p[4] for p in paired],
                'beams': [p[5] for p in paired],
                'duration': step_data['duration'],
                'rests': step_data['rests']
            })

        return steps, sorted(barlines)

    # ── User-Imported Songs (MIDI Import) ─────────────────────────────

    USER_SONG_PREFIX = "user::"

    # Difficulty adjustment levels for imported songs. Both hands are always
    # kept; levels differ in chord size, reachable stretch, and how densely
    # notes may follow each other (difficult runs get thinned to fewer notes).
    # Level 4 is closest to the original; Level 1 is the simplest.
    SIMPLIFY_LEVELS = {
        1: {"min_gap": 1.0,  "rh_notes": 2, "lh_notes": 1, "rh_span": 7,  "lh_span": 0},
        2: {"min_gap": 0.5,  "rh_notes": 3, "lh_notes": 1, "rh_span": 9,  "lh_span": 0},
        3: {"min_gap": 0.5,  "rh_notes": 4, "lh_notes": 2, "rh_span": 12, "lh_span": 7},
        4: {"min_gap": 0.25, "rh_notes": 5, "lh_notes": 3, "rh_span": 14, "lh_span": 12},
    }

    def _simplify_groups(self, groups, level: int):
        """
        Produces an easier arrangement of quantized note groups for the given
        skill level (1-4). Three transforms:
        1. Timing: enforce a minimum gap between onsets — off-grid groups are
           either shifted into an empty coarse slot or dropped (fewer notes
           in difficult sequences).
        2. Chords: cap simultaneous notes per hand (RH keeps the melody from
           the top down, LH keeps the bass from the bottom up).
        3. Stretches: drop notes beyond the level's reachable span from the
           melody (RH) or bass (LH) anchor.
        """
        cfg = self.SIMPLIFY_LEVELS[level]
        min_gap = cfg["min_gap"]

        def aligned(off):
            return abs(off / min_gap - round(off / min_gap)) < 1e-6

        # 1. Timing thinning
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

        # 2 + 3. Chord reduction and stretch clamping per hand
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
                out.append({"offset": g["offset"], "duration": g["duration"],
                            "notes": sorted(notes)})

        # Smooth durations: let notes ring to the next onset in the same hand
        # so thinned passages read as legato instead of staccato fragments.
        for i, g in enumerate(out):
            hands = {h for _, h in g["notes"]}
            for nxt in out[i + 1:]:
                if hands & {h for _, h in nxt["notes"]}:
                    gap = nxt["offset"] - g["offset"]
                    if gap > 0:
                        g["duration"] = max(0.25, min(max(g["duration"], gap), 4.0))
                    break

        return out

    def _user_songs_dir(self):
        p = get_user_data_dir() / "database" / "user_songs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _load_user_songs(self):
        """Scans the user_songs directory and builds catalog entries."""
        import json
        self._user_songs = []
        try:
            for f in sorted(self._user_songs_dir().glob("*.json")):
                try:
                    with open(f, "r") as fh:
                        data = json.load(fh)
                    self._user_songs.append({
                        "id": data["id"],
                        "title": data.get("title", f.stem),
                        "artist": data.get("artist", "Imported MIDI"),
                        "level": data.get("level", ""),
                    })
                except Exception as e:
                    print(f"Music21Service: Skipping unreadable user song {f.name}: {e}")
        except Exception as e:
            print(f"Music21Service: Error scanning user songs: {e}")
        if self._user_songs:
            print(f"Music21Service: Loaded {len(self._user_songs)} imported songs")

    @Slot(str)
    def import_midi_file(self, file_url: str):
        """
        Starts a background import of a MIDI file. Emits
        importSucceeded(song_id) or importFailed(error) when done.
        """
        if self._import_worker is not None and self._import_worker.isRunning():
            self.importFailed.emit("Another import is still running")
            return

        path = file_url
        if path.startswith("file:"):
            from PySide6.QtCore import QUrl
            path = QUrl(file_url).toLocalFile()

        self._import_worker = MidiImportWorker(self, path)
        self._import_worker.succeeded.connect(self._on_import_succeeded)
        self._import_worker.failed.connect(self._on_import_failed)
        self._import_worker.start()

    def _on_import_succeeded(self, song_id: str, entry: dict):
        """Main-thread registration of a freshly imported song."""
        self._user_songs.append(entry)
        self.userSongsChanged.emit()
        self.importSucceeded.emit(song_id)

    def _on_import_failed(self, error: str):
        print(f"Music21Service: MIDI import failed: {error}")
        self.importFailed.emit(error)

    def _do_import(self, path: str):
        """
        Blocking import pipeline (runs on the worker thread): cleans up
        live-performance timing, builds notation steps, scores difficulty,
        and saves the song record. Returns (song_id, catalog_entry);
        raises on failure.
        """
        import json, re, time
        from logic.services.midi_ingestor import parse_and_quantize

        quantized = parse_and_quantize(path)
        score, key_name, key_sharps = self._build_score_from_groups(quantized["groups"])
        steps, barlines = self._extract_steps_from_score(score)
        if not steps:
            raise ValueError("No notation steps could be generated from this file")

        difficulty = self._score_difficulty(steps)
        level = f"Grade {difficulty}"

        slug = re.sub(r'[^a-z0-9]+', '-', quantized["title"].lower()).strip('-') or "song"
        song_id = f"{self.USER_SONG_PREFIX}{slug}-{int(time.time())}"

        record = {
            "id": song_id,
            "title": quantized["title"],
            "artist": "Imported MIDI",
            "level": level,
            "key": key_name,
            "key_sharps": key_sharps,
            "bpm": quantized["bpm"],
            "barlines": barlines,
            "steps": steps,
            # Raw quantized groups kept for difficulty re-arrangement
            "quantized_groups": quantized["groups"],
            "source_file": path,
            "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        out_path = self._user_songs_dir() / f"{song_id.replace(self.USER_SONG_PREFIX, '')}.json"
        with open(out_path, "w") as f:
            json.dump(record, f)

        entry = {"id": song_id, "title": record["title"], "artist": record["artist"], "level": level}
        print(f"Music21Service: Imported '{record['title']}' as {song_id} ({len(steps)} steps, {level}, {key_name})")
        return song_id, entry

    def _build_score_from_groups(self, groups, key_name=None, key_sharps=None):
        """
        Converts quantized note groups into a two-part music21 Score with
        measures/ties, plus detected key info for correct note spelling.
        Pass key_name/key_sharps to skip detection (e.g. when re-arranging an
        already-analyzed song). Returns (score, key_name, key_sharps).
        """
        from music21 import pitch as m21pitch, clef as m21clef, meter, key as m21key, duration as m21duration

        if key_name is None or key_sharps is None:
            # Key detection on raw pitch classes (Krumhansl — no corpus needed)
            probe = stream.Stream()
            for g in groups:
                for p, _h in g["notes"]:
                    probe.append(note.Note(pitch=m21pitch.Pitch(midi=p), quarterLength=0.25))
            try:
                analyzed = probe.analyze('key')
                key_name = f"{analyzed.tonic.name} {analyzed.mode.capitalize()}"  # type: ignore
                key_sharps = int(analyzed.sharps)  # type: ignore
            except Exception:
                key_name, key_sharps = "C Major", 0

        def spelled(midi_val):
            p = m21pitch.Pitch(midi=midi_val)  # defaults to sharp spelling
            if key_sharps < 0 and p.accidental is not None and p.accidental.alter > 0:
                p = p.getEnharmonic()  # C# -> D-flat etc. for flat keys
            return p

        parts = {}
        for hand in ("right", "left"):
            part = stream.Part()
            part.insert(0, m21clef.TrebleClef() if hand == "right" else m21clef.BassClef())
            part.insert(0, meter.TimeSignature('4/4'))  # type: ignore
            if key_sharps:
                part.insert(0, m21key.KeySignature(key_sharps))
            parts[hand] = part

        used_hands = set()
        for g in groups:
            by_hand = {}
            for p, h in g["notes"]:
                by_hand.setdefault(h, []).append(p)
            for hand, pitches in by_hand.items():
                if len(pitches) == 1:
                    el = note.Note(pitch=spelled(pitches[0]))
                else:
                    el = chord.Chord([spelled(p) for p in sorted(pitches)])  # type: ignore
                el.duration = m21duration.Duration(g["duration"])
                parts[hand].insert(g["offset"], el)
                used_hands.add(hand)

        score = stream.Score()
        for hand in ("right", "left"):
            if hand in used_hands:
                part = parts[hand]
                try:
                    part.makeNotation(inPlace=True)  # measures + ties for barline rendering
                except Exception:
                    try:
                        part.makeMeasures(inPlace=True)
                    except Exception:
                        pass
                score.insert(0, part)
        return score, key_name, key_sharps

    def _score_difficulty(self, steps) -> int:
        """Heuristic 1-10 difficulty from density, polyphony, and hand use."""
        if not steps:
            return 1
        total_beats = max(float(s['offset']) + float(s['duration']) for s in steps)
        total_beats = max(total_beats, 1.0)
        notes_total = sum(len(s['pitches']) for s in steps)
        events_per_beat = len(steps) / total_beats  # how fast new attacks come
        avg_chord_size = notes_total / len(steps)   # simultaneous-note load
        poly = sum(1 for s in steps if len(s['pitches']) >= 3) / len(steps)
        both_hands = sum(1 for s in steps if len(set(s['hands'])) > 1) / len(steps)
        spans = []
        for s in steps:
            for h in ("right", "left"):
                hp = [p for p, hh in zip(s['pitches'], s['hands']) if hh == h]
                if len(hp) >= 2:
                    spans.append(max(hp) - min(hp))
        wide = (sum(1 for sp in spans if sp > 12) / len(spans)) if spans else 0.0

        raw = (1.0 + min(events_per_beat, 3.0) * 1.2 + (avg_chord_size - 1.0) * 0.5
               + poly * 1.5 + both_hands * 1.5 + wide * 1.5)
        return max(1, min(10, round(raw)))

    def _load_user_song_steps(self, song_id: str) -> dict:
        """
        Loads a previously imported song's cached steps from disk.
        A "::L<n>" suffix (n = 1-4) requests a difficulty-adjusted
        arrangement regenerated from the stored quantized groups;
        no suffix plays the original unadjusted import.
        """
        import json

        level = 0
        base_id = song_id
        if "::L" in song_id:
            base_id, lv_str = song_id.rsplit("::L", 1)
            try:
                level = int(lv_str)
            except ValueError:
                level = 0
        if level not in self.SIMPLIFY_LEVELS:
            level = 0

        fname = base_id.replace(self.USER_SONG_PREFIX, "") + ".json"
        path = self._user_songs_dir() / fname
        try:
            with open(path, "r") as f:
                data = json.load(f)

            title = data.get("title", "Imported Song")
            result = {
                "steps": data.get("steps", []),
                "title": title,
                "composer": data.get("artist", "Imported MIDI"),
                "key": data.get("key", "Unknown Key"),
                "key_sharps": data.get("key_sharps", 0),
                "barlines": data.get("barlines", []),
            }

            if level and data.get("quantized_groups"):
                # JSON round-trip turns note tuples into lists — restore tuples
                groups = [
                    {"offset": g["offset"], "duration": g["duration"],
                     "notes": [(int(p), h) for p, h in g["notes"]]}
                    for g in data["quantized_groups"]
                ]
                simplified = self._simplify_groups(groups, level)
                score, _kn, _ks = self._build_score_from_groups(
                    simplified,
                    key_name=data.get("key"),
                    key_sharps=data.get("key_sharps"))
                steps, barlines = self._extract_steps_from_score(score)
                result.update({
                    "steps": steps,
                    "barlines": barlines,
                    "title": f"{title} (Level {level})",
                })
                print(f"Music21Service: Simplified '{title}' to Level {level}: "
                      f"{len(data.get('steps', []))} -> {len(steps)} steps")
            elif level:
                print(f"Music21Service: '{title}' has no quantized groups; playing original")

            print(f"Music21Service: Loaded imported song '{result['title']}' ({len(result['steps'])} steps)")
            return result
        except Exception as e:
            print(f"Music21Service: Error loading imported song {song_id}: {e}")
            return {"steps": [], "title": "Error", "key": "Import Error"}
