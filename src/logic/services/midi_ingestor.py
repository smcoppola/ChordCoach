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
    tagged, single_track = _collect_notes_with_hands(pm)
    if not tagged:
        raise ValueError("No playable notes found in MIDI file")

    to_beats = _make_beat_converter(pm, tagged)
    groups = _group_chords(tagged)
    quantized = _quantize_groups(groups, to_beats)
    if single_track:
        assign_hands(quantized)

    time_signatures = _extract_time_signatures(pm, to_beats)
    tempo_map = _extract_tempo_map(pm, to_beats)
    pedal_events = _extract_pedal_events(pm, to_beats)

    title = Path(file_path).stem.replace("_", " ").replace("-", " ").strip().title()
    return {
        "title": title or "Imported Song",
        "bpm": to_beats.bpm,
        "groups": quantized,
        "time_signatures": time_signatures,
        "tempo_map": tempo_map,
        "pedal_events": pedal_events,
        "single_track": single_track,
    }


def _extract_time_signatures(pm, to_beats) -> List[dict]:
    sigs = []
    for ts in pm.time_signature_changes:
        off = round(to_beats(ts.time), 5)
        sigs.append({"offset": off, "numerator": int(ts.numerator), "denominator": int(ts.denominator)})
    sigs.sort(key=lambda s: s["offset"])

    if not sigs or sigs[0]["offset"] > 0:
        sigs.insert(0, {"offset": 0.0, "numerator": 4, "denominator": 4})

    # Dedup by offset (keep last)
    dedup = {}
    for s in sigs:
        dedup[s["offset"]] = s
    return [dedup[k] for k in sorted(dedup.keys())]


def _extract_tempo_map(pm, to_beats) -> List[dict]:
    tempo_times, tempi = pm.get_tempo_changes()
    tempo_map = []
    for t, b in zip(tempo_times, tempi):
        off = round(to_beats(t), 5)
        tempo_map.append({"offset": off, "bpm": round(float(b), 2)})
    tempo_map.sort(key=lambda tm: tm["offset"])

    if not tempo_map or tempo_map[0]["offset"] > 0:
        tempo_map.insert(0, {"offset": 0.0, "bpm": round(to_beats.bpm, 2)})

    dedup = {}
    for tm in tempo_map:
        dedup[tm["offset"]] = tm
    return [dedup[k] for k in sorted(dedup.keys())]


def _extract_pedal_events(pm, to_beats) -> List[dict]:
    pedals = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for cc in inst.control_changes:
            if cc.number == 64:
                off = round(to_beats(cc.time), 5)
                is_down = bool(cc.value >= 64)
                pedals.append({"offset": off, "down": is_down})
    pedals.sort(key=lambda p: (p["offset"], not p["down"]))

    # Clean up duplicate state changes at exact same offset
    cleaned = []
    last_state = None
    for p in pedals:
        if p["down"] != last_state:
            cleaned.append(p)
            last_state = p["down"]
    return cleaned


def _collect_notes_with_hands(pm) -> Tuple[List[Tuple[object, str]], bool]:
    """Assign each note a hand. Two+ tracks: lower-pitched track is the left
    hand. Single track: provisional middle-C split, refined per chord group
    later by _refine_hands. Returns (tagged_notes, is_single_track)."""
    insts = [i for i in pm.instruments if not i.is_drum and i.notes]
    if not insts:
        return [], False

    single_track = len(insts) < 2
    if not single_track:
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
    return tagged, single_track


HAND_ALGO_VERSION = 2  # bump when assign_hands changes enough to re-migrate

# Viterbi cost weights (all in "penalty per semitone" unless noted)
_SPAN_COMFORT = 9        # free reach within a hand
_SPAN_STRETCH = 12       # up to here costs _W_STRETCH per semitone
_W_STRETCH = 1.5
_W_IMPOSSIBLE = 6.0      # per semitone beyond _SPAN_STRETCH
_W_EXTRA_FINGER = 8.0    # per simultaneous note beyond 5 in one hand
_W_REGISTER = 0.4        # gentle prior: LH belongs below ~E4, RH above ~G3
_LH_HIGH, _RH_LOW = 64, 55
_W_MOVE = 0.6            # hand-center movement between consecutive groups
_FREE_STEP = 2.0         # semitones of free movement — stepwise lines cost 0
_REST_RELAX = 2.0        # beats of silence after which movement cost halves
_W_NEW_HAND = 3.0        # cost to introduce a hand with no playing history —
                         # comparable to a large leap, so a melody keeps its
                         # hand across leaps instead of recruiting the idle one


