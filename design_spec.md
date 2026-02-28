# ChordCoach Companion — Design Specification

## 1. Executive Summary

ChordCoach Companion is an AI-driven, cross-platform desktop application designed to accelerate piano proficiency for **advanced beginner to advanced intermediate** adult learners. It combines interval-based music theory (half-step formulas), spatial keyboard awareness, and an Enhanced Visual Notation system — featuring color-coded fingering and physical duration blocks — to lower the barrier to playing popular music.

The core experience is a **Curriculum Engine** that manages long-term progress across four learning tracks (Technique, Theory, Repertoire, Ear/Listen), powered by the Gemini Multimodal Live API for real-time coaching and adaptive lesson generation. The **music21** library provides the analytical backbone — key detection, Roman numeral analysis, difficulty scoring, and transposition — enabling intelligent, offline music theory processing.

**Pedagogical philosophy:** An adult who plays 4 chords in rhythm with both hands and understands *why* they sound good is a more successful student than one who can name 20 chords but can't play them in time. Focus on musicianship, not just correctness.

## 2. Technical Architecture & Stack

The application utilizes a high-performance hybrid architecture to ensure zero-latency MIDI processing while maintaining a modern, reactive user interface.

**Hardware Layer (C++17):**
- MIDI I/O: RtMidi for low-latency communication with USB MIDI controllers (e.g., Roland FP-30X).
- Audio I/O: PortAudio for microphone capture (supporting acoustic pianos) and AI voice feedback.
- IPC: pybind11 to expose high-frequency hardware telemetry to the Python logic layer.

**Logic & AI Layer (Python 3.10+):**
- State Management: PySide6 (Qt for Python) handling application flow and local data.
- AI Engine: google-genai (Gemini Multimodal Live API) via a persistent WebSocket for real-time coaching and session generation.
- MIDI Logic: mido and pretty_midi for parsing and manipulating MIDI data.
- Music Theory Engine: music21 (lazy-loaded) for key detection, Roman numeral analysis, difficulty scoring, transposition, scale/chord analysis, and access to the built-in musical corpus.

**Presentation Layer (QML / Qt Quick):**
- UI Rendering: Hardware-accelerated QML for 60fps scrolling notation.
- Web Integration: QtWebEngine for embedded YouTube playback.
- Interactive Visualizations: QML Canvas for the Circle of Fifths widget and theory visuals.

## 3. Data Sourcing: The Automated Repertoire Engine

To eliminate manual file management, the application features an automated crawler and parser for song ingestion.

- **MIDI Crawling:** A background service crawls bitmidi.com and similar repositories, indexing songs by genre, popularity, and complexity.
- **Intelligent Curation:** The AI Coach identifies "Dream Songs" from the user's preferences and automatically retrieves the most accurate MIDI versions from the crawled database.
- **Difficulty Analysis (music21):** Feature extraction auto-scores every song 1-10 using melodic interval size, rhythmic complexity, harmonic density, and hand span requirements — no AI call needed.
- **Key Detection (music21):** `stream.analyze('key')` detects the key and confidence score for every ingested file.
- **Smart Segment Extraction (music21):** Parse scores into phrases, identify the hardest 4-bar section by interval jumps, chord density, and tempo changes. Auto-loop the user's weakest section.
- **MusicXML Import (music21):** Read MusicXML files from MuseScore and other sources — measures, dynamics, articulations, lyrics, fingerings, and time signatures. The user chooses their notation style (enhanced blocks vs. standard sheet music), with lessons that help transition from one to the other.

**Notation Parsing:**
- The MidiIngestor class filters MIDI streams for piano-specific tracks.
- It automatically assigns colors to notes based on hand-span and pitch proximity.
- It translates MIDI timestamps into proprietary duration-based visual blocks.

## 4. The Studio Console (User Interface)

The UI follows a modular "Studio Console" design focused on clarity and peripheral awareness.

- **Left Sidebar (The Adaptive Plan):** A persistent view of the current session's roadmap, showing completed and upcoming phases. Includes the interactive Circle of Fifths widget as a passive learning aid.
- **Center Workspace (The Media Center):** A dual-purpose area that hosts the embedded YouTube player for lessons and the horizontal Enhanced Timeline for playing.
- **Bottom Dock (Telemetry Zone):**
  - Visual Keyboard: A 2D piano reflecting every key pressed in real-time.
  - Coach Feedback: A glowing waveform and text transcript area for the Gemini AI.
  - Status: Connection indicators for MIDI hardware and cloud sync.

## 5. Curriculum Engine — Multi-Track Learning System

### Architecture

The Curriculum Engine replaces monolithic per-session lesson generation with a structured, multi-session learning system.

