"""
The two scripted lessons that drive the Circle of Fifths view.

- CircleTutorial: a seven-step introduction to the wheel. Each step pushes a
  visual, is narrated by the coach, and waits for Continue; the last step
  ends the lesson once narrated.
- DominantMotionDrill: six V→I resolutions. The app plays the V chord, the
  student plays its I; a wrong answer gets a hint (the I chord played, the
  shared note named) once the keys are released.

Both run without a coach: narration is skipped, nothing waits for it.

They belong to a ChordTrainerService and work through it — its target, its
MIDI and visual signals, its coach — so the trainer keeps the QML-facing
surface (continueCircleTutorial, isWaitingForUserContinue,
isCircleOfFifthsMode) and delegates here.
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import TYPE_CHECKING, List

from PySide6.QtCore import QTimer  # type: ignore

from logic.services import coach_prompts  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    from logic.services.chord_trainer import ChordTrainerService


def _stamp() -> str:
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]


class CircleTutorial:
    """The seven-step Circle of Fifths introduction."""

    LAST_STEP = 7

    # What the wheel shows at each step (pushed from Python, never the coach).
    STEP_VISUALS = {
        1: {"show_base": True, "show_major": False, "show_minor": False, "highlight_key": "", "revealed_keys": []},
        2: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "C", "revealed_keys": ["C"]},
        3: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "G", "revealed_keys": ["C", "G"]},
        4: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "D", "revealed_keys": ["C", "G", "D"]},
        5: {"show_base": True, "show_major": True, "show_minor": False, "highlight_key": "F", "revealed_keys": ["C", "G", "D", "F"]},
        6: {"show_base": True, "show_major": True, "show_minor": True, "highlight_key": "Am", "revealed_keys": ["C", "G", "D", "F", "Am"]},
        7: {"show_base": True, "show_major": True, "show_minor": True, "highlight_key": "", "revealed_keys": ["ALL"]},
    }

    # What the coach reads at each step.
    STEP_SCRIPTS = {
        1: "Welcome to the Circle of Fifths. This wheel maps out the relationship between every key in western music. Let's build it up together, one piece at a time.",
        2: "C Major is at the very top. It has no sharps and no flats, making it the simplest key on the piano—just the white keys.",
        3: "G Major is one step clockwise. Moving right takes us up a perfect fifth, and adds exactly one sharp to the key signature.",
        4: "D Major is the next step clockwise. Following the pattern, it goes up another perfect fifth and has exactly two sharps.",
        5: "F Major is one step counter-clockwise from C. Moving left takes us down a fifth, and adds one flat instead of a sharp.",
        6: "A Minor is hiding on the inner ring. Every major key has a relative minor that shares the exact same notes. They are simply two sides of the same coin.",
        7: "That completes our first look at the Circle of Fifths. Sharps accumulate clockwise, flats accumulate counter-clockwise, and every major key has a hidden relative minor. Great job today!",
    }

    # The chord played as each step's wheel finishes turning.
    STEP_CHORDS = {
        2: [60, 64, 67],  # C Major
        3: [67, 71, 74],  # G Major
        4: [62, 66, 69],  # D Major
        5: [65, 69, 72],  # F Major
        6: [69, 72, 76],  # A Minor (relative minor of C)
    }

    # Delay before the step's chord, so it sounds as the wheel finishes spinning.
    CHORD_DELAY_MS = 1000

    def __init__(self, trainer: "ChordTrainerService"):
        self._t = trainer
        self.step = 0  # 1..7 while running, 8 once finished, 0 before
        self.waiting_for_continue = False

    def reset(self):
        self.step = 0
        self._set_waiting(False)

    def start(self):
        t = self._t
        t._reset_for_lesson()
        t._set_circle_mode(True)
        self.step = 1
        t._set_state(t.State.USER_PLAYING)
        t.lessonStateChanged.emit()
        self._narrate(self.prompt())

    def prompt(self) -> str:
        """Pushes the current step's visual and returns its narration prompt ('' if none)."""
        if self.step not in self.STEP_VISUALS:
            return ""
        self._t.theoryVisualDirect.emit(self.STEP_VISUALS[self.step])
        return coach_prompts.verbatim(self.STEP_SCRIPTS[self.step])

    def on_speech_finished(self):
        if self.step == self.LAST_STEP:
            # The last step just finished — end directly, no Continue button.
            print(f"[TIMING {_stamp()}] CircleTutorial: complete (step 7 narrated). Finalizing lesson.")
            self._finish()
        elif 0 < self.step < self.LAST_STEP:
            print(f"[TIMING {_stamp()}] CircleTutorial: paused at step {self.step}. Waiting for Continue.")
            self._set_waiting(True)

    def advance(self):
        """The student pressed Continue."""
        if not self.waiting_for_continue:
            return
        self._set_waiting(False)
        if not 0 < self.step <= self.LAST_STEP:
            return
        if self.step == self.LAST_STEP:
            print(f"[TIMING {_stamp()}] CircleTutorial: complete. Finalizing lesson.")
            self._finish()
            return

        self.step += 1
        print(f"[TIMING {_stamp()}] CircleTutorial: advancing to step {self.step}")
        self._narrate(self.prompt())
        step = self.step
        QTimer.singleShot(self.CHORD_DELAY_MS, lambda: self._play_step_chord(step))

    def _narrate(self, prompt: str):
        # Continue appears when the narration ends — at once if there is no coach.
        if not self._t._coach_say(prompt):
            self._t.resume_lesson()

    def _play_step_chord(self, step: int):
        pitches = self.STEP_CHORDS.get(step)
        if pitches:
            print(f"CircleTutorial: Playing step {step} chord {pitches}")
            self._t.midiOutRequested.emit(list(pitches))

    def _finish(self):
        self._t._set_circle_mode(False)
        self._t._conclude_lesson()
        self.step = self.LAST_STEP + 1

    def _set_waiting(self, waiting: bool):
        if waiting != self.waiting_for_continue:
            self.waiting_for_continue = waiting
            self._t.waitingForUserContinueChanged.emit(waiting)


