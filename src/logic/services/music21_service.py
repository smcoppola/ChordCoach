import music21
from PySide6.QtCore import QObject, Signal, Slot # type: ignore
from music21 import corpus, note, chord, stream
from logic.utils.fingering_optimizer import inject_fingering_to_stream, distribute_chord_fingers

class Music21Service(QObject):
    """
    Handles accessing the music21 corpus and parsing scores into UI-friendly steps.
    """
    songRequested = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._catalog = {}
        self._recent_songs = [] # List of song IDs
        self._flat_catalog = [] # Cached flattened list for search
        self._load_catalog()
        self._load_recents()

    def _load_catalog(self):
        """Loads the hierarchical catalog from the local cache."""
        try:
            import json
            import os
            from pathlib import Path
            db_path = Path(__file__).parent.parent.parent.parent / "database" / "music21_catalog.json"
            if os.path.exists(db_path):
                with open(db_path, "r") as f:
                    self._catalog = json.load(f)
                print(f"Music21Service: Loaded hierarchical catalog with {len(self._catalog)} levels.")
            else:
                print("Music21Service: Catalog cache not found. Re-indexing...")
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
            return [{"id": k, "isCategory": True} for k in keys]
            
        return []

    def _load_recents(self):
        from pathlib import Path
        import json
        try:
            p = Path("database/recent_songs.json")
            if p.exists():
                with open(p, "r") as f:
                    self._recent_songs = json.load(f)
        except:
            self._recent_songs = []

    def _save_recents(self):
        from pathlib import Path
        import json
        try:
            p = Path("database/recent_songs.json")
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
        for song in self._flat_catalog:
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
            except:
                key_name = "Unknown Key"
            
            offset_map = {}
            all_parts = score.parts if score.parts else [score]
            
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
                
                flat_part = part.flatten()
                for el in flat_part.notes:
                    pitches = []
                    if isinstance(el, note.Note): pitches.append(el.pitch.midi)
                    elif isinstance(el, chord.Chord): pitches.extend([p.midi for p in el.pitches])
                    else: continue
                        
                    fingerings = []
                    if isinstance(el, music21.chord.Chord):
                        internal_notes = sorted(el.notes, key=lambda n: n.pitch.midi)
                        for n in internal_notes:
                            f_val = 1
                            for a in n.articulations:
                                if isinstance(a, music21.articulations.Fingering):
                                    f_val = a.fingerNumber; break
                            fingerings.append(f_val)
                    else:
                        fingerings = [a.fingerNumber for a in el.articulations if isinstance(a, music21.articulations.Fingering)]
                    
                    dur = float(el.duration.quarterLength)
                    off = float(el.offset)
                    if off not in offset_map:
                        offset_map[off] = {'pitches': [], 'hands': [], 'fingers': [], 'duration': dur}
                        
                    for i, pitch_val in enumerate(pitches):
                        found = False
                        for existing_pitch in offset_map[off]['pitches']:
                            if existing_pitch == pitch_val:
                                found = True; break
                        if not found:
                            f_val = fingerings[i] if i < len(fingerings) else (fingerings[0] if fingerings else 1)
                            offset_map[off]['pitches'].append(pitch_val)
                            offset_map[off]['hands'].append(hand_tag)
                            offset_map[off]['fingers'].append(f_val)
                part_index += 1
            
            # Process steps and re-balance (snip for brevity, but I'll keeping it robust)
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
                paired = sorted(list(zip(step_data['pitches'], step_data['hands'], step_data['fingers'])), key=lambda x: x[0])
                steps.append({
                    'offset': off,
                    'pitches': [p[0] for p in paired],
                    'hands': [p[1] for p in paired],
                    'fingers': [p[2] for p in paired],
                    'duration': step_data['duration']
                })
                
            print(f"Music21Service: Loaded {len(steps)} steps for '{title}' in {key_name}.")
            return {"steps": steps, "title": title, "composer": composer, "key": key_name}
            
        except Exception as e:
            print(f"Music21Service: Error loading {piece_name}: {e}")
            import traceback
            traceback.print_exc()
            return {"steps": [], "title": "Error", "key": "Direct Error"}
