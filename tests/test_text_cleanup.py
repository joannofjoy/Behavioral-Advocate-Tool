# Tests for text_cleanup.py: em dashes become commas, but ordinary hyphens
# and number ranges stay as they are.

from text_cleanup import remove_em_dashes


def test_em_dash_without_spaces():
    assert remove_em_dashes("I hear you—many people agree") == "I hear you, many people agree"


def test_em_dash_with_spaces():
    assert remove_em_dashes("It's simple — just try it") == "It's simple, just try it"


def test_spaced_en_dash():
    assert remove_em_dashes("Cheap – and filling") == "Cheap, and filling"


def test_ranges_and_hyphens_unchanged():
    text = "Eat 2–4 plant-based meals a week"
    assert remove_em_dashes(text) == text
