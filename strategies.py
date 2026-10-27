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


# The "tone" tags from prompt1.txt: how the person comes across, as opposed
# to the claims they make. Keep this list in sync with that prompt.
TONE_TAGS = {
    "skeptical",
    "defensive",
    "resistant",
    "curious",
    "judgmental",
    "uncertain",
    "overwhelmed",
    "angry",
    "mocking",
    "open",
    "polarized",
    "conflicted",
    "closed",
    "moral outrage",
    "frustrated",
}


def pick_top_strategies(matched, tags, limit):
    """Keep only the most relevant few of the tag-matched strategies.

    Tag matching alone often offers 9-12 strategies in no particular order,
    and with that many the model tends to fall back on the easiest one
    (e.g. "validate first") and write something generic. So each strategy is
    scored: 2 points per matching claim tag (it answers what the person
    actually argued) and 1 point per matching tone tag. The result is up to
    "limit" strategies: the best claim-based ones first, then the single best
    tone-based one, so the reply still meets the person where they are.
    A limit of 0 or None keeps them all.
    """
    if not limit or len(matched) <= limit:
        return matched
    wanted = set(tags)

    def counts(s):
        shared = wanted & set(s.get("tags", []))
        return len(shared - TONE_TAGS), len(shared & TONE_TAGS)

    # sorted() keeps the original order for ties, so the result is stable.
    by_score = sorted(matched, key=lambda s: 2 * counts(s)[0] + counts(s)[1], reverse=True)
    claim_based = [s for s in by_score if counts(s)[0] > 0]
    tone_only = [s for s in by_score if counts(s)[0] == 0]
    picked = claim_based[: limit - 1] + tone_only[:1]
    # If there weren't enough of one kind, fill up with the next best overall.
    for s in by_score:
        if len(picked) >= limit:
            break
        if s not in picked:
            picked.append(s)
    return picked
