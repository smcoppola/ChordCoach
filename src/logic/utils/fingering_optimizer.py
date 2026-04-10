"""
PIANO FINGERING OPTIMIZATION ENGINE (PARNCUTT 1997 MODEL)

This module implements a computational model for piano fingering based on 
ergonomic difficulty ratings. It uses a Dynamic Programming (Viterbi) algorithm 
 to find the fingering sequence that minimizes the total physical strain 
based on biomechanical constraints like hand span, finger crossings, 
and key surface (black vs. white keys).

Methodology:
- Algorithm: Viterbi Trellis (Forward-accumulate, Backward-reconstruct)
- Complexity: O(N * 5^2)
- Biomechanical Model: Parncutt, Sloboda, Clarke, Raekallio, & Desain (1997)
"""

import numpy as np
import music21
from typing import List, Dict, Any, Tuple

# =============================================================================
# ERGONOMIC COST PARAMETERS (Parncutt 1997 / Jacobs 2001 Refinements)
# =============================================================================

# Standard comfortable spans (in semitones) for each finger pair in the Right Hand.
# The model penalizes transitions that fall outside these 'ideal' zones.
# Based on Parncutt (1997) "MaxComf" values for a typical adult hand.
RH_SPAN_LIMITS = {
    (1, 2): (1, 5),
    (1, 3): (3, 7),
    (1, 4): (5, 9),
    (1, 5): (7, 12),
    (2, 3): (1, 2),
    (2, 4): (2, 4),
    (2, 5): (3, 5),
    (3, 4): (1, 2),
    (3, 5): (2, 4),
    (4, 5): (1, 2)
}

# Penalty weights for various ergonomic violations
COST_STRETCH = 4.0        # High penalty per semitone beyond max comfort (quadratic)
COST_COMPRESSION = 4.0    # High penalty per semitone below min comfort (quadratic)
COST_CROSSING = 8.0       # High penalty for unnatural finger crossings
COST_BLACK_THUMB = 3.0    # Penalty for thumb (1) on a black key
COST_BLACK_PINKY = 1.5    # Penalty for pinky (5) on a black key
COST_REPETITION = 50.0    # High penalty for same finger on different pitch
COST_WEAK_FINGER = 0.1    # Slight penalty for using fingers 4 or 5
COST_ILLEGAL_CROSS = 100.0 # Prohibitive penalty for crossing fingers over each other (not thumb)
COST_CHANGE_ON_SAME_PITCH = 20.0 # Heavily discourage finger switching on repeated notes

def calculate_transition_cost(p1: int, f1: int, p2: int, f2: int, is_black2: bool, hand: str = "right") -> float:
    """
    Calculates the ergonomic cost of moving from one (pitch, finger) state 
    to the next state (pitch, finger).

    Args:
        p1: MIDI pitch of the first note.
        f1: Finger used for the first note (1-5).
        p2: MIDI pitch of the second note.
        f2: Finger used for the second note (1-5).
        is_black2: True if the target note is a black key.
        hand: Either "right" or "left".

    Returns:
        float: Total ergonomic penalty for this transition.
    """
    # 1. Base Cost: Same finger on different pitch is very inefficient
    if f1 == f2:
        return 0.0 if p1 == p2 else COST_REPETITION
    
    # New: Small penalty for changing fingers on the same pitch
    if p1 == p2 and f1 != f2:
        return COST_CHANGE_ON_SAME_PITCH

    interval = p2 - p1 # Semi-tone interval
    if hand == "left":
        interval = -interval

    total_cost = 0.0

    # 2. Crossing Rules (Thumb-under / Finger-over)
    # Rule: Crossing must involve the thumb (1). 
    # Finger-over-finger (e.g., 3 over 2) is nearly always illegal in standard repertoire.
    is_crossing = (f2 < f1 and interval > 0) or (f2 > f1 and interval < 0)
    
    if is_crossing:
        # Crossings are only permitted if one of the fingers is the thumb (1)
        if f1 == 1 or f2 == 1:
            total_cost += COST_CROSSING
            # Crossing finger 5 over thumb is extremely rare/awkward
            if f1 == 5 or f2 == 5:
                total_cost += COST_ILLEGAL_CROSS
        else:
            # Illegal finger-over-finger crossing
            total_cost += COST_ILLEGAL_CROSS

    # 3. Span/Stretch Analysis
    # Get the expected comfort range for this finger pair
    # We sort fingers to check the span limit
    lower_f, higher_f = min(f1, f2), max(f1, f2)
    pair = (lower_f, higher_f)
    
    if pair in RH_SPAN_LIMITS:
        min_span, max_span = RH_SPAN_LIMITS[pair]
        
        # Absolute physical distance required on the keyboard
        dist = abs(interval)
        
        # Quadratic penalties for falling outside the comfort range
        if dist > max_span:
            total_cost += ((dist - max_span) ** 2) * COST_STRETCH
        elif dist < min_span:
            total_cost += ((min_span - dist) ** 2) * COST_COMPRESSION
    else:
        # Unexpected finger pair
        total_cost += 10.0

    # 4. Black Key Constraints
    if is_black2:
        if f2 == 1: total_cost += COST_BLACK_THUMB
        if f2 == 5: total_cost += COST_BLACK_PINKY

    # 5. Weak Finger Preference
    if f2 in [4, 5]:
        total_cost += COST_WEAK_FINGER

    return total_cost

