# Tests for jsonutils.parse_json_object - checking that it can pull a JSON
# object out of the different shapes of text GPT tends to send back.
#
# Each "test_..." function below is picked up automatically by pytest and
# run on its own. A test passes if every "assert" statement inside it is
# true; if an assert is false, pytest reports that test as failed and shows
# what was expected versus what was actually returned.

from jsonutils import parse_json_object


def test_plain_json():
    assert parse_json_object('{"message": "hi"}') == {"message": "hi"}


def test_fenced_json_block():
    text = '```json\n{"message": "hi", "explanation": "because"}\n```'
    assert parse_json_object(text) == {"message": "hi", "explanation": "because"}


def test_fenced_without_json_tag():
    text = '```\n{"explanation": "- point one"}\n```'
    assert parse_json_object(text) == {"explanation": "- point one"}


def test_json_with_surrounding_prose():
    text = 'Sure, here you go:\n{"message": "hi"}\nLet me know if you need anything else.'
    assert parse_json_object(text) == {"message": "hi"}
