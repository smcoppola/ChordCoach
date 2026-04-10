from music21 import corpus, stream

def analyze_piece(piece_id):
    try:
        score = corpus.parse(piece_id)
        if isinstance(score, stream.Opus):
            score = score[0]
            if not isinstance(score, stream.Score):
                score = [s for s in score if isinstance(s, stream.Stream)][0]
        
        all_pitches = [p.midi for p in score.flatten().pitches]
        if not all_pitches:
            return "No pitches found"
            
        k = score.analyze('key')
        return {
            "min": min(all_pitches),
            "max": max(all_pitches),
            "tonic": k.tonic.midi,
            "key": str(k)
        }
    except Exception as e:
        return f"Error: {e}"

catalog = [
    "bach/bwv1.6.mxl",
    "bach/bwv10.7.mxl",
    "essenFolksong/erk5.abc",
    "essenFolksong/erk20.abc"
]

for piece in catalog:
    print(f"{piece}: {analyze_piece(piece)}")