class DominantMotionDrill:
    """Six V→I resolutions around the circle."""

    # (V key, I key, V root, I root, the note they share: the 5th of I = root of V)
    PAIRS = [
        {"v_key": "G", "i_key": "C", "v_root": 7,  "i_root": 0,  "shared": "G"},
        {"v_key": "D", "i_key": "G", "v_root": 2,  "i_root": 7,  "shared": "D"},
        {"v_key": "A", "i_key": "D", "v_root": 9,  "i_root": 2,  "shared": "A"},
        {"v_key": "C", "i_key": "F", "v_root": 0,  "i_root": 5,  "shared": "C"},
        {"v_key": "E", "i_key": "A", "v_root": 4,  "i_root": 9,  "shared": "E"},
        {"v_key": "B", "i_key": "E", "v_root": 11, "i_root": 4,  "shared": "B"},
    ]

    # Pause between a resolution and the next V chord.
    NEXT_PAIR_DELAY_MS = 700
    # A wrong answer is flagged this quickly (any number of keys).
    WRONG_CHORD_MS = 100

    PROMPTS_BETWEEN_PAIRS = [
        "Now resolve {v} Major.",
        "{v} Major. Where does it want to go?",
        "Here's {v}. Find the resolution.",
        "{v} to... you tell me.",
        "Resolve {v}.",
    ]

    def __init__(self, trainer: "ChordTrainerService"):
        self._t = trainer
        self.reset()

    def reset(self):
        self.active = False
        self.step = 0
        self.hint_sent = False
        self.needs_hint = False
        self.wrong_pitches: List[int] = []
        self.complete = False

    def start(self):
        t = self._t
        t._reset_for_lesson()
        t._set_circle_mode(True)
        self.reset()
        self.active = True
        t._set_state(t.State.USER_PLAYING)
        t.lessonStateChanged.emit()
        prompt = self._present_pair(intro=True)
        if not t._coach_say(prompt):
            t.resume_lesson()

    def on_speech_finished(self):
        print(f"[TIMING {_stamp()}] DominantMotion: speech finished, awaiting input.")
        self._t._set_state(self._t.State.USER_PLAYING)
        self._t.lessonStateChanged.emit()

    def on_wrong_chord(self, pitches: List[int]):
        """A wrong resolution: hint once the keys are up (first mistake per pair only)."""
        if self.hint_sent:
            return
        self.needs_hint = True
        self.wrong_pitches = list(pitches)
        self._t._waiting_for_release = True

    def on_chord_complete(self):
        """The I chord was played: wait for release, then the next pair (or the end)."""
        self.step += 1
        if self.step >= len(self.PAIRS):
            print(f"[TIMING {_stamp()}] DominantMotion: all pairs resolved. Waiting for release.")
            self.complete = True
        self._t._waiting_for_release = True

    def on_keys_released(self):
        t = self._t
        if self.complete:
            self.reset()
            t._set_circle_mode(False)
            t._conclude_lesson()
        elif self.needs_hint:
            self.needs_hint = False
            self._hint(self.wrong_pitches)
        else:
            QTimer.singleShot(self.NEXT_PAIR_DELAY_MS, self._next_pair)

    def _next_pair(self):
        self._t._waiting_for_release = False
        self._t.speakBrief.emit(self._present_pair())

    def _present_pair(self, intro: bool = False) -> str:
        """Sets up the current pair (visual, I-chord target, V chord played) and returns its prompt."""
        t = self._t
        pair = self.PAIRS[self.step]
        v_key, i_key = pair["v_key"], pair["i_key"]
        print(f"DominantMotion: step {self.step + 1}/{len(self.PAIRS)}: {v_key}→{i_key}")
        self.hint_sent = False

        t.theoryVisualDirect.emit({
            "show_base": True,
            "show_major": True,
            "show_minor": False,
            "highlight_key": v_key,
            "revealed_keys": ["ALL"],
            "highlighted_chords": [v_key],
            "arrows": [{"from": v_key, "to": i_key, "color": "#4CAF50"}],
        })

        t._lesson_progress = self.step + 1
        t._lesson_total = len(self.PAIRS)

        t._exercise_type = "chord"
        t._exercise_name = f"Resolve {v_key} → {i_key}"
        t._current_hand = "right"
        t._required_hold_ms = 0
        t._current_inversion = 0
        t._setup_target(pair["i_root"], "Major", {0, 4, 7}, 4)

        # The V chord, so the student hears the tension they are resolving.
        v_root = 60 + pair["v_root"]
        t.midiOutRequested.emit([v_root, v_root + 4, v_root + 7])

        if not intro:
            return coach_prompts.verbatim(random.choice(self.PROMPTS_BETWEEN_PAIRS).format(v=v_key))

        t.db.record_dominant_motion_play()
        play_count = t.db.get_dominant_motion_play_count()
        attempts = successes = 0
        if t.curriculum:
            for ms in t.db.get_curriculum_state("theory"):
                if ms["milestone_id"] == "dominant_motion":
                    attempts = ms.get("attempts", 0)
                    successes = ms.get("successes", 0)
                    break
        return coach_prompts.dominant_motion_intro(play_count, successes, attempts, v_key)

    def _hint(self, wrong_pitches: List[int]):
        """Highlights the answer, plays the I chord, and has the coach explain."""
        if self.hint_sent:
            return
        self.hint_sent = True
        t = self._t
        pair = self.PAIRS[self.step]
        v_key, i_key, shared = pair["v_key"], pair["i_key"], pair["shared"]
        print(f"DominantMotion: hint — shared note {shared} between {v_key} and {i_key}")

        t.theoryVisualDirect.emit({
            "show_base": True,
            "show_major": True,
            "show_minor": False,
            "highlight_key": i_key,
            "revealed_keys": ["ALL"],
            "highlighted_chords": [v_key, i_key],
            "arrows": [{"from": v_key, "to": i_key, "color": "#4CAF50"}],
        })

        i_root = 60 + pair["i_root"]
        t.midiOutRequested.emit([i_root, i_root + 4, i_root + 7])

        if wrong_pitches:
            played = [t.ROOT_NOTES[p % 12] for p in wrong_pitches]
            prompt = coach_prompts.dominant_motion_mistake(v_key, i_key, played, shared)
        else:
            prompt = coach_prompts.verbatim(
                f"The answer is {i_key} Major. {shared} is the note they share. Try playing {i_key} Major now.")
        t.speakBrief.emit(prompt)
