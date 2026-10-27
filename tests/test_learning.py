from studyagent.learning import update_mastery, choose_mode


def test_mastery_unknown_and_repeated_success():
    first = update_mastery(None, True, "")
    assert first["attempts"] == 1 and first["score"] == 0.6 and first["streak"] == 1
    second = update_mastery(first, True, "")
    assert second["score"] >= 0.8 and second["streak"] == 2


def test_wrong_answer_switches_to_example_and_preserves_error():
    state = update_mastery(None, False, "confused value with advantage")
    assert state["score"] == 0.2 and state["attempts"] == 1 and state["errors"]
    assert choose_mode(state, False) == "example"
    assert choose_mode(None, None) == "explanation"

def test_quiz_rejects_duplicate_or_empty_options():
    import pytest
    from pydantic import ValidationError
    from studyagent.schemas import Teaching
    base = dict(explanation='lesson',question='question',correct_index=1,rubric='rule',answer_explanation='reason')
    with pytest.raises(ValidationError):
        Teaching(**base,options=['same','same','third','fourth'])
    with pytest.raises(ValidationError):
        Teaching(**base,options=['','second','third','fourth'])