```
┌─────────────────────────────────────────────────┐
│  CURRICULUM PLANNER (long-term, weeks/months)   │
│                                                 │
│  Four Tracks, Each with Ordered Milestones:     │
│  ┌───────────┐ ┌───────────┐                    │
│  │ Technique │ │ Theory    │                    │
│  └───────────┘ └───────────┘                    │
│  ┌───────────┐ ┌───────────┐                    │
│  │ Repertoire│ │ Ear/Listen│                    │
│  └───────────┘ └───────────┘                    │
│                                                 │
│  Spaced Repetition (SM-2) for chords, keys,     │
│  theory concepts, and songs.                    │
│  Session History tracks what was covered.        │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│  SESSION PLANNER (per session, 5-10 minutes)    │
│                                                 │
│  Inputs: curriculum state, skill matrix,        │
│  review queue, Dream Song goals, available time │
│                                                 │
│  Output: balanced session mixing 2-3 tracks,    │
│  theory woven into technique, song context      │
└─────────────────────────────────────────────────┘
```

### Curriculum Tracks

**Technique Track** — ordered milestones:
1. Right-hand C pentascale → Major triads (C, F, G) → Minor triads (Am, Dm, Em)
2. Chord transitions with common-tone pivots → Inversions (root, 1st, 2nd)
3. Left-hand bass notes (single pitches, octave 2-3) → Hands-together basics
4. Walking bass lines → Full two-hand coordination
5. Sustain pedal: direct pedaling → legato (syncopated) pedaling → half pedaling
6. Extended chords: dominant 7th, major 7th, minor 7th

**Theory Track** — ordered milestones:
1. Half steps and the major/minor chord formula (4+3, 3+4)
2. Roman numerals (I, IV, V) — taught experientially, not as flash cards
3. Circle of Fifths: Key Explorer and Progression Navigator lessons
4. Nashville Number System alongside Roman numerals
5. Minor key progressions, secondary dominants, modulation

**Repertoire Track** — dynamically linked to Dream Songs:
1. First song application (I-V-VI-IV) with backing track
2. Song Breakdown lessons: analyze progression → drill transitions → play along
3. Verse/chorus/bridge structure awareness
4. Dream Song preparation: key-matched exercises, targeted transitions

**Ear/Listen Track** — progressive listening skills:
1. "Hear it first" chord previews (play target via MIDI before drills)
2. Major vs. minor recognition
3. Chord quality identification (diminished, 7th)
4. Root identification by ear
5. Scale-degree recognition (future)

### Key Principles

1. **Every session touches at least 2 tracks.** Mix technique with theory nuggets, listening moments, or song excerpts.
2. **Theory is never standalone.** Teach *inside* the practice: "We're about to drill V→I. Here's WHY this sounds so satisfying…"
3. **Spaced repetition for everything.** Chords, songs, theory concepts, key signatures. If the user hasn't played in F major for 2 weeks, insert an F major warmup.
4. **Dream Song as the North Star.** Every lesson moves the user closer: "Your Dream Song 'Let It Be' uses C-G-Am-F. Today's transitions are getting you ready."
5. **Focused AI calls.** Instead of one giant prompt for 80-150 steps, generate exercises per curriculum block (20-30 steps). Multiple smaller calls per session.

### Enhanced Skill Matrix

The skill matrix tracks more than chord accuracy:
- Rhythm accuracy (on-beat vs. late/early)
- Left-hand independence level
- Key familiarity (which keys has the user practiced in?)
- Transition speed between specific chord pairs
- Pedal timing accuracy (release/press alignment with chord changes) and blur detection
- Sight-reading fluency (future)

## 6. Exercise Types

### Existing Types (Enhanced)

- **Pentascale Warmup:** Ascending AND descending. Add contrary motion (both hands in opposite directions), skip patterns (C-E-G-E-C), and varied rhythms (quarter notes → eighth notes → dotted).
- **Isolated Chord Drills:** Include inversions early (root → 1st → 2nd inversion). AI coach explains *why* each chord exists ("This V chord creates tension that resolves to I…").
- **Transition Bridge:** Common-tone pivot coaching ("Keep fingers 2 and 3 down, only your thumb moves"). Pairs and triplets of related chords.
- **Chord Progression:** Roman numerals AND Nashville numbers. Include minor key progressions (Am-F-C-G). Transposition engine (music21) practices the same shape in all 12 keys.
- **Rhythmic Locking:** Hold chords against a metronome or drum loop, not in silence. Vary durations within a progression for phrasing, not just stamina.

### New Exercise Types

