# Small fixes applied to the model's text before anyone sees it.
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


def remove_em_dashes(text):
    """Replace em dashes (and spaced en dashes) with a comma and a space.

    A comma is the closest natural replacement in most sentences, e.g.
    "I hear you—many people feel that way" becomes
    "I hear you, many people feel that way".
    """
    return _DASH.sub(", ", text)
