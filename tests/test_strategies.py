# Tests for strategies.py - the tag-matching logic and the JSON file loader.

from strategies import filter_strategies_by_tags, load_strategies, pick_top_strategies

# A small, fixed set of strategies to test against, so these tests don't
# depend on the real (and much bigger) strategies.json file.
SAMPLE = [
    {"title": "A", "description": "desc a", "tags": ["defensive", "angry"]},
    {"title": "B", "description": "desc b", "tags": ["curious", "open"]},
    {"title": "C", "description": "desc c", "tags": ["angry", "judgmental"]},
]


def test_filter_matches_on_any_shared_tag():
    matched, matched_tags = filter_strategies_by_tags(SAMPLE, ["angry"])
    assert [s["title"] for s in matched] == ["A", "C"]
    assert matched_tags == ["angry"]


def test_filter_with_multiple_tags_is_sorted_and_deduped():
    matched, matched_tags = filter_strategies_by_tags(SAMPLE, ["judgmental", "angry"])
    assert [s["title"] for s in matched] == ["A", "C"]
    assert matched_tags == ["angry", "judgmental"]


def test_filter_with_no_matching_tags_returns_empty():
    matched, matched_tags = filter_strategies_by_tags(SAMPLE, ["confused"])
    assert matched == []
    assert matched_tags == []


def test_load_strategies_reads_json_file(tmp_path):
    # "tmp_path" is a built-in pytest fixture: pytest automatically creates
    # a fresh, empty temporary folder and passes it in as this argument, so
    # the test can write files without touching the real project folder.
    path = tmp_path / "strategies.json"
    path.write_text('[{"title": "A", "tags": ["curious"]}]', encoding="utf-8")
    assert load_strategies(str(path)) == [{"title": "A", "tags": ["curious"]}]


def test_load_strategies_missing_file_returns_empty_list(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_strategies(str(missing)) == []


# pick_top_strategies: keeping only the most relevant few of the matches.


def strat(title, tags):
    return {"title": title, "tags": tags}


def test_claim_strategies_first_then_one_tone_strategy():
    matched = [
        strat("validate", ["defensive"]),
        strat("listen", ["defensive", "angry"]),
        strat("necessity", ["necessary"]),
        strat("welfare", ["welfarism"]),
        strat("necessity and welfare", ["necessary", "welfarism"]),
    ]
    tags = ["defensive", "angry", "necessary", "welfarism"]
    picked = [s["title"] for s in pick_top_strategies(matched, tags, 3)]
    # Two best claim-based strategies, then the best tone-only one.
    assert picked == ["necessity and welfare", "necessity", "listen"]


def test_no_limit_or_few_matches_keeps_everything():
    matched = [strat("a", ["defensive"]), strat("b", ["necessary"])]
    assert pick_top_strategies(matched, ["defensive"], 0) == matched
    assert pick_top_strategies(matched, ["defensive"], 4) == matched


def test_fills_up_when_there_are_no_tone_strategies():
    matched = [strat(str(i), ["necessary"]) for i in range(6)]
    assert len(pick_top_strategies(matched, ["necessary"], 4)) == 4
