# Downloads every logged session from Firestore and saves it on this
# computer, as a spreadsheet (CSV, opens in Excel) plus a complete JSON
# backup. Run by hand (python export_logs.py) whenever you want a fresh
# copy - for a backup, or to read through what visitors typed and how they
# rated the replies.
#
# The files land in the exports/ folder, which is excluded from Git: they
# contain what visitors typed into the app, so they must never be uploaded
# to the public GitHub repo.

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from firebase_logger import fetch_all_sessions, init_firebase

EXPORT_DIR = Path(__file__).parent / "exports"

# The spreadsheet's columns, in order. Each one is filled by flatten_session()
# below. Anything not listed here is still kept in the JSON backup.
COLUMNS = [
    "timestamp",
    "session_id",
    "version",
    "visitor_id",
    "is_test",
    "use_case",
    "comment",
    "draft_reply",
    "reply",
    "explanation",
    "what_changed",
    "delivery_tip",
    "rating",
    "rating_confirmed",
    "written_feedback",
    "worth_engaging",
    "engagement_reason",
    "tags",
    "strategies",
    "false_claims",
    "quality_sounds_human",
    "quality_addresses_point",
    "quality_specific_not_generic",
    "quality_persuasiveness",
    "quality_tone_non_confrontational",
    "quality_notes",
    "cost_usd",
]


def _join(value):
    """Turn a list into one readable cell ("a; b; c"); leave anything else as is."""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return value


def flatten_session(doc):
    """Turn one Firestore log entry into one spreadsheet row.

    The entry stores the visitor's input as a small piece of JSON text
    ({"comment": ..., "draft_reply": ...}) and the quality scores as a nested
    dictionary, so both are unpacked into their own columns here. Fields
    that older entries don't have yet are left blank.
    """
    try:
        user_input = json.loads(doc.get("user_input") or "{}")
    except (TypeError, ValueError):
        # Very old entries may have stored plain text instead of JSON.
        user_input = {"comment": doc.get("user_input")}
    quality = doc.get("quality_scores") or {}
    row = {
        "timestamp": doc.get("timestamp"),
        "session_id": doc.get("session_id"),
        "version": doc.get("version"),
        "visitor_id": doc.get("visitor_id"),
        "is_test": doc.get("is_test"),
        # Older entries used "relationship_context" before modes existed.
        "use_case": doc.get("use_case") or doc.get("relationship_context"),
        "comment": user_input.get("comment"),
        "draft_reply": user_input.get("draft_reply"),
        "reply": doc.get("llm_message"),
        "explanation": doc.get("llm_explanation"),
        "what_changed": doc.get("what_changed"),
        "delivery_tip": doc.get("delivery_tip"),
        "rating": doc.get("rating"),
        "rating_confirmed": doc.get("rating_confirmed"),
        "written_feedback": doc.get("written_feedback"),
        "worth_engaging": doc.get("worth_engaging"),
        "engagement_reason": doc.get("engagement_reason"),
        "tags": _join(doc.get("tags_input")),
        "strategies": _join(doc.get("strategies")),
        "false_claims": _join(doc.get("false_claims")),
        "quality_notes": quality.get("notes"),
        "cost_usd": doc.get("cost_usd"),
    }
    for name in [
        "sounds_human",
        "addresses_point",
        "specific_not_generic",
        "persuasiveness",
        "tone_non_confrontational",
    ]:
        row[f"quality_{name}"] = quality.get(name)
    return row


def main():
    db = init_firebase()
    if not db:
        print("Firebase isn't configured on this computer, so there's nothing to export.")
        return

    sessions = fetch_all_sessions(db)
    # Oldest first, which reads most naturally in a spreadsheet. "or ''"
    # keeps entries without a timestamp from breaking the sort.
    sessions.sort(key=lambda doc: doc.get("timestamp") or "")

    EXPORT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = EXPORT_DIR / f"session_logs_{stamp}.csv"
    json_path = EXPORT_DIR / f"session_logs_{stamp}.json"

    # "utf-8-sig" adds a small marker at the start of the file that tells
    # Excel the text is UTF-8, so accents, emoji, and quotes display
    # correctly instead of as garbled characters. newline="" is what the csv
    # module expects, so it doesn't add blank lines between rows on Windows.
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for doc in sessions:
            writer.writerow(flatten_session(doc))

    # The complete, unflattened records - every field, nothing left out.
    # default=str turns anything JSON can't store directly (like dates) into
    # text instead of crashing.
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False, default=str)

    real = sum(1 for doc in sessions if not doc.get("is_test"))
    print(f"Exported {len(sessions)} entries ({real} not marked as tests).")
    print(f"Spreadsheet: {csv_path}")
    print(f"Full backup: {json_path}")


if __name__ == "__main__":
    main()
