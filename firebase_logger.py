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
    except Exception as e:
        logger.exception("Firebase init failed")
        st.warning(f"⚠️ Firebase init failed: {e}")
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
    written_feedback=None,
    rebuttal=None,
    confidence_score=None,
    evaluation_justification=None,
    suggested_improvements=None,
    ultimate_reply=None,
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
        "written_feedback": written_feedback,
        "rebuttal": rebuttal,
        "confidence_score": confidence_score,
        "evaluation_justification": evaluation_justification,
        "suggested_improvements": suggested_improvements,
        "ultimate_reply": ultimate_reply,
    }
    try:
        # uuid.uuid4() generates a random, practically-unique ID to use as
        # this document's name in the "session_logs" collection.
        db.collection("session_logs").document(str(uuid.uuid4())).set(doc)
    except Exception as e:
        logger.exception("Firestore log failed")
        st.warning(f"❌ Firestore log failed: {e}")
