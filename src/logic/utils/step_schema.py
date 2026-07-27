"""
Step Schema v2 — Data model specification & normalization utils.
"""
from typing import List, Dict, Any

CURRENT_SCHEMA_VERSION = 2


def migrate_record(record: dict) -> dict:
    """
    Normalizes any song record (v1/v2 user-song JSON, corpus song dict) to v2 shape in memory.
    Idempotent: passing an already-v2 record returns it safely formatted.
    """
    if not isinstance(record, dict):
        return record

    rec = dict(record)

    # Song-level defaults
    rec["schema_version"] = rec.get("schema_version", CURRENT_SCHEMA_VERSION)

    bpm_val = rec.get("bpm") or 100.0
    rec["time_signatures"] = rec.get("time_signatures") or [{"offset": 0.0, "numerator": 4, "denominator": 4}]
    rec["tempo_map"] = rec.get("tempo_map") or [{"offset": 0.0, "bpm": float(bpm_val)}]
    rec["pedal_events"] = rec.get("pedal_events") or []
    rec["dynamics"] = rec.get("dynamics") or []

    source_file = rec.get("source_file", "")
    is_xml = isinstance(source_file, str) and source_file.lower().endswith((".xml", ".mxl", ".musicxml"))
    rec["source_type"] = rec.get("source_type") or ("musicxml" if is_xml else "midi")
    rec["track_hands_reliable"] = rec.get("track_hands_reliable", False)
    rec["pristine_groups"] = rec.get("pristine_groups", None)
    rec["source_hash"] = rec.get("source_hash", None)
    rec["source_copy"] = rec.get("source_copy", None)

    # Step-level normalization
    raw_steps = rec.get("steps", [])
    migrated_steps = []
    for step in raw_steps:
        s = dict(step)
        pitches = s.get("pitches", [])
        n_notes = len(pitches)

        # Single scalar duration for v1 fallback consumers
        step_dur = s.get("duration", 0.25)
        if "durations" not in s or not s["durations"]:
            s["durations"] = [step_dur] * n_notes
        else:
            s["duration"] = max(s["durations"]) if s["durations"] else step_dur

        if "tuplets" not in s or len(s["tuplets"]) != n_notes:
            s["tuplets"] = s.get("tuplets") or [None] * n_notes

        if "articulations" not in s or len(s["articulations"]) != n_notes:
            s["articulations"] = s.get("articulations") or [[] for _ in range(n_notes)]

        if "velocities" not in s or len(s["velocities"]) != n_notes:
            s["velocities"] = s.get("velocities") or [None] * n_notes

        migrated_steps.append(s)

    rec["steps"] = migrated_steps
    return rec


def compute_barlines(time_signatures: List[Dict[str, Any]], end_beat: float) -> List[float]:
    """
    Computes barline beat offsets from a list of time signature changes up to end_beat.
    A time signature change resets the measure origin at its offset.
    """
    if not time_signatures or end_beat <= 0:
        return []

    sorted_sigs = sorted(time_signatures, key=lambda ts: ts.get("offset", 0.0))

    barlines = []
    for i, ts in enumerate(sorted_sigs):
        start_off = float(ts.get("offset", 0.0))
        num = int(ts.get("numerator", 4))
        den = int(ts.get("denominator", 4))
        measure_len = num * (4.0 / den)

        if start_off >= end_beat:
            break

        # Next segment boundary
        next_off = float(sorted_sigs[i + 1]["offset"]) if i + 1 < len(sorted_sigs) else end_beat
        next_off = min(next_off, end_beat)

        # If start_off > 0 and start_off isn't in barlines yet, add it as measure start
        if start_off > 0 and (not barlines or abs(barlines[-1] - start_off) > 1e-5):
            barlines.append(start_off)

        curr = start_off + measure_len
        while curr <= next_off + 1e-5:
            if curr > 0 and (not barlines or abs(barlines[-1] - curr) > 1e-5):
                barlines.append(round(curr, 5))
            curr += measure_len

    return barlines


def groups_from_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Projects v2 steps into [{offset, duration, notes: [(pitch, hand)]}] format
    suitable for _simplify_groups and re-arrangements.
    """
    groups = []
    for s in steps:
        off = float(s.get("offset", 0.0))
        durations = s.get("durations", [])
        dur = float(s.get("duration", max(durations) if durations else 0.25))
        pitches = s.get("pitches", [])
        hands = s.get("hands", [])

        notes = []
        for p, h in zip(pitches, hands):
            notes.append((int(p), str(h)))

        groups.append({
            "offset": off,
            "duration": dur,
            "notes": notes,
        })
    return groups
