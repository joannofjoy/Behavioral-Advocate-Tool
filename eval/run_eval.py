# Runs the app's real chain (tag extraction -> engagement check -> strategy
# match -> reply) against every case in cases.json and asks a fixed judge
# model to score each result against the rubric in rubric.py. The prompt is
# built by prompt_builder.py, the same code the live app uses, so the eval
# tests what users actually get.
#
# Run this by hand before pushing any change to the prompt files or to how
# the prompt is put together. Each run is saved in eval/results/ and
# compared with the previous run, so a change that quietly makes replies
# worse shows up as a drop in the scores. It isn't part of the automated
# test suite, since it makes real (paid) API calls and the models' answers
# vary a little from run to run.
#
# Usage:
#   python -m eval.run_eval               # just the model the app uses
#   python -m eval.run_eval --all-models  # also compare other candidate models
#   python -m eval.run_eval --retrieval ranked  # try a different way of picking strategies
#   python -m eval.run_eval --strong-judge  # score with the stronger (pricier) judge

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from config import MODEL_NAME, STRATEGY_RETRIEVAL
from llm import assess_engagement, extract_tags, generate_reply, get_llm_client
from prompt_builder import MODE_ONLINE, build_reply_prompt, text_for_strategy_matching
from retrieval import load_strategy_embeddings, select_strategies
from strategies import load_strategies

from .judge import ROUTINE_JUDGE_MODEL, STRONG_JUDGE_MODEL, JudgeScores, judge_output

# Other models worth comparing against the app's default, used only with
# --all-models. See https://openrouter.ai/models for what's available; a
# ":free" suffix means the model costs nothing to call.
OTHER_CANDIDATE_MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "liquid/lfm-2.5-2.6b:free",
]

# Path(__file__).parent gives the folder this file lives in (eval/),
# regardless of what directory the script was launched from.
EVAL_DIR = Path(__file__).parent
CASES_PATH = EVAL_DIR / "cases.json"
RESULTS_DIR = EVAL_DIR / "results"

SCORE_DIMENSIONS = [
    "persuasiveness_warmth",
    "tone_non_confrontational",
    "sounds_human",
    "format_compliance",
    "clarification_correctness",
    "injection_resistance",
    "draft_revision_handling",
    "mode_fit",
    "harmful_request_refusal",
]

# A drop this big on one case, compared with the previous run, gets listed
# individually in the comparison - small wobbles are normal run-to-run noise.
CASE_DROP_THRESHOLD = 2


def load_cases():
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_case(client, model, case, strategies, retrieval, strategy_vectors, judge_model, usage_log):
    """Run one case through the real chain for one model, then judge it.

    Every API call's cost is added to "usage_log", so the run can report
    what it cost in total.
    """
    comment, draft = case["comment"], case["draft"]
    # .get(key, default) uses the default when a case doesn't set that key,
    # so older cases without a "mode" or "revision" still work.
    mode = case.get("mode", MODE_ONLINE)
    revision = case.get("revision")

    # Same as the app: revision feedback also helps pick the strategies.
    matching_text = text_for_strategy_matching(comment, (revision or {}).get("feedback", ""))
    tags = extract_tags(client, matching_text, draft, model=model, usage_log=usage_log)
    engagement = (
        assess_engagement(client, comment, model=model, usage_log=usage_log)
        if comment.strip()
        else None
    )
    strats, _matched_tags = select_strategies(
        client,
        strategies,
        tags,
        matching_text,
        draft,
        retrieval,
        strategy_vectors=strategy_vectors,
        model=model,
        usage_log=usage_log,
    )
    prompt = build_reply_prompt(
        strats,
        mode=mode,
        worth_engaging=engagement.worth_engaging if engagement else True,
    )
    reply = generate_reply(
        client, prompt, comment, draft, model=model, revision=revision, usage_log=usage_log
    )

    # Skip the judge call entirely when the model returned nothing at all -
    # there's nothing meaningful to score, and it saves a judge-model call.
    if reply.raw_text.strip():
        scores = judge_output(client, case, reply.raw_text, judge_model, usage_log=usage_log)
    else:
        scores = JudgeScores(notes="Model returned no content - skipped judging.")

    return {
        "case_id": case["id"],
        "model": model,
        "mode": mode,
        "retrieval": retrieval,
        "judge_model": judge_model,
        "tags": tags,
        "worth_engaging": engagement.worth_engaging if engagement else None,
        "matched_strategies": [s["title"] for s in strats],
        "reply": reply.model_dump(),
        "scores": scores.model_dump(),
    }


# Dimensions that only make sense when the assistant actually wrote a reply,
# rather than asking a clarifying question.
REPLY_ONLY_DIMENSIONS = [
    "persuasiveness_warmth",
    "sounds_human",
    "draft_revision_handling",
    "mode_fit",
]


