"""
MIDI Import Pipeline — parses a user-supplied MIDI file (often a live,
unquantized performance) and produces timing-cleaned note groups in
quarterLength units, ready for conversion into a music21 score.

Timing cleanup strategy:
- If the file carries a real tempo map (>1 tempo event, i.e. exported from
  notation software), trust the file's own tick grid.
- Otherwise (live capture at the default 120bpm), estimate the actual tempo
  from note onsets and build a grid phase-aligned to the first note.
- Notes whose onsets fall within CHORD_WINDOW_SEC of each other are merged
  into one chord group, then group onsets/durations snap to a 16th-note grid.
"""
import pretty_midi  # type: ignore
from pathlib import Path
from typing import List, Tuple

GRID = 0.25              # 16th note, in quarterLength units
CHORD_WINDOW_SEC = 0.08  # notes within 80ms are considered one chord
MIN_BPM, MAX_BPM = 40, 200
LEFT_HAND_SPLIT = 60     # middle C — single-track fallback split point


def parse_and_quantize(file_path: str) -> dict:
    """
    Returns {
        "title": str,
        "bpm": float,
        "groups": [ {"offset": float, "duration": float,
                     "notes": [(pitch:int, hand:str), ...]} ],
    }
    Raises ValueError if the file contains no usable notes.
    """
    pm = pretty_midi.PrettyMIDI(file_path)
    tagged = _collect_notes_with_hands(pm)
    if not tagged:
        raise ValueError("No playable notes found in MIDI file")

    to_beats = _make_beat_converter(pm, tagged)
    groups = _group_chords(tagged)
    quantized = _quantize_groups(groups, to_beats)

    title = Path(file_path).stem.replace("_", " ").replace("-", " ").strip().title()
    return {
        "title": title or "Imported Song",
        "bpm": to_beats.bpm,
        "groups": quantized,
    }


def _collect_notes_with_hands(pm) -> List[Tuple[object, str]]:
    """Assign each note a hand. Two+ tracks: lower-pitched track is the left
    hand. Single track: split at middle C."""
    insts = [i for i in pm.instruments if not i.is_drum and i.notes]
    if not insts:
        return []

    if len(insts) >= 2:
        # Two busiest tracks are assumed to be the two hands
        insts.sort(key=lambda i: len(i.notes), reverse=True)
        a, b = insts[0], insts[1]
        mean_a = sum(n.pitch for n in a.notes) / len(a.notes)
        mean_b = sum(n.pitch for n in b.notes) / len(b.notes)
        right, left = (a, b) if mean_a >= mean_b else (b, a)
        tagged = [(n, "right") for n in right.notes] + [(n, "left") for n in left.notes]
    else:
        tagged = [(n, "right" if n.pitch >= LEFT_HAND_SPLIT else "left")
                  for n in insts[0].notes]

    tagged.sort(key=lambda t: (t[0].start, t[0].pitch))
    return tagged


class _BeatConverter:
    """Converts absolute seconds to quarterLength beats."""

    def __init__(self, pm, bpm: float, phase_sec: float, use_tick_grid: bool):
        self._pm = pm
        self.bpm = bpm
        self._phase = phase_sec
        self._use_ticks = use_tick_grid

    def __call__(self, t_sec: float) -> float:
        if self._use_ticks:
            return self._pm.time_to_tick(t_sec) / self._pm.resolution
        return max(0.0, (t_sec - self._phase)) * self.bpm / 60.0

    def duration(self, start_sec: float, end_sec: float) -> float:
        if self._use_ticks:
            return (self._pm.time_to_tick(end_sec) - self._pm.time_to_tick(start_sec)) / self._pm.resolution
        return (end_sec - start_sec) * self.bpm / 60.0


def _make_beat_converter(pm, tagged) -> _BeatConverter:
    _, tempi = pm.get_tempo_changes()
    has_tempo_map = len(tempi) > 1

    if has_tempo_map:
        # Score-exported MIDI: its own tick grid is authoritative
        return _BeatConverter(pm, float(tempi[0]), 0.0, use_tick_grid=True)

    # Live capture: estimate the real tempo from onsets
    try:
        bpm = float(pm.estimate_tempo())
    except Exception:
        bpm = float(tempi[0]) if len(tempi) else 120.0
    # estimate_tempo often returns double/half time — fold into playable range
    while bpm > MAX_BPM:
        bpm /= 2.0
    while bpm < MIN_BPM:
        bpm *= 2.0

    first_onset = tagged[0][0].start
    return _BeatConverter(pm, bpm, first_onset, use_tick_grid=False)


def _group_chords(tagged) -> List[dict]:
    """Cluster notes whose onsets are within CHORD_WINDOW_SEC into chords."""
    groups = []
    current = None
    for n, hand in tagged:
        if current is not None and (n.start - current["start"]) <= CHORD_WINDOW_SEC:
            current["notes"].append((n, hand))
            current["end"] = max(current["end"], n.end)
        else:
            current = {"start": n.start, "end": n.end, "notes": [(n, hand)]}
            groups.append(current)
    return groups


def _quantize_groups(groups, to_beats: _BeatConverter) -> List[dict]:
    """Snap group onsets and durations to the grid; merge collisions."""
    result = []
    for g in groups:
        offset = round(to_beats(g["start"]) / GRID) * GRID
        dur = to_beats.duration(g["start"], g["end"])
        dur = max(GRID, round(dur / GRID) * GRID)

        # Deduplicate pitches within the group (keep first hand tag seen)
        seen = {}
        for n, hand in g["notes"]:
            if n.pitch not in seen:
                seen[n.pitch] = hand
        notes = sorted(seen.items())  # [(pitch, hand)]

        if result and result[-1]["offset"] == offset:
            # Two live "chords" snapped to the same grid point — merge
            merged = {p: h for p, h in result[-1]["notes"]}
            for p, h in notes:
                merged.setdefault(p, h)
            result[-1]["notes"] = sorted(merged.items())
            result[-1]["duration"] = max(result[-1]["duration"], dur)
            continue

        result.append({"offset": offset, "duration": dur, "notes": notes})

    # Normalize so the song starts at beat 0
    if result:
        base = result[0]["offset"]
        for g in result:
            g["offset"] = round((g["offset"] - base) / GRID) * GRID

    # Trim durations that overlap the next onset in the same hand (live
    # legato bleed makes notation unreadable otherwise)
    for i, g in enumerate(result):
        g_hands = {h for _, h in g["notes"]}
        for nxt in result[i + 1:]:
            if not g_hands & {h for _, h in nxt["notes"]}:
                continue
            gap = nxt["offset"] - g["offset"]
            if gap > 0:
                g["duration"] = max(GRID, min(g["duration"], gap))
            break

    return result
