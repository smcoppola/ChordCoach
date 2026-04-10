from music21 import corpus, note, chord

def extract_chords(score):
    p = score.flatten()
    offset_map = {}
    for el in p.notes:
        if isinstance(el, note.Note):
            pitches = [el.pitch.midi]
        elif isinstance(el, chord.Chord):
            pitches = [pit.midi for pit in el.pitches]
        else:
            continue
            
        dur = float(el.duration.quarterLength)
        off = float(el.offset)
        
        if off not in offset_map:
            offset_map[off] = {'pitches': set(), 'duration': dur}
        
        for p_val in pitches:
            offset_map[off]['pitches'].add(p_val)
            
    # Sort offsets
    sorted_offsets = sorted(offset_map.keys())
    result = []
    for off in sorted_offsets:
        result.append({
            'offset': off,
            'pitches': sorted(list(offset_map[off]['pitches'])),
            'duration': offset_map[off]['duration']
        })
    return result

score = corpus.parse('bach/bwv1.6.mxl')
chords = extract_chords(score)
for c in chords[:10]:
    print(c)
