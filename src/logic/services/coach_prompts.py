"""
What the app asks the coach to say during a lesson.

The coach no longer chooses exercises (see lesson_sequencer), so every prompt
here asks for speech only. The app prompts at a few moments — the lesson's
first exercise, an exercise type the student meets for the first time or
returns to, a struggle streak, a concept card, and the end of the lesson —
and stays quiet between repetitions of the same kind of drill.

Each function returns the full text to send, wrapped in the directive marker
the coach's system instruction treats as not-to-be-read-aloud.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

_HANDS = {"right": "right hand", "left": "left hand", "both": "both hands"}
_SPEECH_ONLY = ("Speak only to the student. Do not call any tools. "
                "Do not read out numbers such as BPM or milliseconds.")


def _directive(body: str) -> str:
    return f"<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>\n{body.strip()}\n{_SPEECH_ONLY}\n</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>"


def describe(ex: Dict[str, Any]) -> str:
    """A plain-language description of an exercise, for the coach's benefit."""
    t = ex.get("exercise_type", "chord")
    name = ex.get("exercise_name", "the exercise")
    hand = _HANDS.get(ex.get("hand", "right"), "right hand")
    if t == "chord":
        return f"playing {name} with the {hand}"
    if t == "hands_together":
        return f"{name}: the right hand plays the chord while the left hand plays its root in the bass"
    if t == "sustain_pedal":
        how = ("press the pedal together with the chord"
               if ex.get("pedal_type", "direct") == "direct"
               else "play the chord first, then press the pedal (legato pedaling)")
        return f"a sustain-pedal drill on {name.split(' — ')[0]}: {how}"
    if t == "pentascale":
        return f"the {name} with the {hand}, one note at a time"
    if t == "progression":
        return f"the chord progression {name}, one chord after another"
    if t == "listen":
        return "an ear-training drill: the app plays a chord and the student says whether it is major or minor"
    if t == "song_application":
        return f"playing the piece \"{name}\" at their own pace"
    if t == "theory_concept":
        return f"the idea \"{name}\": {ex.get('concept_body', '')}"
    return name


def lesson_intro(first: Dict[str, Any], block_titles: Iterable[str],
                 student_context: str = "") -> str:
    blocks = ", ".join(t for t in block_titles if t) or "a few short drills"
    context = f"\n\nWhat you know about the student:\n{student_context.strip()}" if student_context else ""
    return _directive(
        f"A new lesson is starting. Today covers: {blocks}.{context}\n\n"
        f"Welcome the student in one sentence, give a one-sentence overview of today, "
        f"then explain how to do the first exercise: {describe(first)}. "
        f"Keep it under five sentences."
    )


def exercise_intro(ex: Dict[str, Any], first_time_ever: bool,
                   milestone_description: str = "", note: str = "") -> str:
    lead = f"{note.strip()} " if note else ""
    why = f" Background: {milestone_description}" if milestone_description else ""
    if first_time_ever:
        body = (f"{lead}The student is about to try a kind of exercise they have never done: "
                f"{describe(ex)}.{why} Explain what it is, why it matters musically, and how "
                f"to do it. Use the length your brevity setting calls for when introducing "
                f"something new.")
    else:
        body = (f"{lead}The next exercise is {describe(ex)}. Introduce it in one short sentence.")
    return _directive(body)


def struggle_tip(ex: Dict[str, Any], note: str = "") -> str:
    lead = f"{note.strip()} " if note else ""
    return _directive(
        f"{lead}The student has struggled with the last few attempts at {describe(ex)}. "
        f"They are about to try again. Give one specific, practical tip in one or two "
        f"sentences, kindly."
    )


def concept(ex: Dict[str, Any]) -> str:
    return _directive(
        f"Explain this idea to the student, out loud, in three to five sentences, tied to "
        f"what their hands do on the keyboard: \"{ex.get('exercise_name', '')}\" — "
        f"{ex.get('concept_body', '')} The card is on their screen; they will press "
        f"Continue when ready."
    )


def note_song_finished(title: str) -> str:
    return f"The student just played all the way through \"{title}\". Acknowledge it in one sentence first."


def lesson_summary(exercises_done: int, struggled: Iterable[str],
                   block_titles: Iterable[str], note: str = "") -> str:
    hard = sorted(set(s for s in struggled if s))
    hard_text = f" They found these harder: {', '.join(hard)}." if hard else " They did not struggle with anything in particular."
    covered = ", ".join(t for t in block_titles if t) or "today's material"
    lead = f"{note.strip()} " if note else ""
    return _directive(
        f"{lead}The lesson is over. The student completed {exercises_done} exercises covering "
        f"{covered}.{hard_text} "
        f"Close the lesson in two or three sentences: one honest observation, one thing to "
        f"practise next time, and a goodbye."
    )


def choose_intro(ex: Dict[str, Any], *, first_in_lesson: bool, previous_type: Optional[str],
                 seen_types: Iterable[str], struggle_streak: int, tip_given: bool,
                 block_titles: Iterable[str], student_context: str = "",
                 milestone_description: str = "", note: str = "") -> Optional[str]:
    """
    The prompt to send before presenting `ex`, or None to stay quiet. Same-type
    repetitions are silent unless the student is struggling or something (a
    finished song) needs acknowledging.
    """
    ex_type = ex.get("exercise_type", "chord")
    if ex_type == "theory_concept":
        return concept(ex)
    if first_in_lesson:
        return lesson_intro(ex, block_titles, student_context)
    if ex_type != previous_type:
        return exercise_intro(ex, ex_type not in set(seen_types), milestone_description, note)
    if struggle_streak >= 2 and not tip_given:
        return struggle_tip(ex, note)
    if note:
        return _directive(note)
    return None