def optimize_fingering(notes: List[Dict[str, Any]], hand: str = "right") -> List[int]:
    """
    Executes the Viterbi Dynamic Programming search to find the optimal 
    fingering sequence for a monophonic passage.

    Args:
        notes: A list of dicts containing 'pitch' (MIDI) and 'is_black' (bool).
        hand: "right" or "left".

    Returns:
        List[int]: A sequence of finger numbers (1-5) matching the input notes.
    """
    n_notes = len(notes)
    if n_notes == 0: return []
    
    # Trellis structure: [Step, Finger-1]
    # min_cost[i][f] stores the minimum cumulative cost to reach note i using finger f+1.
    min_cost = np.full((n_notes, 5), np.inf)
    # backpointer stores which previous finger led to this minimum cost.
    backpointer = np.zeros((n_notes, 5), dtype=int)

    # INITIALIZATION: For the first note, all fingers start with cost 0 (or weak-finger penalty)
    for f in range(5):
        min_cost[0][f] = COST_WEAK_FINGER if (f+1) in [4, 5] else 0.0
        # Additional black key penalty for start note
        if notes[0]['is_black']:
            if f+1 == 1: min_cost[0][f] += COST_BLACK_THUMB
            if f+1 == 5: min_cost[0][f] += COST_BLACK_PINKY

    # FORWARD PASS: Accumulate costs across the trellis
    for i in range(1, n_notes):
        p_prev = notes[i-1]['pitch']
        p_curr = notes[i]['pitch']
        is_black_curr = notes[i]['is_black']

        for f_curr in range(1, 6): # Current finger (1-5)
            best_prev_cost = np.inf
            best_prev_f = 0
            
            for f_prev in range(1, 6): # Previous finger (1-5)
                # Calculate the cost of this specific transition f_prev -> f_curr
                trans_cost = calculate_transition_cost(
                    p_prev, f_prev, 
                    p_curr, f_curr, 
                    is_black_curr, 
                    hand=hand
                )
                
                total_cumulative_cost = min_cost[i-1][f_prev-1] + trans_cost
                
                if total_cumulative_cost < best_prev_cost:
                    best_prev_cost = total_cumulative_cost
                    best_prev_f = f_prev
            
            # Store results in trellis
            min_cost[i][f_curr-1] = best_prev_cost
            backpointer[i][f_curr-1] = best_prev_f

    # BACKWARD PASS: Reconstruct the optimal path from the end
    result_fingers = [0] * n_notes
    current_f = np.argmin(min_cost[n_notes-1]) + 1
    result_fingers[n_notes-1] = int(current_f)

    for i in range(n_notes - 1, 0, -1):
        prev_f = backpointer[i][current_f-1]
        result_fingers[i-1] = int(prev_f)
        current_f = prev_f

    return result_fingers

