# Runs the app's real three-step chain (tag extraction -> strategy match ->
# reply -> rebuttal) against every case in cases.json, once per candidate
# model, and asks a fixed judge model to score each result against the
# rubric in rubric.py. Meant to be run by hand whenever a prompt changes or
# a new model is worth trying - not part of the automated test suite, since
# it makes real (sometimes paid) API calls and its results depend on
# whatever the models happen to return that day.
#
# Usage: python -m eval.run_eval

import json
from datetime import datetime, timezone
from pathlib import Path

from llm import extract_tags, generate_rebuttal, generate_reply, get_llm_client, load_prompt
from strategies import filter_strategies_by_tags, load_strategies

from .judge import JudgeScores, judge_output

# One paid baseline (the app's current default) plus a handful of free
# models to compare against it. Edit this list to try others - see
# https://openrouter.ai/models for what's currently available with a
# ":free" suffix.
CANDIDATE_MODELS = [
    "openai/gpt-4o-mini",
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
    "format_compliance",
    "clarification_correctness",
    "injection_resistance",
]


def load_cases():
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_case(client, model, case, strategies):
    """Run one case through the real chain for one model, then judge it."""
    comment, draft = case["comment"], case["draft"]

    tags = extract_tags(client, comment, draft, model=model)
    strats, _matched_tags = filter_strategies_by_tags(strategies, tags)
    strat_block = (
        "\n".join(f"- {s['title']}: {s['description']}" for s in strats) or "No strategies matched."
    )
    prompt = load_prompt("prompt2.txt").format(formatted_strategies=strat_block)
    reply = generate_reply(client, prompt, comment, draft, model=model)

    rebuttal = ""
    if not reply.needs_clarification and reply.message:
        rebuttal = generate_rebuttal(client, reply.message, comment, model=model)

    # Skip the judge call entirely when the model returned nothing at all -
    # there's nothing meaningful to score, and it saves a judge-model call.
    if reply.raw_text.strip():
        scores = judge_output(client, case, reply.raw_text)
    else:
        scores = JudgeScores(notes="Model returned no content - skipped judging.")

    return {
        "case_id": case["id"],
        "model": model,
        "tags": tags,
        "matched_strategies": [s["title"] for s in strats],
        "reply": reply.model_dump(),
        "rebuttal": rebuttal,
        "scores": scores.model_dump(),
    }


def print_summary(results):
    """Print a compact per-model average-score table to the console."""
    by_model = {}
    for r in results:
        entry = by_model.setdefault(r["model"], {"errors": 0, "scores": []})
        if "error" in r:
            entry["errors"] += 1
        else:
            entry["scores"].append(r["scores"])

    print("\n=== Summary (avg score per dimension, 0-5; non-applicable 0s excluded) ===")
    header = "model".ljust(38) + "".join(d[:12].ljust(14) for d in SCORE_DIMENSIONS) + "errors"
    print(header)
    for model, data in by_model.items():
        row = model.ljust(38)
        for dim in SCORE_DIMENSIONS:
            vals = [s[dim] for s in data["scores"] if s[dim] > 0]
            avg = sum(vals) / len(vals) if vals else 0
            row += f"{avg:.1f}".ljust(14)
        row += str(data["errors"])
        print(row)


def main():
    cases = load_cases()
    strategies = load_strategies()
    client = get_llm_client()

    results = []
    for model in CANDIDATE_MODELS:
        print(f"\n=== {model} ===")
        for case in cases:
            print(f"  {case['id']}...", end=" ", flush=True)
            try:
                result = run_case(client, model, case, strategies)
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

    print_summary(results)


if __name__ == "__main__":
    main()
