import music21
from music21 import corpus, stream, note, chord, metadata
import json
import os
from pathlib import Path
import time
import re

def parse_metadata_only(score_path):
    """
    Tries to get metadata without a full heavy parse.
    """
    try:
        # Use str() to ensure music21 compatibility
        s = corpus.parse(str(score_path))
        
        # Title and Composer
        title = "Unknown Piece"
        composer = "Unknown Composer"
        
        if s.metadata:
            # Use getattr for robustness against different music21 versions/metadata schemas
            title = getattr(s.metadata, 'title', None) or \
                    getattr(s.metadata, 'movementName', None) or \
                    getattr(s.metadata, 'workTitle', None) or "Unknown"
            composer = getattr(s.metadata, 'composer', None) or "Unknown"
            
        return s, title, composer
    except Exception as e:
        # Silent failure for files that are too big or malformed during quick index
        # print(f"  [ERROR] parse_metadata_only failed: {e}")
        return None, "Unknown", "Unknown"

def index_corpus():
    print("Catalog Indexer: Starting deep crawl of music21 corpus...")
    start_time = time.time()
    
    # Define our New Taxonomy (Grades 1-10)
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
    
    target_collections = [
        "bach", "mozart", "beethoven", "haydn", "essenFolksong", 
        "airdsAirs", "czerny", "joplin", "schumann_robert", "schubert", 
        "chopin", "corelli", "handel", "oneills1850"
    ]
    
    for score_path in paths:
        path_str = str(score_path).replace("\\", "/")
        
        collection = "unknown"
        for coll in target_collections:
            if f"corpus/{coll}/" in path_str:
                collection = coll
                break
        
        if collection == "unknown":
            continue
            
        processed += 1
        if processed % 100 == 0:
            print(f"Catalog Indexer: Processed {processed} files...")

        # Determine Grade and Genre
        grade_num = 5 
        for g, colls in grade_map.items():
            if collection in colls:
                grade_num = g
                break
        
        filename = os.path.basename(path_str).lower()
        if "chorale" in filename or "bwv" in filename:
            grade_num = max(4, min(grade_num, 6))
        if "sonatina" in filename:
            grade_num = max(3, min(grade_num, 5))
        if "sonata" in filename:
            grade_num = max(7, grade_num)
        
        difficulty_label = f"Grade {grade_num}"
        genre = "Classical"
        for g, colls in genre_map.items():
            if collection in colls:
                genre = g
                break
        
        composer_default = collection.capitalize()
        if collection == "essenFolksong": composer_default = "German Folk"
        if collection == "airdsAirs": composer_default = "Scottish Airs"
        if collection == "schumann_robert": composer_default = "Schumann"

        # Match collection path relative to corpus/collection_name/
        match = re.search(f"corpus/{collection}/(.*)", path_str)
        rel_path = match.group(1) if match else os.path.basename(path_str)
        file_id = f"{collection}/{rel_path}"

        # Initialize hierarchy if needed
        if genre not in catalog[difficulty_label]:
            catalog[difficulty_label][genre] = {}
        if composer_default not in catalog[difficulty_label][genre]:
            catalog[difficulty_label][genre][composer_default] = []

        # Use filename cleanup for the fallback or base name
        clean_name = os.path.basename(path_str).replace(".mxl", "").replace(".xml", "").replace(".abc", "").replace(".krn", "").replace("_", " ").title()
        clean_name = re.sub(r'Bwv(\d+)\.(\d+)', r'BWV \1 No. \2', clean_name)
        clean_name = re.sub(r'Op(\d+)\.(\d+)', r'Op. \1 No. \2', clean_name)

        # Parse Metadata for the file
        score, meta_title, meta_composer = parse_metadata_only(score_path)

        if score is not None and isinstance(score, stream.Opus):
            # It's a collection! Create a sub-dictionary for the book
            print(f"  > Collection expanded: {clean_name} ({len(score)} tunes)")
            
            book_item = {
                "id": file_id,
                "title": clean_name,
                "isCategory": True,
                "children": []
            }
            
            # Extract tunes within the Opus
            for i, tune in enumerate(score):
                if not isinstance(tune, (stream.Score, stream.Stream)):
                    continue
                    
                tune_title = "Unknown Tune"
                if tune.metadata:
                    tune_title = getattr(tune.metadata, 'title', None) or \
                                 getattr(tune.metadata, 'movementName', None) or \
                                 f"Tune {i+1}"
                else:
                    tune_title = f"Tune {i+1}"
                
                # Cleanup if title is just the filename or number
                if "tune" in tune_title.lower() and len(tune_title) < 8:
                    tune_title = f"Selection No. {i+1}"
                
                book_item["children"].append({
                    "id": f"{file_id}::{i+1}",
                    "title": tune_title.strip(),
                    "level": difficulty_label,
                    "artist": composer_default,
                    "genre": genre
                })
            
            catalog[difficulty_label][genre][composer_default].append(book_item)
            
        else:
            # Single piece
            final_title = meta_title if (meta_title and meta_title != "Unknown") else clean_name
            final_composer = meta_composer if (meta_composer and meta_composer != "Unknown") else composer_default
            
            catalog[difficulty_label][genre][composer_default].append({
                "id": file_id,
                "title": final_title.strip(),
                "level": difficulty_label,
                "artist": final_composer.strip(),
                "genre": genre
            })

    # Save to database
    db_path = Path(__file__).parent.parent.parent.parent / "database" / "music21_catalog.json"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(db_path, "w") as f:
        json.dump(catalog, f, indent=4)
        
    print(f"Catalog Indexer: Finished! Indexed {processed} files in {time.time() - start_time:.1f}s")
    return catalog

if __name__ == "__main__":
    index_corpus()