- **Hands-Together Coordination:** Right hand plays chord, left hand plays bass note. Start with whole notes → half notes → walking bass. Highest-priority new type.
- **Steady-Pulse Drills:** Metronome at target BPM. Play chord ON the beat. Rhythm pattern drills. Gradual tempo increases.
- **"Hear It First" Previews:** Play target chord through MIDI output before the drill. Cheapest ear training win.
- **Song Application Phase:** After learning a progression, play it over a backing track or simplified arrangement.
- **"Theory in Context" Mini-Lessons:** 2-minute interactive explainers woven into technique drills.
- **Sustain Pedal Drills:** Three progressive techniques: (1) "Clean Hold" — direct pedaling, press with the chord, release before the next; (2) "Smooth Switch" — legato pedaling, foot follows hands (play new chord → lift pedal → re-press), validated within a ~300ms window; (3) "Pedal + Progression" — full I-V-VI-IV with legato pedaling, scored for blur vs. clean transitions. Requires MIDI CC64 input capture from the Roland FP-30X. A "sustain lane" visualization below the notation shows when the pedal should be down. Over-pedaling detection warns when the pedal stays down across chord changes.
- **Sight-Reading Sprint (future):** Short 4-8 bar excerpts, timed reading, depends on MusicXML support.

## 7. Circle of Fifths — Interactive Learning Device

A QML Canvas-rendered, rotatable wheel driven by music21 data (`key.Key`, `roman.RomanNumeral`, scale pitches).

**UX Features:**
- Dynamic tonic centering (selected key at 12 o'clock)
- Live MIDI pulse (played notes glow on matching segment in real-time)
- Color-coding: green = diatonic, yellow = borrowed, red = chromatic

**Lesson Type A — "Key Explorer":** Navigate the circle clockwise, adding sharps. Play scales, see diatonic chords light up, understand shared notes between adjacent keys.

**Lesson Type B — "Progression Navigator":** See I-V-VI-IV as arcs on the circle. II-V-I stencil overlay draggable to any key. Drag-to-transpose a learned progression and see new chord names + fingerings.

**Gamified Modes:** "Around the World" (timed I-IV-V-I in every key), Key Signature Flash (recognition speed), Relative Minor Finder (inner/outer ring connection).

**Persistent Sidebar Widget:** During any exercise or song playback, the circle animates harmonic motion in real-time.

## 8. AI-Driven Session Flow

### Phase 1: Performance Evaluation (Onboarding)
- If no data exists, the app initiates a skill evaluation using recognizable melodies (Twinkle Twinkle → Für Elise) at increasing difficulty.
- The app monitors latency and polyphonic accuracy, identifying the "Break Point" where accuracy falls below 80%.
- Results populate the local SQLite skill matrix and set the starting milestone for each curriculum track.

### Phase 2: Targeted Micro-Lesson (YouTube)
- Based on bottlenecks, the AI curates a YouTube video addressing the specific technique.
- Gemini explains the choice in context.

### Phase 3: Tailored Lesson Session
- The Curriculum Engine selects from 2-3 active tracks plus spaced repetition items.
- AI generates focused exercise blocks (20-30 steps each) for each curriculum block.
- Exercise phases within each block: warmup → isolated skills → transitions → musical context → endurance.

### Phase 4: Repertoire Application
- The session concludes by applying the day's skills to a song from the Dream Songs list.
- The AI selectively highlights the chords or intervals practiced, providing verbal encouragement and real-time corrections.
- music21 provides harmonic reduction (`chordify()`) to show the chord skeleton before the full arrangement.

## 9. Continuous Mastery Tracking

- **Spaced Repetition (SM-2):** All items — chords, keys, concepts, songs — are scheduled for review. If the user masters a chord but doesn't play it for seven days, the AI inserts a warmup.
- **Session History:** What tracks were covered, milestones worked, exercises completed, time spent, accuracy. Ensures no two sessions feel identical.
- **Skill Decay Model:** Mastery scores decay for items not practiced recently (48h threshold, 0.95 decay rate), automatically surfacing them for review.

## 10. music21 Integration Notes

- **Lazy-loaded** via `importlib` to avoid 1-2s startup penalty (~40MB package).
- **Coexists** with `pretty_midi`/`mido`; gradual migration path available.
- **Fast enough for real-time:** Chord analysis ~1ms per call, suitable for live MIDI.
- **Roman numeral analysis** replaces Gemini dependency for harmonic labeling.
- **Transposition engine** enables "practice in all 12 keys" without AI regeneration.
- **Built-in corpus** (Bach chorales, folk songs) provides real musical material for lesson content.
- **Future:** Voice leading analysis, improvisation analysis, ear training exercises.