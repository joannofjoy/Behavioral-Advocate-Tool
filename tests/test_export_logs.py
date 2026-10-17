# Tests for export_logs.flatten_session: turning one saved log entry into one
# spreadsheet row, including older entries that are missing newer fields.

from export_logs import COLUMNS, flatten_session


def test_unpacks_input_scores_and_lists():
    doc = {
        "timestamp": "2026-10-15T10:22:00",
        "user_input": '{"comment": "liver is essential", "draft_reply": ""}',
        "llm_message": "Many people do well without it.",
        "strategies": ["Correct the Necessity Myth, Respectfully", "Validate Before Redirecting"],
        "quality_scores": {"persuasiveness": 3, "notes": "clear"},
        "rating": 5,
        "use_case": "Street outreach practice",
    }
    row = flatten_session(doc)
    assert row["comment"] == "liver is essential"
    assert row["reply"] == "Many people do well without it."
    assert row["strategies"] == (
        "Correct the Necessity Myth, Respectfully; Validate Before Redirecting"
    )
    assert row["quality_persuasiveness"] == 3
    assert row["rating"] == 5
    assert set(row) == set(COLUMNS)


def test_old_entries_without_newer_fields():
    doc = {"user_input": "plain old text", "relationship_context": "A stranger online"}
    row = flatten_session(doc)
    assert row["comment"] == "plain old text"
    assert row["use_case"] == "A stranger online"
    assert row["quality_persuasiveness"] is None
