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
        except Exception as e:
            print(f"Music21Service: Error loading catalog: {e}")
            self._catalog = {}

    @Slot(list, result="QVariantList")
    def get_catalog_level(self, path):
        """
        Returns the contents of the catalog at the specified path (list of keys).
        If the path leads to a leaf (song list), it returns the songs.
        """
        node = self._catalog
        for segment in path:
            if segment in node:
                node = node[segment]
            else:
                return []
        
        # If node is a list, it's the final level (Songs)
        if isinstance(node, list):
            return node
            
        # If node is a dict, return its keys (Categories)
        if isinstance(node, dict):
            # Sort keys for consistent UI
            if len(path) == 0:
                # Top level: Grade Sort (Natural sort for Grade 1..10)
                import re
                def natural_sort_key(s):
                    return [int(text) if text.isdigit() else text.lower()
                            for text in re.split('([0-9]+)', s)]
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
        # Flattened lookup for speed
        flat_all = []
        def flatten(node):
            if isinstance(node, list):
                flat_all.extend(node)
            elif isinstance(node, dict):
                for v in node.values():
                    flatten(v)
        flatten(self._catalog)
        
        lookup = {s['id']: s for s in flat_all}
        for sid in self._recent_songs:
            if sid in lookup:
                res.append(lookup[sid])
        return res[:5]

    @Slot(str)
    def mark_song_played(self, song_id):
        if song_id in self._recent_songs:
            self._recent_songs.remove(song_id)
        self._recent_songs.insert(0, song_id)
        self._recent_songs = self._recent_songs[:10] # Keep last 10
        self._save_recents()

    @Slot(result="QVariantList")
    def get_catalog(self):
        """Legacy compatibility for flat structure if needed, or starting level."""
        return self.get_catalog_level([])
        
    def load_song_as_steps(self, piece_name: str) -> dict:
        """
        Parses a piece from the music21 corpus and returns a dictionary with
        rhythmic steps and metadata (title, key).
        """
        try:
            print(f"Music21Service: Loading '{piece_name}'...")
            score = corpus.parse(piece_name)
            
            # Handle Opus collection (some folksongs are collections)
            if isinstance(score, stream.Opus):
                # getScoreByNumber(1) is the standard music21 way to get the first piece
                try:
                    score = score.getScoreByNumber(1)
                except:
                    # Fallback to direct indexing if that fails
                    score = score[0]
            
            # Ensure we are working with a Stream/Score, not Metadata or other elements
            if not isinstance(score, (stream.Score, stream.Part, stream.Stream)):
                # If we got metadata or similar, look for the first actual stream element
                for el in score:
                    if isinstance(el, (stream.Score, stream.Part, stream.Stream)):
                        score = el
                        break
            
            # Extract Metadata
            title = "Unknown Piece"
            
            # Step 1: Try deep metadata search
            if score.metadata:
                title = (score.metadata.title or 
                         score.metadata.movementName or 
                         score.metadata.workTitle or 
                         "Unknown Piece")
            elif hasattr(score, 'title') and score.title:
                title = score.title
                
            # Step 2: Fallback to our verified catalog title if still unknown
            if title == "Unknown Piece":
                # Flattened lookup for speed
                flat_all = []
                def flatten(node):
                    if isinstance(node, list):
                        flat_all.extend(node)
                    elif isinstance(node, dict):
                        for v in node.values():
                            flatten(v)
                flatten(self._catalog)
                
                lookup = {s['id']: s for s in flat_all}
                if piece_name in lookup:
                    title = lookup[piece_name]['title']
                else:
                    # Final fallback: Clean filename
                    title = os.path.basename(piece_name).replace(".mxl", "").replace(".xml", "").replace(".abc", "").replace(".krn", "").replace("_", " ").title()
            
            # Analyze Key
            try:
                analyzed_key = score.analyze('key')
                key_name = f"{analyzed_key.tonic.name} {analyzed_key.mode.capitalize()}"
            except:
                key_name = "Unknown Key"
            
            offset_map = {}
            
            # Extract notes from each part. Use score itself if no parts exist.
            all_parts = score.parts
            if not all_parts:
                all_parts = [score]
            
            # RUN VITERBI FINGERING OPTIMIZATION
            for i, part in enumerate(all_parts):
                # Robust hand detection: check for clefs first
                flattened = part.flatten()
                clefs = flattened.getElementsByClass(music21.clef.Clef)
                
                hand = "right"
                if clefs:
                    if isinstance(clefs[0], music21.clef.BassClef):
                        hand = "left"
                    else:
                        hand = "right"
                else:
                    # Fallback to index-based for lead sheets
                    hand = "right" if i == 0 else "left"
                
                inject_fingering_to_stream(part, hand=hand)
            
            # Extract notes from each part and try to infer hand based on part index
            part_index = 0
            for part in all_parts:
                # Use the same logic for tagging steps
                flattened = part.flatten()
                clefs = flattened.getElementsByClass(music21.clef.Clef)
                if clefs:
                    hand_tag = "left" if isinstance(clefs[0], music21.clef.BassClef) else "right"
                else:
                    hand_tag = "left" if part_index > 0 else "right"
                
                # Flatten this specific part to get absolute offsets
                flat_part = part.flatten()
                
                for el in flat_part.notes:
                    pitches = []
                    if isinstance(el, note.Note):
                        pitches.append(el.pitch.midi)
                    elif isinstance(el, chord.Chord):
                        pitches.extend([p.midi for p in el.pitches])
                    else:
                        continue
                        
                    # Extract fingerings (Deep extraction for chords)
                    fingerings = []
                    if isinstance(el, music21.chord.Chord):
                        # Sort internal notes to match pitch order
                        internal_notes = sorted(el.notes, key=lambda n: n.pitch.midi)
                        for n in internal_notes:
                            f_val = 1
                            for a in n.articulations:
                                if isinstance(a, music21.articulations.Fingering):
                                    f_val = a.fingerNumber
                                    break
                            fingerings.append(f_val)
                    else:
                        fingerings = [a.fingerNumber for a in el.articulations if isinstance(a, music21.articulations.Fingering)]
                    
                    dur = float(el.duration.quarterLength)
                    off = float(el.offset)
                    
                    if off not in offset_map:
                        offset_map[off] = {'pitches': [], 'hands': [], 'fingers': [], 'duration': dur}
                        
                    # Add pitches with their corresponding hand tag and unique fingers
                    # deduplicate across hands (Unisons)
                    for i, pitch_val in enumerate(pitches):
                        found = False
                        for existing_pitch in offset_map[off]['pitches']:
                            if existing_pitch == pitch_val:
                                # We already have this pitch at this offset
                                # Piano notation usually shows unisons as a single note
                                found = True
                                break
                        
                        if not found:
                            # Match fingering to pitch (our optimizer sorts both Low to High)
                            f_val = fingerings[i] if i < len(fingerings) else (fingerings[0] if fingerings else 1)
                            offset_map[off]['pitches'].append(pitch_val)
                            offset_map[off]['hands'].append(hand_tag)
                            offset_map[off]['fingers'].append(f_val)
                
                part_index += 1
            
            # --- ANATOMICAL REBALANCING ---
            # Automatically split impossible spans (> 13 semitones) between hands
            for off in offset_map:
                step = offset_map[off]
                rh_indices = [i for i, h in enumerate(step['hands']) if h == "right"]
                lh_indices = [i for i, h in enumerate(step['hands']) if h == "left"]
                
                # Check Right Hand for impossible stretches (like the Beethoven G3-G4-G5)
                if len(rh_indices) > 1:
                    rh_pitches = sorted([step['pitches'][i] for i in rh_indices])
                    if (rh_pitches[-1] - rh_pitches[0]) > 13:
                        # Find the bottom outlier and move it to the Left Hand
                        bottom_pitch = rh_pitches[0]
                        orig_idx = step['pitches'].index(bottom_pitch)
                        step['hands'][orig_idx] = "left"
                        # Re-finger the moved note for the new hand (preferring thumb/1 for LH top)
                        step['fingers'][orig_idx] = 1
                
                # Check Left Hand
                if len(lh_indices) > 1:
                    lh_pitches = sorted([step['pitches'][i] for i in lh_indices])
                    if (lh_pitches[-1] - lh_pitches[0]) > 13:
                        # Find the top outlier and move it to the Right Hand
                        top_pitch = lh_pitches[-1]
                        orig_idx = step['pitches'].index(top_pitch)
                        step['hands'][orig_idx] = "right"
                
                # --- FINAL UNIQUENESS PASS ---
                # Re-run the chord distributor ONLY if it's a chord (len > 1)
                # This prevents monophonic melodies from being forced into a single finger (the "all-red" bug)
                for h_tag in ["right", "left"]:
                    h_indices = [i for i, h in enumerate(step['hands']) if h == h_tag]
                    if len(h_indices) <= 1:
                        continue
                        
                    h_pitches = [step['pitches'][i] for i in h_indices]
                    # Map Midi pitches to music21.pitch.Pitch objects for the optimizer
                    m21_pitches = [music21.pitch.Pitch(p) for p in h_pitches]
                    
                    # For chords, ensure they use unique fingers by anchoring at 1 or 5
                    # Orchestral chords will still follow the 1-5 logic implemented in the optimizer
                    anchor = 5 if h_tag == "right" else 1
                    new_fingers = distribute_chord_fingers(m21_pitches, anchor, h_tag)
                    
                    # Store back in the correct indices (distribute_chord_fingers returns in pitch order)
                    pitch_to_finger = {p.midi: f for p, f in zip(sorted(m21_pitches, key=lambda x: x.midi), new_fingers)}
                    for idx in h_indices:
                        p_midi = step['pitches'][idx]
                        step['fingers'][idx] = pitch_to_finger.get(p_midi, 1)
                
            # Process map into sorted list of steps
            sorted_offsets = sorted(offset_map.keys())
            steps = []
            for off in sorted_offsets:
                step_data = offset_map[off]
                
                # Standardize format for UI
                paired = list(zip(step_data['pitches'], step_data['hands'], step_data['fingers']))
                paired.sort(key=lambda x: x[0])
                
                sorted_pitches = [p[0] for p in paired]
                sorted_hands = [p[1] for p in paired]
                sorted_fingers = [p[2] for p in paired]
                
                steps.append({
                    'offset': off,
                    'pitches': sorted_pitches,
                    'hands': sorted_hands,
                    'fingers': sorted_fingers,
                    'duration': step_data['duration']
                })
                
            print(f"Music21Service: Loaded {len(steps)} steps for '{title}' in {key_name}.")
            return {
                "steps": steps,
                "title": title,
                "key": key_name
            }
            
        except Exception as e:
            print(f"Music21Service: Error loading {piece_name}: {e}")
            return {"steps": [], "title": "Error", "key": "N/A"}