def distribute_chord_fingers(pitches: List[music21.pitch.Pitch], anchor_finger: int, hand: str = "right") -> List[int]:
    """
    Distributes fingers across a chord given an anchor finger (usually for the top/bottom note).
    Uses a simple ergonomic spreading heuristic.
    """
    if len(pitches) == 1:
        return [anchor_finger]
        
    sorted_pitches = sorted(pitches, key=lambda x: x.midi)
    n = len(sorted_pitches)
    res = [0] * n
    
    if hand == "right":
        # Anchor finger is for the HIGHEST note
        res[-1] = anchor_finger
        # Fill downwards
        curr_f = anchor_finger
        for i in range(n-2, -1, -1):
            interval = sorted_pitches[i+1].midi - sorted_pitches[i].midi
            # If interval is large (>7), jump to thumb (1)
            if interval >= 7:
                curr_f = 1
            else:
                curr_f = max(1, curr_f - (1 if interval <= 2 else 2))
            res[i] = curr_f
    else:
        # Anchor finger is for the LOWEST note (Pinky/1 usually)
        res[0] = anchor_finger
        # Fill upwards
        curr_f = anchor_finger
        for i in range(1, n):
            interval = sorted_pitches[i].midi - sorted_pitches[i-1].midi
            if interval >= 7:
                curr_f = 5
            else:
                curr_f = min(5, curr_f + (1 if interval <= 2 else 2))
            res[i] = curr_f
            
    # Ensure uniqueness (simple fallback)
    used = set()
    for i in range(len(res)):
        if res[i] in used or res[i] == 0:
            for f in (range(1, 6) if hand == "right" else range(5, 0, -1)):
                if f not in used:
                    res[i] = f
                    break
        used.add(res[i])
        
    return res

def inject_fingering_to_stream(stream: music21.stream.Stream, hand: str = "right") -> music21.stream.Stream:
    """
    Parses a music21 stream, calculates optimal fingerings using the 
    Viterbi model, and attaches them back to the score objects.
    """
    # Flatten and extract notes
    flat = stream.flatten().notes
    note_data = []
    m21_elements = []

    for el in flat:
        if isinstance(el, music21.note.Note):
            note_data.append({
                'pitch': el.pitch.midi,
                'is_black': el.pitch.accidental is not None
            })
            m21_elements.append(el)
        elif isinstance(el, music21.chord.Chord):
            # Target for optimization is highest (RH) or lowest (LH)
            target_p = max(el.pitches, key=lambda x: x.midi) if hand == "right" else min(el.pitches, key=lambda x: x.midi)
            note_data.append({
                'pitch': target_p.midi,
                'is_black': target_p.accidental is not None
            })
            m21_elements.append(el)

    # Solve optimal fingers
    fingers = optimize_fingering(note_data, hand=hand)

    # Inject results
    for i, anchor_f in enumerate(fingers):
        el = m21_elements[i]
        
        # Clear existing fingerings if any
        el.articulations = [a for a in el.articulations 
                           if not isinstance(a, music21.articulations.Fingering)]
        
        if isinstance(el, music21.note.Note):
            el.articulations.append(music21.articulations.Fingering(anchor_f))
        elif isinstance(el, music21.chord.Chord):
            # Distribute fingers uniquely across chord
            chord_fingers = distribute_chord_fingers(list(el.pitches), anchor_f, hand=hand)
            # Assign fingerings to the internal Note objects to prevent ambiguity
            # Match them by pitch (both our distribution and el.notes are sorted)
            chord_notes = sorted(el.notes, key=lambda n: n.pitch.midi)
            for j, n in enumerate(chord_notes):
                # Clear existing fingerings on the note object itself
                n.articulations = [a for a in n.articulations 
                                  if not isinstance(a, music21.articulations.Fingering)]
                f_obj = music21.articulations.Fingering(chord_fingers[j])
                n.articulations.append(f_obj)

    return stream

if __name__ == "__main__":
    # Internal Unit Test Example
    print("Optimization Engine: Running internal test for C Major scale...")
    
    # C4 -> C5 scale
    c_major = [60, 62, 64, 65, 67, 69, 71, 72]
    test_notes = [{'pitch': p, 'is_black': False} for p in c_major]
    
    solved_rh = optimize_fingering(test_notes, hand="right")
    print(f"Solved RH (C Major): {solved_rh}")
    # Expected: 1, 2, 3, 1, 2, 3, 4, 5 (standard scale fingering)
    
    # G Major scale (includes F# / Black Key)
    g_major = [67, 69, 71, 72, 74, 76, 78, 79]
    test_g = [{'pitch': p, 'is_black': (p % 12) in [1, 3, 6, 8, 10]} for p in g_major]
    solved_g = optimize_fingering(test_g, hand="right")
    print(f"Solved RH (G Major): {solved_g}")
