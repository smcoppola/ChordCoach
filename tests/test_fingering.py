import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import music21
from src.logic.utils.fingering_optimizer import inject_fingering_to_stream

def test_winter_ade_fingering():
    print("Testing fingering for 'Winter ade' (erk20.abc)...")
    try:
        # 1. Parse from corpus
        s = music21.corpus.parse('essenFolksong/erk20.abc')
        if isinstance(s, music21.stream.Opus):
            s = s.getScoreByNumber(1)
            
        print(f"Piece: {s.metadata.title}")
        
        # 2. Inject fingerings (Right Hand)
        inject_fingering_to_stream(s, hand="right")
        
        # 3. Verify all notes
        notes = s.flatten().notes
        print(f"\nAll {len(notes)} notes:")
        print(f"{'Note':<10} {'Pitch':<10} {'Finger':<10}")
        print("-" * 30)
        
        for n in notes:
            f_num = "None"
            for a in n.articulations:
                if isinstance(a, music21.articulations.Fingering):
                    f_num = a.fingerNumber
                    break
            
            p_name = n.pitch.nameWithOctave if hasattr(n, 'pitch') else "Chord"
            p_midi = n.pitch.midi if hasattr(n, 'pitch') else "N/A"
            print(f"{p_name:<10} {p_midi:<10} {f_num:<10}")
            
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    test_winter_ade_fingering()
