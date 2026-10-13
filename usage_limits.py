# Keeps the app's API credits from being drained, whether by accident or on
# purpose. Two daily limits are checked before every reply:
#
# - A spending cap for the whole app: once today's total cost reaches
#   DAILY_SPEND_LIMIT_USD, the app pauses for everyone until tomorrow (UTC).
#   This is the real safety net - however someone misuses the app, it can't
#   cost more than this per day.
# - A reply limit per visitor, so one person can't use up the shared budget
#   alone. Visitors are told apart by their IP address, but the address is
#   never stored: only a scrambled version of it (a "hash") is, which can't
#   be turned back into the original address.
#
# The counts live in Firestore so they survive page refreshes, new sessions,
# and app restarts. Without Firebase (e.g. local development), they're kept
# in memory instead and reset when the app restarts.

import datetime
import hashlib
import logging
import os
import secrets

from config import DAILY_SPEND_LIMIT_USD, VISITOR_DAILY_REPLY_LIMIT

logger = logging.getLogger(__name__)

# Mixed into every IP address before hashing. Without it, someone with the
# stored hashes could hash all ~4 billion possible IPv4 addresses and match
# them up; with a secret mixed in, they can't. Set VISITOR_HASH_SALT in the
# environment or Streamlit secrets to keep visitor counts stable across app
# restarts; otherwise a random one is made each time the app starts (counts
# then reset on restart, which is harmless).
_SALT = os.getenv("VISITOR_HASH_SALT") or secrets.token_hex(16)

# The in-memory fallback, used only when Firestore isn't available.
_memory = {"day": None, "spend": 0.0, "visitors": {}}

DAILY_LIMIT_MESSAGE = (
    "The assistant has reached its usage limit for today, which keeps this free "
    "demo running. Please come back tomorrow!"
)
VISITOR_LIMIT_MESSAGE = (
    f"You've reached today's limit of {VISITOR_DAILY_REPLY_LIMIT} replies. "
    "Please come back tomorrow!"
)


def today():
    """Today's date in UTC as text, e.g. "2026-10-13" - the daily limits
    reset when this changes."""
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def visitor_id(ip_address):
    """A scrambled, fixed-length ID for a visitor's IP address, or None for
    local development (where Streamlit reports no IP address)."""
    if not ip_address:
        return None
    return hashlib.sha256((_SALT + ip_address).encode("utf-8")).hexdigest()[:24]


def _reset_memory_if_new_day():
    if _memory["day"] != today():
        _memory.update({"day": today(), "spend": 0.0, "visitors": {}})


def _read(db, visitor):
    """Today's total spend for the app, and today's reply count for this
    visitor (0 for local development)."""
    if db is None:
        _reset_memory_if_new_day()
        return _memory["spend"], _memory["visitors"].get(visitor, 0)
    day_doc = db.collection("usage_daily").document(today()).get().to_dict() or {}
    count = 0
    if visitor:
        visitor_doc = (
            db.collection("usage_visitors").document(f"{today()}_{visitor}").get().to_dict() or {}
        )
        count = visitor_doc.get("replies", 0)
    return day_doc.get("cost_usd", 0.0), count


def check_limits(db, visitor):
    """Return a message to show the user if a limit has been reached, or
    None if they're free to generate a reply.

    If Firestore can't be read, this lets the request through rather than
    blocking every visitor because of a database hiccup; the key's own
    credit limit on OpenRouter is the backstop for that rare case.
    """
    try:
        spend, replies = _read(db, visitor)
    except Exception:
        logger.exception("Could not read usage limits")
        return None
    if spend >= DAILY_SPEND_LIMIT_USD:
        return DAILY_LIMIT_MESSAGE
    if visitor and replies >= VISITOR_DAILY_REPLY_LIMIT:
        return VISITOR_LIMIT_MESSAGE
    return None


def record_usage(db, visitor, cost_usd):
    """Add one reply's cost to today's totals."""
    try:
        if db is None:
            _reset_memory_if_new_day()
            _memory["spend"] += cost_usd
            if visitor:
                _memory["visitors"][visitor] = _memory["visitors"].get(visitor, 0) + 1
            return
        # Imported here so the in-memory path (and its tests) work without
        # Firebase installed or configured.
        from firebase_admin import firestore

        # firestore.Increment adds to the stored number on the database's
        # side, so two visitors finishing at the same moment can't overwrite
        # each other's count. merge=True creates the document if it's new.
        db.collection("usage_daily").document(today()).set(
            {"cost_usd": firestore.Increment(cost_usd), "replies": firestore.Increment(1)},
            merge=True,
        )
        if visitor:
            db.collection("usage_visitors").document(f"{today()}_{visitor}").set(
                {"replies": firestore.Increment(1), "day": today()}, merge=True
            )
    except Exception:
        logger.exception("Could not record usage")
