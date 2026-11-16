"""Score analysis, and the QML-facing front for the corpus catalogue and song library."""
import os
import re
from PySide6.QtCore import QObject, Signal, Slot, Property
import music21
from music21 import corpus, note, chord, stream
from logic.utils.fingering_optimizer import inject_fingering_to_stream, distribute_chord_fingers
from logic.utils.step_schema import migrate_record, compute_barlines
from logic.services.corpus_catalog import CorpusCatalog
from logic.services.song_library import SongLibrary, USER_SONG_PREFIX


class Music21Service(QObject):
    """
    Turns scores into the steps the app plays, and is the one object QML
    talks to about songs.

    The songs themselves live in two collaborators it owns — `catalog`
    (CorpusCatalog: the built-in corpus browser) and `library` (SongLibrary:
    the student's imported songs). Their signals are re-emitted here and
    their public slots are delegated by name below, so `appState.music21Service`
    is unchanged for QML.
    """
    songRequested = Signal(str)
    corpusProgressChanged = Signal(float)
    corpusStatusChanged = Signal(str)
    corpusReady = Signal()
    corpusError = Signal()
    userSongsChanged = Signal()
    importSucceeded = Signal(str)       # song_id
    importFailed = Signal(str)          # error message
    importDuplicate = Signal(str, str)   # existing_song_id, existing_title
    songLevelFailed = Signal(str)        # error message (async level generation)

    USER_SONG_PREFIX = USER_SONG_PREFIX
    SIMPLIFY_LEVELS = SongLibrary.SIMPLIFY_LEVELS

    def __init__(self, project_root=None):
        super().__init__()
        self.library = SongLibrary(self._extract_steps_from_score,
                                   self._build_score_from_groups,
                                   self._score_difficulty)
        self.catalog = CorpusCatalog(project_root, user_songs=self.library.entries)
        self.library.setParent(self)
        self.catalog.setParent(self)

        for name in ('songRequested', 'userSongsChanged', 'importSucceeded', 'importFailed', 'importDuplicate', 'songLevelFailed'):
            getattr(self.library, name).connect(getattr(self, name))
        for name in ('corpusProgressChanged', 'corpusStatusChanged', 'corpusReady', 'corpusError'):
            getattr(self.catalog, name).connect(getattr(self, name))

    def set_database(self, db):
        """AppState hands the DatabaseManager over so the library can show mastery."""
        self.library.set_database(db)

    def set_chord_trainer(self, trainer):
        """
        The trainer, so the library can refuse to edit or delete the song in
        play. The library is only told which song is active, not handed the trainer.
        """
        if trainer is None:
            self.library.set_active_song(None)
            return
        self.library.set_active_song(
            lambda: str(trainer.songId or "") if trainer.isActive else "")

    # ── Score → steps ────────────────────────────────────────────────

    def load_song_as_steps(self, piece_name: str) -> dict:
        cached = self.library.cached_steps(piece_name)
        if cached is not None:
            return cached

        if piece_name.startswith(self.USER_SONG_PREFIX):
            try:
                return self.library.load_steps(piece_name)
            except Exception as e:
                # A hallucinated / deleted user:: id must fail the same way a bad
                # corpus id does — an empty error record the caller can recover from.
                print(f"Music21Service: Error loading user song {piece_name}: {e}")
                return {"steps": [], "title": "Error", "key": "Direct Error"}

        try:
            tune_index = None
            if "::" in piece_name:
                base_path, idx_str = piece_name.split("::")
                piece_name = base_path
                try:
                    tune_index = int(idx_str)
                except Exception:
                    tune_index = None

            print(f"Music21Service: Loading '{piece_name}'" + (f" (Tune {tune_index})" if tune_index else "") + "...")
            score = corpus.parse(piece_name)

            if isinstance(score, stream.Opus):
                if tune_index is not None:
                    try:
                        score = score.getScoreByNumber(tune_index)
                    except Exception:
                        score = score[0]
                else:
                    score = score[0]

            if not isinstance(score, (stream.Score, stream.Part, stream.Stream)):
                for el in score:
                    if isinstance(el, (stream.Score, stream.Part, stream.Stream)):
                        score = el
                        break

            title = "Unknown Piece"
            composer = "Unknown Composer"

            flat_lookup = {}
            def build_lookup(node):
                if isinstance(node, list):
                    for item in node:
                        if isinstance(item, dict):
                            if item.get("isCategory") and "children" in item:
                                build_lookup(item["children"])
                            else:
                                flat_lookup[item["id"]] = item
                elif isinstance(node, dict):
                    for v in node.values():
                        build_lookup(v)
            build_lookup(self.catalog.tree())

            full_id = f"{piece_name}::{tune_index}" if tune_index else piece_name
            if full_id in flat_lookup:
                title = flat_lookup[full_id]['title']
                composer = flat_lookup[full_id].get('artist', "Unknown Composer")
            else:
                if hasattr(score, 'metadata') and score.metadata:
                    title = (score.metadata.title or
                             score.metadata.movementName or
                             score.metadata.workTitle or
                             "Unknown Piece")
                    composer = (score.metadata.composer or "Unknown Composer")

            if title == "Unknown Piece" or ".mxl" in title.lower() or ".xml" in title.lower():
                title = os.path.basename(piece_name).replace(".mxl", "").replace(".xml", "").replace(".abc", "").replace(".krn", "").replace("_", " ").title()

            try:
                analyzed_key = score.analyze('key')
                key_name = f"{analyzed_key.tonic.name} {analyzed_key.mode.capitalize()}"
                key_sharps = analyzed_key.sharps
            except Exception:
                key_name = "Unknown Key"
                key_sharps = 0

            steps, barlines, extra_meta = self._extract_steps_from_score(score)

            rec = {
                "steps": steps,
                "title": title,
                "composer": composer,
                "key": key_name,
                "key_sharps": key_sharps,
                "barlines": barlines,
                "time_signatures": extra_meta.get("time_signatures"),
                "tempo_map": extra_meta.get("tempo_map"),
                "dynamics": extra_meta.get("dynamics"),
            }
            rec = migrate_record(rec)
            print(f"Music21Service: Loaded {len(steps)} steps for '{title}' in {key_name}.")
            return rec
        except Exception as e:
            print(f"Music21Service: Error loading {piece_name}: {e}")
            import traceback
            traceback.print_exc()
            return {"steps": [], "title": "Error", "key": "Direct Error"}

    def _extract_steps_from_score(self, score):
        parts = getattr(score, 'parts', None)
        all_parts = list(parts) if parts else [score]

        time_signatures = []
        for part_obj in all_parts:
            try:
                for ts in part_obj.getTimeSignatures():
                    time_signatures.append({
                        "offset": float(ts.offset),
                        "numerator": int(ts.numerator),
                        "denominator": int(ts.denominator)
                    })
            except Exception:
                for ts in part_obj.flatten().getElementsByClass(music21.meter.TimeSignature):
                    time_signatures.append({
                        "offset": float(ts.offset),
                        "numerator": int(ts.numerator),
                        "denominator": int(ts.denominator)
                    })
        time_signatures.sort(key=lambda s: s["offset"])
        dedup_ts = {}
        for ts in time_signatures:
            dedup_ts[ts["offset"]] = ts
        time_signatures = [dedup_ts[k] for k in sorted(dedup_ts.keys())]
        if not time_signatures or time_signatures[0]["offset"] > 0:
            time_signatures.insert(0, {"offset": 0.0, "numerator": 4, "denominator": 4})

        tempo_map = []
        for mm in score.flatten().getElementsByClass(music21.tempo.MetronomeMark):
            try:
                bpm_val = float(mm.getQuarterBPM())
                tempo_map.append({"offset": float(mm.offset), "bpm": round(bpm_val, 2)})
            except Exception:
                pass
        tempo_map.sort(key=lambda tm: tm["offset"])
        dedup_tm = {}
        for tm in tempo_map:
            dedup_tm[tm["offset"]] = tm
        tempo_map = [dedup_tm[k] for k in sorted(dedup_tm.keys())]

        dynamics = []
        offset_map = {}

        for i, part_obj in enumerate(all_parts):
            flattened = part_obj.flatten()
            clefs = flattened.getElementsByClass(music21.clef.Clef)
            hand_tag = "left" if (clefs and isinstance(clefs[0], music21.clef.BassClef)) else ("left" if i > 0 else "right")

            for dyn in flattened.getElementsByClass(music21.dynamics.Dynamic):
                dynamics.append({
                    "offset": float(dyn.offset),
                    "mark": str(dyn.value),
                    "hand": hand_tag
                })

            has_native_fingering = any(
                isinstance(a, music21.articulations.Fingering)
                for el in flattened.notesAndRests
                for a in getattr(el, 'articulations', [])
            )
            if not has_native_fingering:
                inject_fingering_to_stream(part_obj, hand=hand_tag)

        for part_index, part_obj in enumerate(all_parts):
            flattened = part_obj.flatten()
            clefs = flattened.getElementsByClass(music21.clef.Clef)
            hand_tag = "left" if (clefs and isinstance(clefs[0], music21.clef.BassClef)) else ("left" if part_index > 0 else "right")

            for el in flattened.notesAndRests:
                dur = float(el.duration.quarterLength)
                off = float(el.offset)

                if off not in offset_map:
                    offset_map[off] = {
                        'pitches': [], 'spellings': [], 'hands': [], 'fingers': [],
                        'durations': [], 'duration': dur, 'ties': [], 'beams': [],
                        'tuplets': [], 'articulations': [], 'velocities': [], 'rests': []
                    }

                if isinstance(el, music21.note.Rest):
                    offset_map[off]['rests'].append({'duration': dur, 'hand': hand_tag})
                    continue

                pitches = []
                spellings = []
                if isinstance(el, note.Note):
                    pitches.append(el.pitch.midi)
                    spellings.append((el.pitch.step, el.pitch.alter))
                elif isinstance(el, chord.Chord):
                    pitches.extend([p.midi for p in el.pitches])
                    spellings.extend([(p.step, p.alter) for p in el.pitches])
                else:
                    continue

                beam_type = None
                if hasattr(el, 'beams') and el.beams and len(el.beams.beamsList) > 0:
                    b1 = el.beams.getByNumber(1)
                    if b1 is not None:
                        beam_type = b1.type

                tuplet_info = None
                if hasattr(el, 'duration') and el.duration and el.duration.tuplets:
                    t = el.duration.tuplets[0]
                    pos_raw = str(t.type).lower()
                    pos = "start" if "start" in pos_raw else ("stop" if ("stop" in pos_raw or "end" in pos_raw) else "continue")
                    tuplet_info = {
                        "actual": int(t.numberNotesActual),
                        "normal": int(t.numberNotesNormal),
                        "pos": pos
                    }

                art_names = []
                if hasattr(el, 'articulations') and el.articulations:
                    for a in el.articulations:
                        if isinstance(a, music21.articulations.Fingering):
                            continue
                        art_names.append(a.__class__.__name__.lower())

                vel_val = None
                if hasattr(el, 'volume') and el.volume and el.volume.velocity is not None:
                    vel_val = int(el.volume.velocity)

                fingerings = []
                ties = []
                if isinstance(el, music21.chord.Chord):
                    internal_notes = sorted(el.notes, key=lambda n: n.pitch.midi)
                    for n in internal_notes:
                        ties.append(n.tie.type if hasattr(n, 'tie') and n.tie else None)
                        f_val = 1
                        for a in n.articulations:
                            if isinstance(a, music21.articulations.Fingering):
                                f_val = a.fingerNumber
                                break
                        fingerings.append(f_val)
                else:
                    ties.append(el.tie.type if hasattr(el, 'tie') and el.tie else None)
                    fingerings = [a.fingerNumber for a in el.articulations if isinstance(a, music21.articulations.Fingering)]

                for i, pitch_val in enumerate(pitches):
                    found = False
                    for existing_pitch in offset_map[off]['pitches']:
                        if existing_pitch == pitch_val:
                            found = True
                            break
                    if not found:
                        f_val = fingerings[i] if i < len(fingerings) else (fingerings[0] if fingerings else 1)
                        t_val = ties[i] if i < len(ties) else None
                        s_val = spellings[i] if i < len(spellings) else None
                        offset_map[off]['pitches'].append(pitch_val)
                        offset_map[off]['spellings'].append(s_val)
                        offset_map[off]['hands'].append(hand_tag)
                        offset_map[off]['fingers'].append(f_val)
                        offset_map[off]['durations'].append(dur)
                        offset_map[off]['ties'].append(t_val)
                        offset_map[off]['beams'].append(beam_type)
                        offset_map[off]['tuplets'].append(tuplet_info)
                        offset_map[off]['articulations'].append(art_names)
                        offset_map[off]['velocities'].append(vel_val)

        for off in offset_map:
            step = offset_map[off]
            step['duration'] = max(step['durations']) if step['durations'] else step['duration']
            for h_tag in ["right", "left"]:
                h_indices = [i for i, h in enumerate(step['hands']) if h == h_tag]
                if len(h_indices) <= 1:
                    continue
                h_pitches = [step['pitches'][i] for i in h_indices]
                m21_pitches = [music21.pitch.Pitch(p) for p in h_pitches]
                anchor = 5 if h_tag == "right" else 1
                new_fingers = distribute_chord_fingers(m21_pitches, anchor, h_tag)
                pitch_to_finger = {p.midi: f for p, f in zip(sorted(m21_pitches, key=lambda x: x.midi), new_fingers)}
                for idx in h_indices:
                    p_midi = step['pitches'][idx]
                    step['fingers'][idx] = pitch_to_finger.get(p_midi, 1)

        sorted_offsets = sorted(offset_map.keys())
        steps = []
        for off in sorted_offsets:
            step_data = offset_map[off]
            paired = sorted(list(zip(
                step_data['pitches'],
                step_data['spellings'],
                step_data['hands'],
                step_data['fingers'],
                step_data['durations'],
                step_data['ties'],
                step_data['beams'],
                step_data['tuplets'],
                step_data['articulations'],
                step_data['velocities']
            )), key=lambda x: x[0])

            steps.append({
                'offset': off,
                'pitches': [p[0] for p in paired],
                'spellings': [p[1] for p in paired],
                'hands': [p[2] for p in paired],
                'fingers': [p[3] for p in paired],
                'durations': [p[4] for p in paired],
                'duration': max([p[4] for p in paired]) if paired else step_data['duration'],
                'ties': [p[5] for p in paired],
                'beams': [p[6] for p in paired],
                'tuplets': [p[7] for p in paired],
                'articulations': [p[8] for p in paired],
                'velocities': [p[9] for p in paired],
                'rests': step_data['rests']
            })

        max_off = round(sorted_offsets[-1] + offset_map[sorted_offsets[-1]]['duration'], 4) if sorted_offsets else 0.0
        barlines_set = set()
        for part_obj in all_parts:
            for m in part_obj.getElementsByClass(music21.stream.Measure):
                if float(m.offset) > 0:
                    barlines_set.add(float(m.offset))
        barlines = sorted(list(barlines_set))
        last_ts = time_signatures[-1] if time_signatures else {"numerator": 4, "denominator": 4}
        last_bar_len = float(last_ts.get("numerator", 4)) * (4.0 / float(last_ts.get("denominator", 4)))
        if not barlines or (max_off - barlines[-1] > last_bar_len + 1e-4):
            barlines = compute_barlines(time_signatures, max_off)

        extra_meta = {
            "time_signatures": time_signatures,
            "tempo_map": tempo_map,
            "dynamics": dynamics,
        }
        return steps, barlines, extra_meta

    def _build_score_from_groups(self, groups, key_name=None, key_sharps=None, time_signatures=None):
        from music21 import pitch as m21pitch, clef as m21clef, meter, key as m21key, duration as m21duration

        if key_name is None or key_sharps is None:
            probe = stream.Stream()
            for g in groups:
                g_dur = float(g.get("duration", 0.25))
                for p, _h in g["notes"]:
                    probe.append(note.Note(pitch=m21pitch.Pitch(midi=p), quarterLength=g_dur))
            try:
                analyzed = probe.analyze('key')
                key_name = f"{analyzed.tonic.name} {analyzed.mode.capitalize()}"
                key_sharps = int(analyzed.sharps)
            except Exception:
                key_name, key_sharps = "C Major", 0

        score = stream.Score()
        p_rh = stream.Part()
        p_lh = stream.Part()
        p_rh.insert(0, m21clef.TrebleClef())
        p_lh.insert(0, m21clef.BassClef())

        if time_signatures:
            for ts in time_signatures:
                ts_obj = meter.TimeSignature(f"{ts['numerator']}/{ts['denominator']}")
                p_rh.insert(float(ts.get("offset", 0.0)), ts_obj)
                p_lh.insert(float(ts.get("offset", 0.0)), meter.TimeSignature(f"{ts['numerator']}/{ts['denominator']}"))
        else:
            p_rh.insert(0, meter.TimeSignature('4/4'))
            p_lh.insert(0, meter.TimeSignature('4/4'))

        try:
            ks = m21key.KeySignature(key_sharps)
            p_rh.insert(0, ks)
            p_lh.insert(0, ks)
        except Exception:
            pass

        for hand_tag, part_obj in [("right", p_rh), ("left", p_lh)]:
            m_curr = stream.Measure(number=1)
            m_curr.offset = 0.0
            last_off = 0.0

            for g in groups:
                off = float(g["offset"])
                dur = float(g["duration"])
                pitches = [p for p, h in g["notes"] if h == hand_tag]

                if pitches:
                    if off > last_off:
                        r_dur = off - last_off
                        m_curr.insert(last_off, note.Rest(quarterLength=r_dur))
                    if len(pitches) == 1:
                        el = note.Note(pitch=m21pitch.Pitch(midi=pitches[0]), quarterLength=dur)
                    else:
                        m21_pitches = [m21pitch.Pitch(midi=p) for p in pitches]
                        el = chord.Chord(m21_pitches, quarterLength=dur)
                    m_curr.insert(off, el)
                    last_off = max(last_off, off + dur)

            part_obj.insert(0.0, m_curr)

        score.append(p_rh)
        score.append(p_lh)

        try:
            score = score.makeNotation()
        except Exception as e:
            print(f"Music21Service: makeNotation warning: {e}")

        return score, key_name, key_sharps

    def _score_difficulty(self, steps: list) -> int:
        # Rest-only steps are notation, not events the hands have to execute, and
        # every term below reads them as one: a 0-note chord, a step with no hands,
        # and an onset that splits one real gap into two shorter ones. Score
        # extraction is rest-dense (_build_score_from_groups fills gaps per hand
        # and makeNotation completes measures), so this is not a rounding matter.
        steps = [s for s in steps if s.get('pitches')]
        if not steps:
            return 1
        onset_diffs = []
        for i in range(1, len(steps)):
            d = steps[i]['offset'] - steps[i - 1]['offset']
            if d > 0:
                onset_diffs.append(d)
        avg_gap = (sum(onset_diffs) / len(onset_diffs)) if onset_diffs else 1.0
        events_per_beat = (1.0 / avg_gap) if avg_gap > 0 else 1.0

        chord_sizes = [len(s['pitches']) for s in steps]
        avg_chord_size = (sum(chord_sizes) / len(chord_sizes)) if chord_sizes else 1.0

        polyphonic_count = sum(1 for s in steps if len(set(s['hands'])) > 1 or len(s['pitches']) > 2)
        poly = polyphonic_count / len(steps)

        both_hands_count = sum(1 for s in steps if "right" in s['hands'] and "left" in s['hands'])
        both_hands = both_hands_count / len(steps)

        spans = []
        for s in steps:
            for h_tag in ("right", "left"):
                hp = [p for p, h in zip(s['pitches'], s['hands']) if h == h_tag]
                if len(hp) >= 2:
                    spans.append(max(hp) - min(hp))
        wide = (sum(1 for sp in spans if sp > 12) / len(spans)) if spans else 0.0

        raw = (1.0 + min(events_per_beat, 3.0) * 1.2 + (avg_chord_size - 1.0) * 0.5
               + poly * 1.5 + both_hands * 1.5 + wide * 1.5)
        return max(1, min(10, round(raw)))

    # ── The corpus browser (CorpusCatalog) ───────────────────────────

    @Property(float, notify=corpusProgressChanged)
    def corpusProgress(self):
        return self.catalog.corpusProgress

    @Property(str, notify=corpusStatusChanged)
    def corpusStatus(self):
        return self.catalog.corpusStatus

    @Property(bool, notify=corpusReady)
    def isCorpusReady(self):
        return self.catalog.isCorpusReady

    @Property(bool, notify=corpusError)
    def hasCorpusError(self):
        return self.catalog.hasCorpusError

    @Slot()
    def trigger_corpus_download(self):
        return self.catalog.trigger_corpus_download()

    @Slot(list, result="QVariantList")
    def get_catalog_level(self, path):
        return self.catalog.get_catalog_level(path)

    @Slot(result="QVariantList")
    def get_recent_songs(self):
        return self.catalog.get_recent_songs()

    def get_recent_corpus_ids(self, limit: int=5) -> list:
        return self.catalog.get_recent_corpus_ids(limit)

    @Slot(str, result="QVariantList")
    def search_catalog(self, query):
        return self.catalog.search_catalog(query)

    @Slot(str)
    def mark_song_played(self, song_id):
        return self.catalog.mark_song_played(song_id)

    @Slot(result="QVariantList")
    def get_catalog(self):
        return self.catalog.get_catalog()

    # ── The student's songs (SongLibrary) ────────────────────────────

    @Slot(str)
    def import_file(self, file_url: str):
        return self.library.import_file(file_url)

    @Slot(str)
    def import_midi_file(self, file_url: str):
        return self.library.import_midi_file(file_url)

    @Slot(str)
    def request_song_level(self, song_id: str):
        return self.library.request_song_level(song_id)

    @Slot(str, str, result=str)
    @Slot(str, str, str, result=str)
    def get_user_song_pref(self, song_id: str, key: str, default: str='') -> str:
        return self.library.get_user_song_pref(song_id, key, default)

    @Slot(str, str, str)
    def set_user_song_pref(self, song_id: str, key: str, value: str):
        return self.library.set_user_song_pref(song_id, key, value)

    @Slot(str, result=str)
    def get_user_song_hand_mode(self, song_id: str) -> str:
        return self.library.get_user_song_hand_mode(song_id)

    @Slot(str, str)
    def set_user_song_hand_mode(self, song_id: str, mode: str):
        return self.library.set_user_song_hand_mode(song_id, mode)

    @Slot(str, result="QVariantList")
    def get_user_song_notes(self, song_id: str):
        return self.library.get_user_song_notes(song_id)

    @Slot(str, result="QVariantList")
    def get_user_song_barlines(self, song_id: str):
        return self.library.get_user_song_barlines(song_id)

    @Slot(str, result="QVariantMap")
    def get_user_song_notation_context(self, song_id: str):
        return self.library.get_user_song_notation_context(song_id)

    @Slot(str, "QVariantList", result=str)
    def save_user_song_notes(self, song_id: str, notes) -> str:
        return self.library.save_user_song_notes(song_id, notes)

    @Slot(result="QVariantList")
    def get_user_songs(self):
        return self.library.get_user_songs()

    @Slot(result="QVariantList")
    def get_user_song_summaries(self):
        return self.library.get_user_song_summaries()

    @Slot(str, str, str)
    def rename_user_song(self, song_id: str, title: str, artist: str):
        return self.library.rename_user_song(song_id, title, artist)

    @Slot(str, result=str)
    def delete_user_song(self, song_id: str) -> str:
        return self.library.delete_user_song(song_id)

    @Slot(result="QVariantList")
    def find_duplicates(self):
        return self.library.find_duplicates()
