"""
Chooses the exercises of a lesson, locally.

Lessons used to be sequenced by the live coach model: every exercise was a
`set_exercise` tool call, so a lesson could not run without a connection and
needed failsafe timers for the calls the model forgot. The sequencer makes
those decisions from the curriculum plan instead, and the coach is left to
introduce and comment.

It is pure Python with a seedable RNG, so a lesson can be replayed exactly in
tests. Each exercise is a dict in the shape ChordTrainerService.present_exercise
accepts (the fields of the old `set_exercise` tool):

    exercise_type, exercise_name, track, milestone_id, plus per type —
    chord / hands_together / sustain_pedal: root_idx, chord_type_name,
        inversion, hand, octave, hold_ms, pedal_type
    pentascale: root_idx, scale_type, direction, hand, octave, bpm
    progression: progression_steps [{root_idx, chord_type_name, numeral}]
    listen: root_idx, chord_type_name, target_quality
    song_application: piece_name
    theory_concept: concept_body (a card with a Continue button)

Pacing rules, carried over from what the coach was told to do:
- About `step_count` exercises per block, then the next block.
- Variety: a block's exercises are cycled in shuffled order, so the same one
  never comes up twice running unless the student is struggling.
- A struggled exercise is repeated once; struggling on the repeat as well gets
  a simplified version (root position, no hold, no metronome), then the block
  moves on.
- Songs close their block, and count for SONG_UNITS exercises.
"""
from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_ROOTS = {
    "C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4,
    "F": 5, "E#": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11, "Cb": 11,
}

MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]
MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]
_DIATONIC = {
    "major": ["Major", "Minor", "Minor", "Major", "Major", "Minor", "Diminished"],
    "minor": ["Minor", "Diminished", "Major", "Minor", "Minor", "Major", "Major"],
}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7}

# Qualities the ear-training buttons can answer.
LISTEN_QUALITIES = ("Major", "Minor")
DEFAULT_LISTEN_CHORDS = ["C Major", "F Major", "G Major", "A Minor", "D Minor", "E Minor"]

SONG_UNITS = 5
DEV_MODE_UNITS = 3
DEFAULT_UNITS = 12

INVERSION_NAMES = {1: "1st inversion", 2: "2nd inversion"}


# ── Music helpers ───────────────────────────────────────────────────────────

def parse_key(name: str) -> Tuple[int, str]:
    """'C' → (0, 'major'); 'Am' → (9, 'minor')."""
    name = name.strip()
    if name.endswith("m") and name[:-1] in _ROOTS:
        return _ROOTS[name[:-1]], "minor"
    return _ROOTS[name], "major"


def parse_chord(name: str) -> Tuple[int, str]:
    """'A Minor' → (9, 'Minor'); 'G Dominant 7th' → (7, 'Dominant 7th'); 'C' → (0, 'Major')."""
    root, _, quality = name.strip().partition(" ")
    if root not in _ROOTS:
        raise ValueError(f"unknown chord root in {name!r}")
    return _ROOTS[root], (quality.strip() or "Major")


def resolve_numeral(numeral: str, key_root: int, mode: str = "major") -> Tuple[int, str]:
    """
    A Roman numeral ('V', 'vi', 'vii°') or Nashville number ('5') in a key, to
    (root_idx, quality). Roman case gives the quality; Nashville numbers take
    the key's diatonic quality.
    """
    scale = MINOR_SCALE if mode == "minor" else MAJOR_SCALE
    text = numeral.strip()
    if text.isdigit():
        degree = int(text)
        return (key_root + scale[degree - 1]) % 12, _DIATONIC[mode][degree - 1]
    diminished = text.endswith(("°", "o"))
    core = text.rstrip("°o")
    degree = _ROMAN[core.upper()]
    if diminished:
        quality = "Diminished"
    else:
        quality = "Major" if core.isupper() else "Minor"
    return (key_root + scale[degree - 1]) % 12, quality


