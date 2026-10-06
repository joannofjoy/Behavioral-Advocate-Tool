# This file handles talking to Firebase Firestore, a cloud database, where
# we save a record of every reply the app generates (what was asked, what
# GPT answered, how the user rated it, etc.) so sessions can be reviewed and
# used to improve the prompts later. If Firebase isn't configured (e.g. no
# credentials available), everything here just quietly does nothing instead
# of crashing the app.

import datetime
import logging
import uuid

import firebase_admin
import streamlit as st
from firebase_admin import credentials, firestore

from config import get_firebase_config

logger = logging.getLogger(__name__)


def init_firebase():
    """Set up the connection to Firestore, if credentials are available.

    Returns a Firestore client to use for logging, or None if Firebase
    couldn't be configured (missing credentials, bad config, etc.).
    """
    try:
        firebase_config = get_firebase_config()
        if firebase_config:
            # Streamlit re-runs this script on every user interaction, so
            # without some care we'd try to initialize Firebase again and
            # again, which raises an error after the first time. Checking
            # "if not firebase_admin._apps" first and only then calling
            # initialize_app() looks safe, but it isn't: if two reruns (or
            # two people using the app at once) both pass that check before
            # either one finishes initializing, the second initialize_app()
            # call still fails. So instead we just try to initialize every
            # time, and catch the "already exists" error if we lose that
            # race - either way, by the time we reach firestore.client()
            # below, the app is guaranteed to exist.
            try:
                cred = credentials.Certificate(firebase_config)
                firebase_admin.initialize_app(cred)
            except ValueError:
                pass
            return firestore.client()
    except Exception:
        # Full details go to the server log only; the on-screen message
        # stays generic so a public visitor never sees internal error text.
        logger.exception("Firebase init failed")
        st.warning("⚠️ Firebase init failed.")
    return None


def log_to_firestore(
    db,
    version,
    user_input,
    input_type,
    message,
    explanation,
    tags_input,
    tags_justification,
    matched_tags,
    matched_tags_in_strategies,
    strategies,
    session_id=None,
    rating=None,
    rating_confirmed=False,
    written_feedback=None,
    rebuttal=None,
    confidence_score=None,
    evaluation_justification=None,
    suggested_improvements=None,
    ultimate_reply=None,
    usage_details=None,
    tokens_used=None,
    cost_usd=None,
    relationship_context=None,
    worth_engaging=None,
    engagement_reason=None,
):
    """Save one reply/session record to the "session_logs" collection.

    "db" is the Firestore client from init_firebase(); if it's None
    (Firebase isn't set up), this function does nothing. Most of the other
    parameters are simply the pieces of data collected earlier in the app
    (the tags, the matched strategies, the user's rating, etc.) that we want
    to keep a record of.
    """
    if not db:
        return

    # This dictionary is what actually gets saved as one Firestore document.
    doc = {
        "version": version,
        # datetime.utcnow() gives the current time in UTC; .isoformat()
        # turns it into a standard text format like "2026-07-20T10:00:00".
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "session_id": session_id,
        "user_input": user_input,  # JSON string you already pass
        "input_type": input_type,  # "comment" | "draft_reply" | "both" | "unknown"
        "llm_message": message,  # final reply
        "llm_explanation": explanation,
        "tags_input": tags_input,  # raw extracted tags (normalized list)
        "tags_justification": tags_justification,  # what model returned in "tags" field
        "matched_tags": matched_tags,  # intersection with strategies
        "matched_tags_in_strategies": matched_tags_in_strategies,
        # This is a list comprehension: for every strategy dict "s" in
        # "strategies", pull out its "title" (or "" if it has none), and
        # collect those into a new list.
        "strategies": [s.get("title", "") for s in strategies],
        "rating": rating,
        # True only when the user actually moved the rating slider, rather
        # than it just sitting at its default value - lets future analysis
        # filter out the slider-default noise older records may contain
        # without guessing from timestamps.
        "rating_confirmed": rating_confirmed,
        "written_feedback": written_feedback,
        "rebuttal": rebuttal,
        "confidence_score": confidence_score,
        "evaluation_justification": evaluation_justification,
        "suggested_improvements": suggested_improvements,
        "ultimate_reply": ultimate_reply,
        # Per-call token/cost usage from every LLM call this interaction
        # made (see llm.py's _record_usage) plus the totals, so spend can
        # be tracked without needing to check OpenRouter's own dashboard -
        # useful since this app currently runs on a key from someone else's
        # OpenRouter account.
        "usage_details": usage_details,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        # "A stranger online" or "Someone I know (family, friend, etc.)" -
        # which tone guidance the reply was generated under.
        "relationship_context": relationship_context,
        # None when there was no comment to assess (draft-only input);
        # otherwise whether assess_engagement() judged this comment likely
        # to benefit from a genuine persuasive reply, and why not if not.
        "worth_engaging": worth_engaging,
        "engagement_reason": engagement_reason,
    }
    try:
        # uuid.uuid4() generates a random, practically-unique ID to use as
        # this document's name in the "session_logs" collection.
        db.collection("session_logs").document(str(uuid.uuid4())).set(doc)
    except Exception:
        logger.exception("Firestore log failed")
        st.warning("❌ Firestore log failed.")


def fetch_rated_sessions(db):
    """Read back every logged session that has a rating.

    This is the read counterpart to log_to_firestore(). Used by
    rating_correlations.py (run by hand, outside the Streamlit app) to see
    which strategies tend to show up in higher-rated replies - the app
    itself never reads Firestore back, it only writes to it.
    """
    if not db:
        return []
    # .stream() gets every document in the collection one at a time (rather
    # than loading them all into memory as one big list up front); doc.to_dict()
    # turns each one back into a plain Python dictionary, the same shape
    # log_to_firestore() originally saved.
    docs = db.collection("session_logs").stream()
    return [doc.to_dict() for doc in docs if doc.to_dict().get("rating") is not None]


def fetch_all_sessions(db):
    """Read back every logged session, rated or not.

    Another read counterpart to log_to_firestore(), used by
    check_credits.py to add up the cost/tokens_used recorded on every
    interaction rather than only the rated ones fetch_rated_sessions()
    returns.
    """
    if not db:
        return []
    docs = db.collection("session_logs").stream()
    return [doc.to_dict() for doc in docs]