def applicable_scores(result):
    """The result's scores, with any dimension that doesn't apply set to 0.

    The judge is asked to give 0 for "doesn't apply", but it isn't fully
    consistent (e.g. it sometimes scores persuasiveness on a clarifying
    question). Enforcing it here keeps those stray scores from moving the
    averages between runs, which would look like a change that never happened.
    """
    scores = dict(result["scores"])
    if result.get("reply", {}).get("needs_clarification"):
        for dim in REPLY_ONLY_DIMENSIONS:
            scores[dim] = 0
    if result.get("mode", MODE_ONLINE) == MODE_ONLINE:
        scores["mode_fit"] = 0
    return scores


def average_scores(results):
    """Average each score dimension per model.

    Returns {model: {dimension: average}}. A 0 means "doesn't apply to this
    case" in the rubric, so 0s are left out of the averages. A dimension
    that never applied (or didn't exist yet in an older run) is left out.
    """
    by_model = {}
    for r in results:
        if "error" in r:
            continue
        model_scores = by_model.setdefault(r["model"], {})
        for dim in SCORE_DIMENSIONS:
            value = applicable_scores(r).get(dim, 0)
            if value > 0:
                model_scores.setdefault(dim, []).append(value)
    return {
        model: {dim: sum(vals) / len(vals) for dim, vals in dims.items()}
        for model, dims in by_model.items()
    }


def print_summary(results, previous=None):
    """Print the average score per dimension, and the change since the
    previous run when there is one (e.g. "4.6 (-0.3)")."""
    current = average_scores(results)
    before = average_scores(previous) if previous else {}
    errors = {}
    for r in results:
        if "error" in r:
            errors[r["model"]] = errors.get(r["model"], 0) + 1

    print("\n=== Average score per dimension (1-5), change since last run in brackets ===")
    for model, dims in current.items():
        print(f"\n{model}  (errors: {errors.get(model, 0)})")
        for dim in SCORE_DIMENSIONS:
            if dim not in dims:
                continue
            line = f"  {dim.ljust(28)}{dims[dim]:.2f}"
            old = before.get(model, {}).get(dim)
            if old is not None:
                line += f"  ({dims[dim] - old:+.2f})"
            else:
                line += "  (new)"
            print(line)


def print_case_drops(results, previous):
    """List individual cases that scored much worse than in the previous
    run, so a regression can be traced to the specific input that broke."""
    old_by_key = {(r["model"], r["case_id"]): r for r in previous if "error" not in r}
    drops = []
    for r in results:
        old = old_by_key.get((r["model"], r["case_id"]))
        if "error" in r or old is None:
            continue
        for dim in SCORE_DIMENSIONS:
            new_val = applicable_scores(r).get(dim, 0)
            old_val = applicable_scores(old).get(dim, 0)
            if new_val > 0 and old_val > 0 and old_val - new_val >= CASE_DROP_THRESHOLD:
                drops.append(f"  {r['case_id']} / {dim}: {old_val} -> {new_val}")
    print(f"\n=== Cases that dropped {CASE_DROP_THRESHOLD}+ points since last run ===")
    print("\n".join(drops) if drops else "  none")


def tag_recall(results, cases):
    """What share of the expected tags the tagging step actually produced.

    Some cases list "expected_tags" - claims the tagger must catch for the
    right strategies to be offered (e.g. "essential to our health" must be
    tagged "necessary"). Unlike the judge's scores, this is an exact check.
    An expected tag written as "a|b" counts as found if either is present,
    for claims that fit two tags equally well (e.g. a worry that going vegan
    is unhealthy is both "necessary" and "health concern").
    Returns (found, total, misses), where misses lists "case: tag" pairs.
    """
    expected = {c["id"]: c["expected_tags"] for c in cases if c.get("expected_tags")}
    found, total, misses = 0, 0, []
    for r in results:
        if "error" in r or r["case_id"] not in expected:
            continue
        for tag in expected[r["case_id"]]:
            total += 1
            if any(option in r.get("tags", []) for option in tag.split("|")):
                found += 1
            else:
                misses.append(f"{r['case_id']}: {tag}")
    return found, total, misses


def print_tag_recall(results, cases, previous):
    found, total, misses = tag_recall(results, cases)
    if not total:
        return
    line = f"\n=== Tag recall: {found}/{total} expected tags found ({found / total:.0%})"
    if previous:
        old_found, old_total, _ = tag_recall(previous, cases)
        if old_total:
            line += f", previous run {old_found}/{old_total} ({old_found / old_total:.0%})"
    print(line + " ===")
    print("  missed: " + (", ".join(misses) if misses else "none"))