def numeral_for(root: int, quality: str, key_root: int, mode: str = "major") -> str:
    """The Roman numeral of a chord in a key, or '' if it is not diatonic."""
    scale = MINOR_SCALE if mode == "minor" else MAJOR_SCALE
    offset = (root - key_root) % 12
    if offset not in scale:
        return ""
    roman = list(_ROMAN)[scale.index(offset)]
    if quality.startswith("Minor"):
        return roman.lower()
    if quality == "Diminished":
        return roman.lower() + "°"
    return roman


def chord_label(root: int, quality: str) -> str:
    return f"{ROOT_NAMES[root]} {quality}".strip()


def exercise_key(ex: Dict[str, Any]) -> tuple:
    """Identity of an exercise for the variety rule; the display name is ignored."""
    def freeze(v):
        if isinstance(v, dict):
            return tuple(sorted((k, freeze(x)) for k, x in v.items()))
        if isinstance(v, (list, tuple)):
            return tuple(freeze(x) for x in v)
        if isinstance(v, (set, frozenset)):
            # Normalised exercises carry `intervals` as a set (struggled items
            # are stored that way), and a set inside a key is unhashable.
            return frozenset(freeze(x) for x in v)
        return v
    return tuple(sorted((k, freeze(v)) for k, v in ex.items() if k != "exercise_name"))


# ── Pool building ───────────────────────────────────────────────────────────

def _chord_names(spec: Dict[str, Any]) -> List[str]:
    chords = list(spec.get("target_chords") or [])
    if chords:
        return chords
    return [f"{k} Major" if parse_key(k)[1] == "major" else f"{k[:-1]} Minor"
            for k in (spec.get("target_keys") or ["C"])]


def _base(spec: Dict[str, Any], ex_type: str, name: str) -> Dict[str, Any]:
    return {
        "exercise_type": ex_type,
        "exercise_name": name,
        "track": spec.get("track", ""),
        "milestone_id": spec.get("milestone_id", ""),
    }


def _chord_drills(spec, ex_type: str) -> List[Dict[str, Any]]:
    hand = spec.get("hand", "both" if ex_type == "hands_together" else "right")
    octave = 3 if hand == "left" else 4
    inversions = spec.get("inversions") or [0]
    single = bool(spec.get("single_notes"))
    out = []
    for chord in _chord_names(spec):
        root, quality = parse_chord(chord)
        for inv in (inversions if not single else [0]):
            if single:
                name = f"{ROOT_NAMES[root]} {'bass ' if hand == 'left' else ''}note"
            else:
                name = chord_label(root, quality)
                if inv in INVERSION_NAMES:
                    name += f" — {INVERSION_NAMES[inv]}"
            if ex_type == "hands_together":
                name = f"{chord_label(root, quality)} with bass"
            elif ex_type == "sustain_pedal":
                name = f"{name} — {spec.get('pedal_type', 'direct')} pedal"
            ex = _base(spec, ex_type, name)
            ex.update({
                "root_idx": root,
                "chord_type_name": "Single" if single else quality,
                "inversion": int(inv),
                "hand": hand,
                "octave": octave,
                "hold_ms": int(spec.get("hold_ms", 0)),
            })
            if ex_type == "sustain_pedal":
                ex["pedal_type"] = spec.get("pedal_type", "direct")
            out.append(ex)
    return out


def _pentascales(spec) -> List[Dict[str, Any]]:
    out = []
    hand = spec.get("hand", "right")
    for key in spec.get("target_keys") or ["C"]:
        root, mode = parse_key(key)
        scale_type = "Minor" if mode == "minor" else "Major"
        for direction in spec.get("directions") or ["ascending", "descending"]:
            ex = _base(spec, "pentascale",
                       f"{ROOT_NAMES[root]} {scale_type} Pentascale ({direction})")
            ex.update({"root_idx": root, "scale_type": scale_type, "direction": direction,
                       "hand": hand, "octave": 3 if hand == "left" else 4,
                       "bpm": int(spec.get("bpm", 0))})
            out.append(ex)
    return out


