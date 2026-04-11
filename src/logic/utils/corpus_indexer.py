import music21
from music21 import corpus, stream, note, chord, metadata
import json
import os
from pathlib import Path
import time

def calculate_complexity(score_path):
    """
    Heuristically estimates complexity of a piece from music21 corpus.
    Uses a partial parse to keep performance high.
    """
    try:
        # We only parse the first part and flatten it to get a representative sample
        # Using m21's partial loading if possible, or just a stream.Opus check
        s = corpus.parse(score_path)
        
        # If it's a collection, take the first one
        if isinstance(s, stream.Opus):
            s = s.getScoreByNumber(1)
        
        # Flatten and keep only notes for a quick count
        # Limit to the first 40 measures or 100 notes
        p = s.parts[0] if s.parts else s
        sample = p.flatten().notes.stream()
        
        note_count = len(sample)
        if note_count == 0: return 0
        
        duration = sample.highestTime or 1
        note_density = note_count / duration # 
        
        durations = set()
        pitches = []
        for n in sample:
            durations.add(n.duration.quarterLength)
            if isinstance(n, note.Note):
                pitches.append(n.pitch.midi)
            elif isinstance(n, chord.Chord):
                pitches.extend([p.midi for p in n.pitches])
        
        rhythmic_variety = len(durations)
        pitch_range = (max(pitches) - min(pitches)) if pitches else 0
        
        # Normalization (rough)
        # 0.0 - 10.0 scale
        nd_score = min(note_density * 2.0, 5.0) # 0-5
        rv_score = min(rhythmic_variety * 0.5, 3.0) # 0-3
        pr_score = min(pitch_range / 12.0, 2.0) # 0-2
        
        return nd_score + rv_score + pr_score # Max 10.0
        
    except Exception as e:
        # print(f"Error analyzing {score_path}: {e}")
        return 5.0 # Neutral fallback

def index_corpus():
    print("Catalog Indexer: Starting crawl of music21 corpus...")
    start_time = time.time()
    
    # Define our New Taxonomy (Grades 1-10)
    # Mapping folders to specific levels and categories
    grade_map = {
        1: ["airdsAirs", "nottingham-dataset"],
        2: ["essenFolksong", "theoryExercises"],
        3: ["schumann_robert", "oneills1850"],
        4: ["bach", "corelli", "ryansMammoth"],
        5: ["haydn", "handel", "czerny"],
        6: ["mozart", "schubert", "weber"],
        7: ["beethoven", "joplin"],
        8: ["chopin", "monteverdi"],
        9: ["palestrina", "webern"],
        10: ["schoenberg", "verdi"]
    }
    
    genre_map = {
        "Folk & Trad": ["airdsAirs", "essenFolksong", "oneills1850", "ryansMammoth", "nottingham-dataset"],
        "Chorales & Hymns": ["bach", "palestrina", "monteverdi", "corelli", "handel"],
        "Études & Studies": ["czerny", "theoryExercises"],
        "Sonatas & Sonatinas": ["beethoven", "mozart", "haydn", "weber"],
        "Character Pieces": ["schumann_robert", "schubert", "chopin"],
        "Ragtime & Jazz": ["joplin", "leadSheet"],
        "Modern & Other": ["schoenberg", "webern", "verdi"]
    }

    catalog = { f"Grade {i}": {} for i in range(1, 11) }

    paths = list(corpus.corpora.CoreCorpus().getPaths())
    processed = 0
    
    # Expand target collections
    target_collections = [
        "bach", "mozart", "beethoven", "haydn", "essenFolksong", 
        "airdsAirs", "czerny", "joplin", "schumann_robert", "schubert", 
        "chopin", "corelli", "handel", "oneills1850"
    ]
    
    for score_path in paths:
        path_str = str(score_path).replace("\\", "/")
        
        # Determine collection
        collection = "unknown"
        for coll in target_collections:
            if f"corpus/{coll}/" in path_str:
                collection = coll
                break
        
        if collection == "unknown":
            continue
            
        processed += 1
        if processed % 100 == 0:
            print(f"Catalog Indexer: Processed {processed} targets...")

        # Find Grade (1-10)
        grade_num = 5 # Default
        for g, colls in grade_map.items():
            if collection in colls:
                grade_num = g
                break
        
        # Fine-tune grade based on filename patterns
        filename = os.path.basename(path_str).lower()
        if "chorale" in filename or "bwv" in filename:
            grade_num = max(4, min(grade_num, 6)) # Bach Chorales are Level 4-6
        if "sonatina" in filename:
            grade_num = max(3, min(grade_num, 5))
        if "sonata" in filename:
            grade_num = max(7, grade_num)
        if "kind" in filename or "album" in filename: # Album for Young
            grade_num = 3
            
        difficulty_label = f"Grade {grade_num}"
        
        # Find Genre
        genre = "Classical"
        for g, colls in genre_map.items():
            if collection in colls:
                genre = g
                break
        
        # Composer
        composer = collection.capitalize()
        if collection == "essenFolksong": composer = "German Folk"
        if collection == "airdsAirs": composer = "Scottish Airs"
        if collection == "schumann_robert": composer = "Schumann"
        
        # Refined titles
        title = os.path.basename(path_str).replace(".mxl", "").replace(".xml", "").replace(".abc", "").replace(".krn", "")
        title = title.replace("_", " ").title()
        
        # Clean up BWV numbering or Op numbers in title
        import re
        title = re.sub(r'Bwv(\d+)\.(\d+)', r'BWV \1 No. \2', title)
        title = re.sub(r'Op(\d+)\.(\d+)', r'Op. \1 No. \2', title)
        
        # FIX: Preserve subfolder structure in the ID. 
        # Previously we used os.path.basename, which broke pieces in subdirectories like corelli/opus3no1/1grave.xml
        # We find the part of the path after the collection folder.
        id_str = f"{collection}/{os.path.basename(path_str)}" # Fallback
        
        # Pattern looks for 'corpus/collection_name/path_to_file'
        # Note: path_str has been standardized to use '/'
        match = re.search(f"corpus/{collection}/(.*)", path_str)
        if match:
            id_str = f"{collection}/{match.group(1)}"
        
        # Construct the hierarchy: Grade X > Genre > Composer > Piece
        if genre not in catalog[difficulty_label]:
            catalog[difficulty_label][genre] = {}
        
        if composer not in catalog[difficulty_label][genre]:
            catalog[difficulty_label][genre][composer] = []
            
        catalog[difficulty_label][genre][composer].append({
            "id": id_str,
            "title": title,
            "level": difficulty_label,
            "artist": composer,
            "genre": genre
        })

    # Save to database
    db_path = Path(__file__).parent.parent.parent.parent / "database" / "music21_catalog.json"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(db_path, "w") as f:
        json.dump(catalog, f, indent=4)
        
    print(f"Catalog Indexer: Finished! Indexed {processed} scores in {time.time() - start_time:.1f}s")
    return catalog

if __name__ == "__main__":
    index_corpus()
