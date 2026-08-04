# Loads the behavioral-science strategy library (strategies.json) and picks
# out the strategies that are relevant to a given conversation, based on the
# emotional/context tags GPT extracted from the user's input.

import json

import streamlit as st

from config import STRATEGIES_PATH


def load_strategies(path=STRATEGIES_PATH):
    """Read the strategy library from a JSON file.

    Returns an empty list (and shows a warning in the app) if the file is
    missing or isn't valid JSON, so the rest of the app can keep running
    without strategies rather than crashing.
    """
    try:
        # "with open(...) as f" is a context manager: it opens the file,
        # hands it to us as "f", and closes it automatically once the
        # indented block finishes, even if something goes wrong inside.
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        st.warning("⚠️ Could not load strategies.json")
        return []


def filter_strategies_by_tags(all_strats, tags):
    """Keep only the strategies that share at least one tag with "tags".

    Returns a tuple: (the matching strategy dicts, the sorted list of tags
    that actually caused a match).
    """
    # This is a "list comprehension" - a compact way to build a new list by
    # looping over "all_strats" and keeping only the items where the
    # condition after "if" is true. any(...) is True as soon as at least one
    # of the strategy's own tags is also in "tags".
    matched = [s for s in all_strats if any(t in s.get("tags", []) for t in tags)]

    # This is a "set comprehension" - like the list comprehension above, but
    # it builds a set (a collection with no duplicates) instead of a list.
    # For every matched strategy, and every tag on that strategy, keep the
    # tag if it's one of the ones we searched for. sorted(...) then turns
    # that set into an alphabetically ordered list.
    matched_tags = sorted({t for s in matched for t in s.get("tags", []) if t in tags})

    return matched, matched_tags
