# Security tests for ui_html.py: anything a visitor pastes (or the model
# repeats back) must show up as plain text, never run as HTML or a script.

from ui_html import reply_card_html

ATTACK = '<script>alert("hacked")</script><img src=x onerror="alert(1)">'


def test_pasted_html_is_shown_as_text_not_run():
    entry = {
        "reply": ATTACK,
        "explanation": ATTACK,
        "draft": ATTACK,
        "context": ATTACK,
        "what_changed": ATTACK,
        "what_changed_label": ATTACK,
    }
    card = reply_card_html(ATTACK, entry)
    # The dangerous tags must not survive in working form anywhere...
    assert "<script>" not in card
    assert "<img" not in card
    # ...but the text itself is still shown, safely escaped.
    assert "&lt;script&gt;" in card


def test_clarifying_question_has_no_explanation_box():
    entry = {"reply": "What did they say?", "explanation": "", "is_clarification": True}
    assert "Why this works" not in reply_card_html("Reply", entry)
