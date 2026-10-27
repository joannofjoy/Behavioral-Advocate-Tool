# Chooses which strategies from strategies.json go into each reply prompt.
#
# There are two ways to do it (picked with STRATEGY_RETRIEVAL in config.py):
#
# - "tags": the original approach. Every strategy that shares a tag with the
#   comment is used, in no particular order. Simple, but it only works when
#   the tagging step happens to pick the same words the strategy uses, and
#   a common tag can pull in many strategies at once.
#
# - "ranked": retrieval-augmented generation (RAG). Each strategy is turned
#   into an embedding (a list of numbers capturing its meaning) once and
#   saved in strategy_embeddings.json. For each comment, the comment is
#   embedded the same way and the closest strategies in meaning are
#   shortlisted; then the model picks the best few from that shortlist, in
#   order. This keeps working as the library grows into the hundreds.
#
# If any step of the ranked approach fails (e.g. the API is unreachable),
# it falls back to tag matching, so a reply can still be written.

import hashlib
import json
import logging
import math
from pathlib import Path

from config import (
    MAX_TAG_STRATEGIES,
    RETRIEVAL_CANDIDATES,
    STRATEGIES_PER_REPLY,
    STRATEGY_EMBEDDINGS_PATH,
    TAG_CANDIDATES,
)
from llm import embed_texts, rank_strategies
from strategies import filter_strategies_by_tags, pick_top_strategies

logger = logging.getLogger(__name__)


def strategy_text(strategy):
    """The text that gets embedded for one strategy: its title, what it
    does, and its tags and goals, so the embedding reflects all of them."""
    return (
        f"{strategy['title']}. {strategy['description']} "
        f"Tags: {', '.join(strategy.get('tags', []))}. "
        f"Goals: {', '.join(strategy.get('goals', []))}."
    )


def _fingerprint(text):
    """A short ID that changes whenever the text changes.

    hashlib.sha256 turns any text into a fixed-length code; editing even one
    character of a strategy gives a completely different code. That's how
    the saved embeddings file knows which strategies are new or edited and
    need re-embedding, without re-embedding the whole library every time.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_strategy_embeddings(client, strategies, path=STRATEGY_EMBEDDINGS_PATH):
    """Return one embedding per strategy, in the same order as "strategies".

    Embeddings already saved in the file are reused; only new or edited
    strategies are sent to the API, all in one call. The file is then
    updated so the next start is instant.
    """
    path = Path(path)
    cache = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)

    # A dict comprehension: builds {fingerprint: text} for every strategy.
    texts = {_fingerprint(strategy_text(s)): strategy_text(s) for s in strategies}
    missing = [fp for fp in texts if fp not in cache]
    if missing:
        vectors = embed_texts(client, [texts[fp] for fp in missing])
        # zip pairs each fingerprint with its vector. Rounding to 5 decimal
        # places keeps the file much smaller without changing the results.
        for fp, vec in zip(missing, vectors):
            cache[fp] = [round(x, 5) for x in vec]
        # Drop entries for strategies that no longer exist, then save.
        cache = {fp: vec for fp, vec in cache.items() if fp in texts}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cache, f)
        except OSError:
            # Some hosts don't allow writing files; the embeddings are still
            # usable from memory for this run.
            logger.warning("Could not save %s", path)

    return [cache[_fingerprint(strategy_text(s))] for s in strategies]


def cosine_similarity(a, b):
    """How similar two embeddings are, from -1 (opposite) to 1 (same meaning).

    It compares the direction the two lists of numbers point in, ignoring
    their overall size.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def shortlist(client, strategies, strategy_vectors, comment, draft, k, usage_log=None):
    """The k strategies closest in meaning to the comment.

    Searches with the other person's comment only: the strategies are about
    answering what they said, and mixing in the user's own draft (which may
    be off-track, e.g. an angry first attempt) pulls the search the wrong
    way. With no comment, the draft is all there is to go on.
    """
    query = comment if comment.strip() else draft
    query_vector = embed_texts(client, [query], usage_log=usage_log)[0]
    scored = [
        (cosine_similarity(query_vector, vec), s) for s, vec in zip(strategies, strategy_vectors)
    ]
    # Sort by similarity, highest first. "key=lambda pair: pair[0]" tells
    # sorted() to compare the pairs by their first item, the score.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [s for _score, s in scored[:k]]


def best_tag_matches(tag_matches, tags, k):
    """The k tag-matched strategies sharing the most tags with the comment."""
    wanted = set(tags)
    # sorted() is stable: strategies with the same number of shared tags
    # keep their order from strategies.json.
    ranked = sorted(tag_matches, key=lambda s: len(wanted & set(s.get("tags", []))), reverse=True)
    return ranked[:k]


def select_strategies(
    client,
    strategies,
    tags,
    comment,
    draft,
    method,
    strategy_vectors=None,
    model=None,
    usage_log=None,
):
    """Pick the strategies to put in the reply prompt.

    "method" is "tags" or "ranked" (see the top of this file). Returns
    (strategies, matched_tags); matched_tags is always the tag overlap, so
    the logs stay comparable whichever method was used.
    """
    tag_matches, matched_tags = filter_strategies_by_tags(strategies, tags)
    if method != "ranked" or not (comment.strip() or draft.strip()):
        # Tag matching: offer only the best few matches, not all of them.
        return pick_top_strategies(tag_matches, tags, MAX_TAG_STRATEGIES), matched_tags

    try:
        if strategy_vectors is None:
            strategy_vectors = load_strategy_embeddings(client, strategies)
        candidates = shortlist(
            client,
            strategies,
            strategy_vectors,
            comment,
            draft,
            RETRIEVAL_CANDIDATES,
            usage_log=usage_log,
        )
        # Searching by meaning finds strategies for the person's argument,
        # but tends to miss the general ones for their mood (e.g. "Validate
        # Before Redirecting" for someone defensive), whose descriptions are
        # short and generic. The tags capture mood well, so the strongest
        # tag matches join the shortlist too, and the ranking step picks
        # from both.
        for s in best_tag_matches(tag_matches, tags, TAG_CANDIDATES):
            if s not in candidates:
                candidates.append(s)
        # "**extra" passes model= only when one was given, so the ranking
        # otherwise uses llm.py's default model.
        extra = {"model": model} if model else {}
        chosen = rank_strategies(
            client,
            comment,
            draft,
            candidates,
            STRATEGIES_PER_REPLY,
            usage_log=usage_log,
            **extra,
        )
        return chosen, matched_tags
    except Exception:
        logger.exception("Ranked strategy retrieval failed; falling back to tag matching")
        return tag_matches, matched_tags
