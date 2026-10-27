# Small fixes applied to the model's text before anyone sees it: removing em
# dashes, and trimming replies to the optional character limit.
#
# The prompt asks the model never to use em dashes, because they're one of
# the clearest signs that text was AI-written, but it still slips them in
# now and then. Asking more firmly only goes so far; replacing them in code
# afterwards works every time.

import re

# A long dash, optionally with spaces around it: "you—many" or "you — many".
# The en dash (–) is included only when it has spaces around it, so number
# ranges like "2–4" are left alone.
_DASH = re.compile(r"\s*—\s*|\s+–\s+")


# The end of a sentence: ".", "!" or "?" followed by a space. The "(?<=...)"
# part means "only split right after one of these", so the punctuation stays
# attached to its sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def trim_to_char_limit(text, limit):
    """Cut text down to at most "limit" characters (spaces included), ending
    at a full sentence.

    Characters rather than words, because that's how platforms set their
    limits (e.g. 280 on X, 150 for TikTok comments). Keeps as many whole
    sentences as fit. If even the first sentence is too long, it cuts at the
    last whole word that fits and adds "..." so the cut is visible. Used as a
    last resort, after asking the model to shorten.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    kept = ""
    for sentence in _SENTENCE_END.split(text):
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > limit:
            break
        kept = candidate
    if kept:
        return kept
    # rsplit(" ", 1)[0] drops the last, possibly half-cut, word; 3 characters
    # are kept free for the "...".
    return text[: limit - 3].rsplit(" ", 1)[0] + "..."


def remove_em_dashes(text):
    """Replace em dashes (and spaced en dashes) with a comma and a space.

    A comma is the closest natural replacement in most sentences, e.g.
    "I hear you—many people feel that way" becomes
    "I hear you, many people feel that way".
    """
    return _DASH.sub(", ", text)