def _progression(spec, key_root: int, mode: str, chords: List[Tuple[int, str, str]]):
    numerals = [n for _, _, n in chords]
    label = "–".join(n for n in numerals if n) or " → ".join(chord_label(r, q) for r, q, _ in chords)
    key_name = ROOT_NAMES[key_root] + (" minor" if mode == "minor" else "")
    ex = _base(spec, "progression", f"{label} in {key_name}")
    ex["hand"] = spec.get("hand", "right")
    ex["progression_steps"] = [
        {"root_idx": r, "chord_type_name": q, "numeral": n} for r, q, n in chords
    ]
    return ex


def _progressions(spec) -> List[Dict[str, Any]]:
    out = []
    for prog in spec.get("progressions") or []:
        keys = [prog["key"]] if prog.get("key") else (spec.get("target_keys") or ["C"])
        for key in keys:
            key_root, key_mode = parse_key(key)
            mode = prog.get("mode", key_mode)
            chords = []
            for n in prog["numerals"]:
                root, quality = resolve_numeral(n, key_root, mode)
                chords.append((root, quality, n))
            out.append(_progression(spec, key_root, mode, chords))
    if out:
        return out

    targets = spec.get("target_chords") or []
    if len(targets) >= 2:
        key_root, mode = parse_key((spec.get("target_keys") or ["C"])[0])
        chords = []
        for name in targets:
            root, quality = parse_chord(name)
            chords.append((root, quality, numeral_for(root, quality, key_root, mode)))
        return [_progression(spec, key_root, mode, chords)]

    for key in spec.get("target_keys") or ["C"]:
        key_root, mode = parse_key(key)
        chords = [(*resolve_numeral(n, key_root, mode), n) for n in ("I", "IV", "V", "I")]
        out.append(_progression(spec, key_root, mode, chords))
    return out


def _listens(spec) -> List[Dict[str, Any]]:
    out = []
    names = spec.get("target_chords") or DEFAULT_LISTEN_CHORDS
    for name in names:
        root, quality = parse_chord(name)
        if quality not in LISTEN_QUALITIES:
            continue
        ex = _base(spec, "listen", "Major or Minor?")
        ex.update({"root_idx": root, "chord_type_name": quality,
                   "target_quality": quality, "octave": 4})
        out.append(ex)
    return out


