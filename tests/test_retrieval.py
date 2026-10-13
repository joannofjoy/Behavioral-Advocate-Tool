# Tests for retrieval.py's logic that doesn't need a real API call: the
# similarity maths, the saved-embeddings file only re-embedding what changed,
# and the fallback to tag matching. The embedding call itself is replaced
# with a fake (via pytest's "monkeypatch"), so these run instantly and free.

import json

import retrieval

STRATEGIES = [
    {"title": "A", "description": "first", "tags": ["natural"], "goals": []},
    {"title": "B", "description": "second", "tags": ["health"], "goals": []},
]


def test_cosine_similarity_basics():
    assert retrieval.cosine_similarity([1, 0], [1, 0]) == 1.0
    assert retrieval.cosine_similarity([1, 0], [0, 1]) == 0.0
    assert retrieval.cosine_similarity([0, 0], [1, 0]) == 0.0


def test_only_new_or_edited_strategies_are_embedded(tmp_path, monkeypatch):
    calls = []

    def fake_embed(client, texts, usage_log=None):
        calls.append(texts)
        return [[float(len(t)), 1.0] for t in texts]

    # Swap the real API call for the fake one, for this test only.
    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)
    path = tmp_path / "embeddings.json"

    first = retrieval.load_strategy_embeddings(None, STRATEGIES, path=path)
    assert len(calls) == 1 and len(calls[0]) == 2
    assert len(first) == 2

    # Loading again with nothing changed should not call the API at all.
    retrieval.load_strategy_embeddings(None, STRATEGIES, path=path)
    assert len(calls) == 1

    # Editing one strategy re-embeds just that one, and the stale entry
    # for its old text is removed from the file.
    edited = [STRATEGIES[0], {**STRATEGIES[1], "description": "changed"}]
    retrieval.load_strategy_embeddings(None, edited, path=path)
    assert len(calls) == 2 and len(calls[1]) == 1
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


def test_tags_method_uses_tag_matching_without_api_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("tags method should not call the API")

    monkeypatch.setattr(retrieval, "embed_texts", fail)
    chosen, matched = retrieval.select_strategies(None, STRATEGIES, ["health"], "hi", "", "tags")
    assert [s["title"] for s in chosen] == ["B"]


def test_ranked_method_falls_back_to_tags_when_the_api_fails(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("API down")

    monkeypatch.setattr(retrieval, "embed_texts", broken)
    chosen, _ = retrieval.select_strategies(
        None,
        STRATEGIES,
        ["natural"],
        "it's natural",
        "",
        "ranked",
        strategy_vectors=[[1, 0], [0, 1]],
    )
    assert [s["title"] for s in chosen] == ["A"]


def test_best_tag_matches_prefers_more_shared_tags():
    one = {"title": "one", "tags": ["angry"]}
    two = {"title": "two", "tags": ["angry", "defensive"]}
    best = retrieval.best_tag_matches([one, two], ["angry", "defensive"], 1)
    assert [s["title"] for s in best] == ["two"]
