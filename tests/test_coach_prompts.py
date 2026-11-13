"""When the app asks the coach to speak during a lesson, and what it asks for."""
from logic.services import coach_prompts as cp

CHORD = {"exercise_type": "chord", "exercise_name": "C Major", "hand": "right"}
PENTA = {"exercise_type": "pentascale", "exercise_name": "C Major Pentascale (ascending)", "hand": "right"}
CARD = {"exercise_type": "theory_concept", "exercise_name": "Major Formula",
        "concept_body": "Stack 4 half steps, then 3."}


def intro(ex, **kw):
    args = dict(first_in_lesson=False, previous_type="chord", seen_types={"chord", "pentascale"},
                struggle_streak=0, tip_given=False, block_titles=["Major Triads"])
    args.update(kw)
    return cp.choose_intro(ex, **args)


def test_every_prompt_is_a_speech_only_directive():
    for prompt in (cp.lesson_intro(CHORD, ["Major Triads"]), cp.exercise_intro(PENTA, True),
                   cp.struggle_tip(CHORD), cp.concept(CARD), cp.lesson_summary(5, [], ["x"])):
        assert prompt.startswith("<SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>")
        assert prompt.rstrip().endswith("</SYSTEM_DIRECTIVE_DO_NOT_SPEAK_THIS>")
        assert "Do not call any tools" in prompt


def test_the_first_exercise_gets_a_welcome():
    prompt = intro(CHORD, first_in_lesson=True, previous_type=None, student_context="Likes Bach.")
    assert "new lesson" in prompt and "Major Triads" in prompt and "Likes Bach." in prompt


def test_same_type_repetitions_are_silent():
    assert intro(CHORD) is None


def test_a_change_of_type_gets_one_sentence():
    prompt = intro(PENTA)
    assert "one short sentence" in prompt


def test_a_type_never_seen_before_gets_a_full_explanation():
    prompt = intro(PENTA, seen_types={"chord"}, milestone_description="Five fingers, five notes.")
    assert "never done" in prompt and "Five fingers, five notes." in prompt


def test_a_struggle_streak_gets_one_tip():
    assert "struggled" in intro(CHORD, struggle_streak=2)
    assert intro(CHORD, struggle_streak=2, tip_given=True) is None


def test_concept_cards_are_always_explained():
    assert "Stack 4 half steps" in intro(CARD, previous_type="theory_concept")


def test_a_note_rides_on_the_next_prompt_even_when_it_would_be_silent():
    note = cp.note_song_finished("Ode to Joy")
    assert "Ode to Joy" in intro(PENTA, note=note)
    assert "Ode to Joy" in intro(CHORD, note=note)


def test_summary_lists_what_was_hard():
    prompt = cp.lesson_summary(12, ["F Major", "F Major", "G Major"], ["Major Triads"])
    assert "12 exercises" in prompt and "F Major, G Major" in prompt