def assign_hands(groups):
    """
    Continuity-aware hand assignment for single-track recordings (Viterbi).

    Per-group candidate states are split indices k: the k lowest pitches go
    to the left hand, the rest to the right (k=0 all-RH, k=n all-LH).
    Emission costs penalize unplayable spans, >5 notes per hand, and
    out-of-register hands; transition costs penalize hand-center movement,
    so a melody that dips below middle C stays in the right hand instead of
    flip-flopping between staves. Mutates groups in place and returns them.
    """
    if not groups:
        return groups

    seqs = [sorted(p for p, _h in g["notes"]) for g in groups]
    times = [float(g["offset"]) for g in groups]

    def emission(pitches, k):
        cost = 0.0
        for hand in (pitches[:k], pitches[k:]):
            if len(hand) >= 2:
                span = hand[-1] - hand[0]
                if span > _SPAN_STRETCH:
                    cost += (_SPAN_STRETCH - _SPAN_COMFORT) * _W_STRETCH \
                            + (span - _SPAN_STRETCH) * _W_IMPOSSIBLE
                elif span > _SPAN_COMFORT:
                    cost += (span - _SPAN_COMFORT) * _W_STRETCH
            if len(hand) > 5:
                cost += (len(hand) - 5) * _W_EXTRA_FINGER
        lh, rh = pitches[:k], pitches[k:]
        if lh:
            c = sum(lh) / len(lh)
            if c > _LH_HIGH:
                cost += (c - _LH_HIGH) * _W_REGISTER
        if rh:
            c = sum(rh) / len(rh)
            if c < _RH_LOW:
                cost += (_RH_LOW - c) * _W_REGISTER
        return cost

    # dp[k] = (total_cost, prev_state_index, ctx)
    # ctx = (lh_center, lh_last_time, rh_center, rh_last_time) carried along
    # the best path so a hand that rests keeps its position
    def apply_ctx(ctx, pitches, k, t):
        lh, rh = pitches[:k], pitches[k:]
        lh_c, lh_t, rh_c, rh_t = ctx
        if lh:
            lh_c, lh_t = sum(lh) / len(lh), t
        if rh:
            rh_c, rh_t = sum(rh) / len(rh), t
        return (lh_c, lh_t, rh_c, rh_t)

    def transition(ctx, pitches, k, t):
        # Movement beyond a whole step costs; stepwise lines are free so a
        # melody can dip below middle C without the LH stealing its notes
        cost = 0.0
        lh_c, lh_t, rh_c, rh_t = ctx
        lh, rh = pitches[:k], pitches[k:]
        if lh:
            if lh_c is None:
                cost += _W_NEW_HAND
            else:
                w = _W_MOVE * (0.5 if (t - lh_t) > _REST_RELAX else 1.0)
                cost += max(0.0, abs(sum(lh) / len(lh) - lh_c) - _FREE_STEP) * w
        if rh:
            if rh_c is None:
                cost += _W_NEW_HAND
            else:
                w = _W_MOVE * (0.5 if (t - rh_t) > _REST_RELAX else 1.0)
                cost += max(0.0, abs(sum(rh) / len(rh) - rh_c) - _FREE_STEP) * w
        return cost

    empty_ctx = (None, 0.0, None, 0.0)
    dp = [(emission(seqs[0], k), -1, apply_ctx(empty_ctx, seqs[0], k, times[0]))
          for k in range(len(seqs[0]) + 1)]

    choices: list = [0] * len(groups)
    backptrs = []
    for i in range(1, len(groups)):
        pitches, t = seqs[i], times[i]
        new_dp = []
        ptr_row = []
        for k in range(len(pitches) + 1):
            e = emission(pitches, k)
            total, pk, pctx = min(
                ((dp[j][0] + e + transition(dp[j][2], pitches, k, t), j, dp[j][2])
                 for j in range(len(dp))),
                key=lambda cand: cand[0])
            new_dp.append((total, pk, apply_ctx(pctx, pitches, k, t)))
            ptr_row.append(pk)
        dp = new_dp
        backptrs.append(ptr_row)

    # Backtrack
    k = min(range(len(dp)), key=lambda j: dp[j][0])
    choices[-1] = k
    for i in range(len(groups) - 1, 0, -1):
        k = backptrs[i - 1][k]
        choices[i - 1] = k

    for g, pitches, k in zip(groups, seqs, choices):
        g["notes"] = [(p, "left") for p in pitches[:k]] + \
                     [(p, "right") for p in pitches[k:]]
    return groups


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
                vel = getattr(n, "velocity", None)
                seen[n.pitch] = (hand, int(vel) if vel is not None else None)
        
        sorted_pitches = sorted(seen.keys())
        notes = [(p, seen[p][0]) for p in sorted_pitches]
        velocities = [seen[p][1] for p in sorted_pitches]

        if result and result[-1]["offset"] == offset:
            # Two live "chords" snapped to the same grid point — merge
            merged_hand = {p: h for p, h in result[-1]["notes"]}
            merged_vel = {p: v for p, v in zip([p for p, _ in result[-1]["notes"]], result[-1]["velocities"])}
            for p, (h, v) in seen.items():
                merged_hand.setdefault(p, h)
                merged_vel.setdefault(p, v)
            
            sorted_m = sorted(merged_hand.keys())
            result[-1]["notes"] = [(p, merged_hand[p]) for p in sorted_m]
            result[-1]["velocities"] = [merged_vel[p] for p in sorted_m]
            result[-1]["duration"] = max(result[-1]["duration"], dur)
            continue

        result.append({"offset": offset, "duration": dur, "notes": notes, "velocities": velocities})

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
