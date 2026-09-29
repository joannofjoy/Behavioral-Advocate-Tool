# Two complementary ways to check how much of the OpenRouter API key's
# usage has been spent: OpenRouter's own account endpoint (the
# authoritative, real-time total for this exact key), and a breakdown of
# what this app itself has recorded per interaction in Firestore (see
# firebase_logger.log_to_firestore's cost_usd/tokens_used fields). Run by
# hand (python check_credits.py) any time you want a quick answer to "how
# much have I used, and on what?" - useful since this app currently runs on
# a key from someone else's OpenRouter account, so keeping an eye on usage
# matters more than usual.

import json
import urllib.request
from collections import defaultdict

from config import get_llm_api_key
from firebase_logger import fetch_all_sessions, init_firebase


def fetch_key_info():
    """Ask OpenRouter for usage/limit info about the currently configured API key.

    urllib.request is Python's built-in way to make a simple web request,
    with no extra library needed. "with ... as resp" is a context manager -
    it opens the connection, hands it to us as "resp", and closes it
    automatically once the indented block finishes.
    """
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {get_llm_api_key()}"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)["data"]


def print_key_status():
    """Print OpenRouter's own live usage/limit numbers for this key."""
    info = fetch_key_info()
    usage = info.get("usage") or 0
    limit = info.get("limit")
    print(f"Key label: {info.get('label', '(none)')}")
    print(f"Total usage on this key: ${usage:.4f}")
    if limit is not None:
        remaining = limit - usage
        # Guard against dividing by zero if a key somehow has a $0 limit.
        pct_used = (usage / limit * 100) if limit else 0
        print(f"Limit: ${limit:.2f}  |  Remaining: ${remaining:.4f}  |  Used: {pct_used:.1f}%")
    else:
        print("No hard limit set on this key (pay-as-you-go, uncapped).")


def print_local_usage_breakdown():
    """Print a per-model cost/token breakdown from this app's own Firestore logs."""
    db = init_firebase()
    if not db:
        print("Firebase isn't configured locally - skipping the per-model breakdown.")
        return

    sessions = fetch_all_sessions(db)
    # defaultdict(float)/defaultdict(int) work like normal dicts, except
    # looking up a model name that hasn't been seen yet gives 0 instead of
    # an error - handy since we don't know the model names in advance.
    cost_by_model = defaultdict(float)
    tokens_by_model = defaultdict(int)
    for session in sessions:
        for entry in session.get("usage_details") or []:
            model = entry.get("model", "unknown")
            cost_by_model[model] += entry.get("cost") or 0
            tokens_by_model[model] += entry.get("total_tokens") or 0

    print(f"{len(sessions)} interaction(s) logged in Firestore.")
    if not cost_by_model:
        print("No per-call usage recorded yet (older records predate usage logging).")
        return

    print(f"{'model'.ljust(30)} | cost (USD) | tokens")
    rows = sorted(cost_by_model.items(), key=lambda kv: -kv[1])
    for model, cost in rows:
        print(f"{model.ljust(30)} | {cost:.4f}".ljust(46) + f" | {tokens_by_model[model]}")
    print(f"\nTotal logged cost: ${sum(cost_by_model.values()):.4f}")


def main():
    print("=== Live OpenRouter key status ===")
    print_key_status()
    print("\n=== Locally logged usage (this app's own records) ===")
    print_local_usage_breakdown()


if __name__ == "__main__":
    main()