def _songs(spec, library: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    titles = {s.get("id"): s.get("title") for s in library}
    candidates = list(spec.get("suggested_pieces") or []) + [s.get("id") for s in library]
    for piece in candidates:
        if not piece or piece in seen:
            continue
        seen.add(piece)
        ex = _base(spec, "song_application", titles.get(piece) or "Repertoire piece")
        ex["piece_name"] = piece
        out.append(ex)
    return out


def build_pool(spec: Dict[str, Any], library: Optional[List[Dict[str, Any]]] = None):
    """
    (drills, songs) for one curriculum milestone. `spec` is the milestone's
    plan block with its curriculum hints merged in.
    """
    drills: List[Dict[str, Any]] = []
    songs: List[Dict[str, Any]] = []
    for ex_type in spec.get("exercise_types") or ["chord"]:
        if ex_type in ("chord", "hands_together", "sustain_pedal"):
            drills += _chord_drills(spec, ex_type)
        elif ex_type == "pentascale":
            drills += _pentascales(spec)
        elif ex_type == "progression":
            drills += _progressions(spec)
        elif ex_type == "listen":
            drills += _listens(spec)
        elif ex_type == "song_application":
            songs += _songs(spec, library or [])
        # theory_concept / key_explorer are cards, added by the block itself.

    if not drills and spec.get("follow_up"):
        follow = dict(spec)
        follow.pop("follow_up")
        follow.update(spec["follow_up"])
        follow["exercise_types"] = [spec["follow_up"].get("exercise_type", "chord")]
        drills, more_songs = build_pool(follow, library)
        songs += more_songs
    return drills, songs


def simplify(ex: Dict[str, Any]) -> Dict[str, Any]:
    """An easier version of an exercise the student struggled with twice."""
    out = dict(ex)
    if out.get("inversion"):
        out["inversion"] = 0
        out["exercise_name"] = out["exercise_name"].split(" — ")[0]
    out["hold_ms"] = 0
    if "bpm" in out:
        out["bpm"] = 0
    if out["exercise_type"] == "pentascale":
        out["direction"] = "ascending"
        out["exercise_name"] = out["exercise_name"].replace("(descending)", "(ascending)")
    elif out["exercise_type"] == "hands_together":
        out["exercise_type"] = "chord"
        out["hand"] = "right"
        out["exercise_name"] = out["exercise_name"].replace(" with bass", "")
    elif out["exercise_type"] == "sustain_pedal":
        out["pedal_type"] = "direct"
    return out


REVIEW_SPEC = {
    "track": "review",
    "milestone_id": "",
    "milestone_title": "Review",
    "milestone_description": "Spaced-repetition review of things learned in earlier lessons.",
}
DEV_MODE_REVIEWS = 2


def review_exercises(items: Iterable[Dict[str, Any]],
                     library: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Exercises for due SM-2 items ({item_type, item_id}): chords and songs."""
    titles = {s.get("id"): s.get("title") for s in library or []}
    out = []
    for item in items:
        kind, item_id = item.get("item_type"), str(item.get("item_id", ""))
        if kind == "chord":
            try:
                root, quality = parse_chord(item_id)
            except (ValueError, KeyError):
                continue
            ex = _base(REVIEW_SPEC, "chord", f"Review: {chord_label(root, quality)}")
            ex.update({"root_idx": root, "chord_type_name": quality, "inversion": 0,
                       "hand": "right", "octave": 4, "hold_ms": 0})
            out.append(ex)
        elif kind == "song" and item_id:
            ex = _base(REVIEW_SPEC, "song_application",
                       f"Review: {titles.get(item_id) or 'a piece you know'}")
            ex["piece_name"] = item_id
            out.append(ex)
    return out


class _FixedBlock:
    """A block that plays a given list in order, once (reviews, review sessions)."""

    def __init__(self, spec: Dict[str, Any], exercises: Iterable[Dict[str, Any]]):
        self.spec = spec
        self.queue = [dict(e) for e in exercises]
        self.excluded: set = set()

    def next(self) -> Optional[Dict[str, Any]]:
        while self.queue:
            ex = self.queue.pop(0)
            if exercise_key(ex) not in self.excluded:
                return ex
        return None

    def consumed(self, ex):
        pass

    def refund(self, ex):
        pass


# ── The sequencer ───────────────────────────────────────────────────────────

class _Block:
    def __init__(self, spec, library, units, rng):
        self.spec = spec
        self.units = units
        drills, songs = build_pool(spec, library)
        self.queue: List[Dict[str, Any]] = []

        types = spec.get("exercise_types") or []
        if "theory_concept" in types or "key_explorer" in types:
            card = _base(spec, "theory_concept", spec.get("milestone_title") or "New idea")
            card["concept_body"] = spec.get("milestone_description", "")
            self.queue.append(card)

        if not drills and not songs and not self.queue:
            drills = _chord_drills({**spec, "target_chords": ["C Major"]}, "chord")

        self._drills = drills
        self._songs = songs
        self._rng = rng
        self._cycle: List[Dict[str, Any]] = []
        self._last: Optional[tuple] = None
        self.excluded: set = set()

    def _song_budget(self) -> int:
        return SONG_UNITS if self._songs else 0

    def next(self) -> Optional[Dict[str, Any]]:
        if self.queue:
            return self.queue.pop(0)
        if self.units <= 0:
            return None

        drills = [d for d in self._drills if exercise_key(d) not in self.excluded]
        if drills and (self.units > self._song_budget() or not self._available_songs()):
            if not self._cycle:
                self._cycle = list(drills)
                self._rng.shuffle(self._cycle)
                if len(self._cycle) > 1 and exercise_key(self._cycle[0]) == self._last:
                    self._cycle.append(self._cycle.pop(0))
            return self._cycle.pop(0)

        songs = self._available_songs()
        if songs:
            return songs[0]
        return None

    def _available_songs(self):
        return [s for s in self._songs if exercise_key(s) not in self.excluded]

    def consumed(self, ex: Dict[str, Any]):
        cost = SONG_UNITS if ex["exercise_type"] == "song_application" else 1
        if ex["exercise_type"] != "theory_concept":
            self.units -= cost
        self._last = exercise_key(ex)
        if ex["exercise_type"] == "song_application":
            self.excluded.add(exercise_key(ex))  # one play of each piece per block

    def refund(self, ex: Dict[str, Any]):
        if ex["exercise_type"] == "song_application":
            self.units += SONG_UNITS
        elif ex["exercise_type"] != "theory_concept":
            self.units += 1


class LessonSequencer:
    """
    Yields a lesson's exercises one at a time.

    Call `next_exercise(result)` after each exercise with what happened:
    {"struggled": bool} once it was played, or {"failed": True} if it could not
    be presented (a song that would not load), which drops it and refunds its
    place. Returns None when the lesson is over.

    Items in the plan's `review_items` (due SM-2 reviews) open the lesson as
    a "Review" block.
    """

    def __init__(self, plan: Dict[str, Any], hints: Optional[Dict[str, Dict]] = None,
                 library: Optional[List[Dict[str, Any]]] = None,
                 seed: Optional[int] = None, dev_mode: bool = False,
                 units_per_block: Optional[int] = None):
        self._rng = random.Random(seed)
        hints = hints or {}
        self._blocks: List[Any] = []

        reviews = review_exercises(plan.get("review_items") or [], library)
        if dev_mode:
            reviews = reviews[:DEV_MODE_REVIEWS]
        if reviews:
            self._blocks.append(_FixedBlock(REVIEW_SPEC, reviews))

        for block in plan.get("blocks") or []:
            spec = dict(block)
            spec.update(hints.get(block.get("milestone_id", ""), {}))
            if units_per_block is not None:
                units = units_per_block
            elif dev_mode:
                units = DEV_MODE_UNITS
            else:
                units = int(block.get("step_count") or DEFAULT_UNITS)
            self._blocks.append(_Block(spec, library or [], units, self._rng))

        self._current: Optional[Dict[str, Any]] = None
        self._current_block: Any = None
        self._repeat_count = 0
        self.history: List[Dict[str, Any]] = []
        self.struggled: List[str] = []

    @classmethod
    def from_exercises(cls, exercises: Iterable[Dict[str, Any]]) -> "LessonSequencer":
        """A sequencer that plays a fixed list in order (e.g. a review of struggled items)."""
        seq = cls({"blocks": []})
        seq._blocks.append(_FixedBlock(REVIEW_SPEC, exercises))
        return seq

    @property
    def block_titles(self) -> List[str]:
        return [b.spec.get("milestone_title") or b.spec.get("milestone_id", "") for b in self._blocks]

    def current_block_spec(self) -> Dict[str, Any]:
        return self._current_block.spec if self._current_block else {}

    def next_exercise(self, result: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        last, block = self._current, self._current_block
        result = result or {}

        if last is not None and result.get("failed"):
            if block is not None:
                block.refund(last)
                block.excluded.add(exercise_key(last))
            self._repeat_count = 0
        elif last is not None and result.get("struggled"):
            self.struggled.append(last["exercise_name"])
            repeatable = last["exercise_type"] not in ("song_application", "theory_concept")
            if repeatable and self._repeat_count == 0:
                return self._emit(dict(last), block, repeat=1)
            if repeatable and self._repeat_count == 1:
                return self._emit(simplify(last), block, repeat=2)
            self._repeat_count = 0
        else:
            self._repeat_count = 0

        while self._blocks:
            block = self._blocks[0]
            ex = block.next()
            if ex is not None:
                return self._emit(ex, block, repeat=0)
            self._blocks.pop(0)

        self._current = None
        self._current_block = None
        return None

    def _emit(self, ex, block, repeat: int):
        if block is not None:
            block.consumed(ex)
        self._current = ex
        self._current_block = block
        self._repeat_count = repeat
        self.history.append(ex)
        return dict(ex)
