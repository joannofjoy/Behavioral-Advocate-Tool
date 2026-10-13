# Scores one eval output against the rubric in rubric.py, using a separate
# "judge" model call. Using one fixed, capable judge for every row (rather
# than each model judging itself) is what makes the scores comparable across
# a whole run.

import logging

from pydantic import BaseModel

from jsonutils import parse_json_object
from llm import _create_completion

from .rubric import JUDGE_RESPONSE_SCHEMA_HINT, RUBRIC

logger = logging.getLogger(__name__)

# Kept separate from config.MODEL_NAME on purpose: the judge should stay
# fixed across an entire eval run even while the model being judged changes
# from row to row, so every row is scored on the same yardstick.
JUDGE_MODEL = "openai/gpt-4o"


class JudgeScores(BaseModel):
    """The judge's scores for one eval output, one field per rubric dimension.

    All default to 0 ("not applicable" per the rubric's own instructions),
    so a judge call that fails outright still returns something the summary
    table in run_eval.py can handle without special-casing it.
    """

    persuasiveness_warmth: int = 0
    tone_non_confrontational: int = 0
    sounds_human: int = 0
    format_compliance: int = 0
    clarification_correctness: int = 0
    injection_resistance: int = 0
    draft_revision_handling: int = 0
    mode_fit: int = 0
    notes: str = ""


def judge_output(client, case, raw_output_text):
    """Ask the judge model to score one case's raw output against the rubric.

    "case" is one dict from cases.json: {id, comment, draft, note}, plus
    optionally "mode" and "revision". "raw_output_text" is exactly what the
    evaluated model returned for the reply-generation step - valid JSON or
    not - so the judge sees the same thing the app itself would have gotten
    back.
    """
    revision = case.get("revision")
    revision_text = ""
    if revision:
        revision_text = (
            "The user asked the assistant to revise its previous reply:\n"
            f"Previous reply: {revision['previous_reply']}\n"
            f"User's feedback: {revision.get('feedback') or '(none)'}\n"
            f"User's rating: {revision.get('rating') or '(not rated)'}\n"
        )
    prompt = (
        f"{RUBRIC}\n\n"
        f"What this case is testing: {case['note']}\n"
        f"Mode: {case.get('mode', 'Online comments')}\n"
        f"Comment shown to the assistant: {case['comment'] or '(empty)'}\n"
        f"Draft reply shown to the assistant: {case['draft'] or '(empty)'}\n"
        f"{revision_text}\n"
        f"Assistant's raw output:\n{raw_output_text}\n\n"
        f"{JUDGE_RESPONSE_SCHEMA_HINT}"
    )
    try:
        r = _create_completion(
            client,
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=300,
        )
        parsed = parse_json_object(r.choices[0].message.content)
        return JudgeScores.model_validate(parsed)
    except Exception:
        logger.exception("Judging failed for case %s", case["id"])
        return JudgeScores(notes="Judging call itself failed - see logs.")
