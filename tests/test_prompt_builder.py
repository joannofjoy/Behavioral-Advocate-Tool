# Tests for prompt_builder.py: checks that the right pieces of guidance end
# up in the reply prompt for each mode, and for a comment flagged as not
# worth a full persuasive reply. These are plain string checks - no model
# calls - so they run instantly and for free.

from prompt_builder import (
    LOW_ENGAGEMENT_MODE_BLOCK,
    MODE_FAMILY,
    MODE_ONLINE,
    MODE_STREET,
    build_reply_prompt,
    format_strategies,
)

STRATEGY = {
    "title": "Validate Before Redirecting",
    "source": "CEVA",
    "description": "Acknowledge their feeling first.",
}


def test_format_strategies_includes_source():
    assert format_strategies([STRATEGY]) == (
        "- Validate Before Redirecting (source: CEVA): Acknowledge their feeling first."
    )


def test_format_strategies_empty():
    assert format_strategies([]) == "No strategies matched."


def test_online_mode_has_no_extra_guidance():
    prompt = build_reply_prompt([STRATEGY], mode=MODE_ONLINE)
    assert "street outreach" not in prompt.lower()
    assert "Delivery tip:" not in prompt
    assert "Validate Before Redirecting (source: CEVA)" in prompt


def test_street_mode_adds_guidance_and_delivery_tip_at_the_end():
    prompt = build_reply_prompt([STRATEGY], mode=MODE_STREET)
    assert prompt.startswith("You are helping an activist prepare for in-person street outreach")
    # The delivery-tip rule has to come last, or the model tends to ignore it.
    assert prompt.rstrip().endswith("let the other person think).")


def test_family_mode_adds_relationship_guidance():
    prompt = build_reply_prompt([STRATEGY], mode=MODE_FAMILY)
    assert prompt.startswith("You are helping reply to someone the user actually knows well")


def test_flagged_comment_puts_low_engagement_block_first():
    prompt = build_reply_prompt([STRATEGY], mode=MODE_STREET, worth_engaging=False)
    assert prompt.startswith(LOW_ENGAGEMENT_MODE_BLOCK)


def test_feedback_is_added_to_the_strategy_matching_text():
    from prompt_builder import text_for_strategy_matching

    assert text_for_strategy_matching("Vegans are weak.") == "Vegans are weak."
    text = text_for_strategy_matching("Vegans are weak.", "say you can be strong on plants")
    assert "Vegans are weak." in text and "say you can be strong on plants" in text