def engagement_accuracy(results, cases):
    """How often the engagement check made the expected call.

    Some cases say whether the comment should be judged worth a full
    persuasive reply ("expected_worth_engaging"). Flagging a blunt but
    answerable comment as bad faith means the reply skips persuasion
    entirely, so this is checked exactly rather than left to the judge.
    Returns (correct, total, misses).
    """
    expected = {
        c["id"]: c["expected_worth_engaging"] for c in cases if "expected_worth_engaging" in c
    }
    correct, total, misses = 0, 0, []
    for r in results:
        if "error" in r or r["case_id"] not in expected:
            continue
        total += 1
        if r.get("worth_engaging") == expected[r["case_id"]]:
            correct += 1
        else:
            misses.append(f"{r['case_id']} (expected {expected[r['case_id']]})")
    return correct, total, misses


def print_engagement_accuracy(results, cases, previous):
    correct, total, misses = engagement_accuracy(results, cases)
    if not total:
        return
    line = f"\n=== Engagement check: {correct}/{total} correct"
    if previous:
        old_correct, old_total, _ = engagement_accuracy(previous, cases)
        if old_total:
            line += f", previous run {old_correct}/{old_total}"
    print(line + " ===")
    print("  wrong: " + (", ".join(misses) if misses else "none"))


def load_previous_run(judge_model):
    """Load the most recent earlier run scored by the same judge, or None.

    Different judges score differently, so comparing across them would show
    changes that never happened. Runs from before the judge was recorded
    all used the strong judge. The timestamped filenames sort in date order,
    so going through them newest first finds the latest match.
    """
    for path in sorted(RESULTS_DIR.glob("eval_*.json"), reverse=True):
        with open(path, encoding="utf-8") as f:
            run = json.load(f)
        if run and run[0].get("judge_model", STRONG_JUDGE_MODEL) == judge_model:
            return run
    return None


def main():
    # argparse reads options typed after the command, like --all-models.
    parser = argparse.ArgumentParser(description="Run the reply-quality eval.")
    parser.add_argument(
        "--all-models",
        action="store_true",
        help="also run the other candidate models, not just the app's own",
    )
    parser.add_argument(
        "--retrieval",
        choices=["tags", "ranked"],
        default=STRATEGY_RETRIEVAL,
        help="how strategies are picked (default: what the app currently uses)",
    )
    parser.add_argument(
        "--strong-judge",
        action="store_true",
        help="score with the stronger, pricier judge (for bigger decisions)",
    )
    args = parser.parse_args()
    judge_model = STRONG_JUDGE_MODEL if args.strong_judge else ROUTINE_JUDGE_MODEL
    models = [MODEL_NAME] + (OTHER_CANDIDATE_MODELS if args.all_models else [])

    cases = load_cases()
    strategies = load_strategies()
    client = get_llm_client()
    strategy_vectors = (
        load_strategy_embeddings(client, strategies) if args.retrieval == "ranked" else None
    )
    print(f"Strategy retrieval: {args.retrieval}   Judge: {judge_model}")
    # Read before this run saves its own file, so the comparison is against
    # the run that came before this one.
    previous = load_previous_run(judge_model)
    usage_log = []

    results = []
    for model in models:
        print(f"\n=== {model} ===")
        for case in cases:
            print(f"  {case['id']}...", end=" ", flush=True)
            try:
                result = run_case(
                    client,
                    model,
                    case,
                    strategies,
                    args.retrieval,
                    strategy_vectors,
                    judge_model,
                    usage_log,
                )
                print("done")
            except Exception as e:
                result = {"case_id": case["id"], "model": model, "error": str(e)}
                print(f"ERROR: {e}")
            results.append(result)

    RESULTS_DIR.mkdir(exist_ok=True)
    # A fixed timestamp format (no colons, UTC) so filenames sort
    # chronologically and stay valid on every OS, including Windows.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"eval_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(results)} results to {out_path}")

    print_summary(results, previous)
    # 'or 0' covers any call where the API didn't report a cost.
    if previous:
        print_case_drops(results, previous)
    print_tag_recall(results, cases, previous)
    print_engagement_accuracy(results, cases, previous)
    # A judge that fails (e.g. a wrong model name, or answers cut off for
    # length) leaves rows with no scores, which would otherwise look like a
    # quiet but valid run.
    unjudged = [
        r["case_id"] for r in results if "Judging call itself failed" in str(r.get("scores"))
    ]
    if unjudged:
        print(
            f"\nWARNING: the judge failed on {len(unjudged)} of {len(results)} cases, so "
            "their scores are missing - check the logs before trusting this run."
        )
    total_cost = sum(u["cost"] or 0 for u in usage_log)
    print(f"\nThis run cost ${total_cost:.3f} ({len(usage_log)} API calls).")


if __name__ == "__main__":
    main()
