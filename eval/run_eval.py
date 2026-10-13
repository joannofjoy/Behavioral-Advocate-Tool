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

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from config import MODEL_NAME, STRATEGY_RETRIEVAL
from llm import assess_engagement, extract_tags, generate_reply, get_llm_client
from prompt_builder import MODE_ONLINE, build_reply_prompt
from retrieval import load_strategy_embeddings, select_strategies
from strategies import load_strategies

from .judge import JudgeScores, judge_output

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
]

# A drop this big on one case, compared with the previous run, gets listed
# individually in the comparison - small wobbles are normal run-to-run noise.
CASE_DROP_THRESHOLD = 2


def load_cases():
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_case(client, model, case, strategies, retrieval, strategy_vectors):
    """Run one case through the real chain for one model, then judge it."""
    comment, draft = case["comment"], case["draft"]
    # .get(key, default) uses the default when a case doesn't set that key,
    # so older cases without a "mode" or "revision" still work.
    mode = case.get("mode", MODE_ONLINE)
    revision = case.get("revision")

    tags = extract_tags(client, comment, draft, model=model)
    engagement = assess_engagement(client, comment, model=model) if comment.strip() else None
    strats, _matched_tags = select_strategies(
        client,
        strategies,
        tags,
        comment,
        draft,
        retrieval,
        strategy_vectors=strategy_vectors,
        model=model,
    )
    prompt = build_reply_prompt(
        strats,
        mode=mode,
        worth_engaging=engagement.worth_engaging if engagement else True,
    )
    reply = generate_reply(client, prompt, comment, draft, model=model, revision=revision)

    # Skip the judge call entirely when the model returned nothing at all -
    # there's nothing meaningful to score, and it saves a judge-model call.
    if reply.raw_text.strip():
        scores = judge_output(client, case, reply.raw_text)
    else:
        scores = JudgeScores(notes="Model returned no content - skipped judging.")

    return {
        "case_id": case["id"],
        "model": model,
        "mode": mode,
        "retrieval": retrieval,
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


def load_previous_run():
    """Load the most recent earlier results file, or None if there isn't one.

    The timestamped filenames sort in date order, so the last one in sorted
    order is the newest.
    """
    files = sorted(RESULTS_DIR.glob("eval_*.json"))
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


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
    args = parser.parse_args()
    models = [MODEL_NAME] + (OTHER_CANDIDATE_MODELS if args.all_models else [])

    cases = load_cases()
    strategies = load_strategies()
    client = get_llm_client()
    strategy_vectors = (
        load_strategy_embeddings(client, strategies) if args.retrieval == "ranked" else None
    )
    print(f"Strategy retrieval: {args.retrieval}")
    # Read before this run saves its own file, so the comparison is against
    # the run that came before this one.
    previous = load_previous_run()

    results = []
    for model in models:
        print(f"\n=== {model} ===")
        for case in cases:
            print(f"  {case['id']}...", end=" ", flush=True)
            try:
                result = run_case(client, model, case, strategies, args.retrieval, strategy_vectors)
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
    if previous:
        print_case_drops(results, previous)


if __name__ == "__main__":
    main()
