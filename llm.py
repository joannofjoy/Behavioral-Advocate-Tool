# This file is the only place that actually talks to the LLM (via
# OpenRouter, using the same "openai" package pointed at a different
# server). It has three jobs, matching the three prompt files in this repo:
#   - extract_tags: read the conversation and label its emotional tone
#     (prompt1.txt)
#   - assess_engagement: judge whether a comment is worth a genuine
#     persuasive reply at all (prompt4.txt)
#   - generate_reply: write the persuasive reply itself (prompt2.txt, built
#     by app.py using the strategies picked out in strategies.py)

import json
import logging

import openai
import streamlit as st
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import (
    MODEL_NAME,
    OPENROUTER_BASE_URL,
    REPLY_MAX_TOKENS,
    REPLY_TEMPERATURE,
    TAG_EXTRACTION_MAX_TOKENS,
    TAG_EXTRACTION_TEMPERATURE,
    get_llm_api_key,
)
from jsonutils import parse_json_object

# A "logger" writes messages to the console/server logs, separately from
# whatever the user sees in the Streamlit UI. __name__ is a built-in
# variable holding the current module's name ("llm"), which is used here so
# log lines say which file they came from.
logger = logging.getLogger(__name__)


class ReplyResponse(BaseModel):
    """The shape we expect back from the reply-generation prompt (prompt2.txt).

    A "pydantic" model like this one checks, as soon as data is loaded into
    it, that every field has the right type - if a model's JSON reply is
    missing a field or has the wrong type in it, we find out immediately
    with a clear error, instead of that mistake quietly turning into an
    empty string somewhere deep in app.py. Giving every field a default
    value here means a reply that's simply missing a field (rather than
    having the wrong type) doesn't raise an error at all - it just falls
    back to that default, same as the old dict.get(..., default) calls did.
    """

    message: str = ""
    follow_up_question: str = ""
    explanation: str = ""
    input_type: str = "unknown"
    needs_clarification: bool = False
    # The exact text the model returned, before any parsing/validation -
    # app.py never looks at this, but eval/run_eval.py uses it to judge
    # whether a model's raw output was well-formed JSON in the first place.
    raw_text: str = ""


class EngagementAssessment(BaseModel):
    """The shape we expect back from the engagement-assessment prompt (prompt4.txt).

    "worth_engaging" defaults to True - if this assessment fails outright
    (API error, bad JSON), we want the app to fall through to its normal
    behavior (generate a real persuasive reply) rather than silently
    suppressing one because of an unrelated technical glitch.
    """

    worth_engaging: bool = True
    reason: str = ""


# Errors worth retrying: all of these are "transient" - a rate limit, a
# dropped connection, a request that timed out, or the provider's server
# briefly erroring - where trying again after a short pause has a real
# chance of succeeding. Free OpenRouter models in particular have fairly
# tight per-minute rate limits, so a busy demo visitor can hit one.
# Authentication/bad-request style errors are deliberately NOT in this
# list, since retrying those would just fail again in the same way.
_TRANSIENT_ERRORS = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)

# Shown specifically when every retry above still ends in a rate limit -
# free OpenRouter models share a fairly small per-minute quota across
# everyone using them, so this is a meaningfully different (and more
# honest) situation than "something broke."
_RATE_LIMIT_MESSAGE = (
    "⏳ The current model is busy right now (rate limited). Please wait a moment and try again."
)


@retry(
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _create_completion(client, **kwargs):
    """Call the chat completions endpoint, retrying transient failures.

    "**kwargs" collects any number of named arguments (model=...,
    messages=..., etc.) into a dictionary, so this one wrapper can sit in
    front of every call site below without needing to know their exact
    arguments. The @retry decorator above wraps this whole function: on one
    of the _TRANSIENT_ERRORS, it waits and calls the function again (up to
    3 attempts total, waiting longer each time); reraise=True means that if
    every attempt fails, the original error is raised as normal so the
    try/except blocks in the functions below still catch it.
    """
    return client.chat.completions.create(**kwargs)


def _record_usage(response, usage_log):
    """Append one API call's token/cost usage to usage_log, if one was given.

    OpenRouter includes a "usage" object on every chat completion response
    with prompt_tokens, completion_tokens, total_tokens, and cost (the
    exact dollar amount charged for that one call) - no special request
    parameters needed, it's always there. "usage_log" is a plain list the
    caller can pass in to collect these across the several calls that make
    up one interaction (tag extraction, engagement assessment, reply); if usage_log is
    None (the default - e.g. eval/run_eval.py doesn't pass one, since it
    doesn't care about cost tracking), this simply does nothing.
    """
    if usage_log is None:
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    # model_dump() turns the SDK's usage object into a plain dict. It picks
    # up "cost" even though that's an OpenRouter-specific extra field, not
    # part of the standard OpenAI response shape, because the SDK's models
    # are built to tolerate and pass through fields they don't know about.
    usage_dict = usage.model_dump()
    usage_log.append(
        {
            "model": response.model,
            "total_tokens": usage_dict.get("total_tokens"),
            "cost": usage_dict.get("cost"),
        }
    )


def get_llm_client():
    """Create an OpenAI-SDK client pointed at OpenRouter instead of OpenAI.

    OpenRouter's API matches OpenAI's exactly, so the same client class
    works - it just needs a different "base_url" and an OpenRouter API key.
    default_headers are sent with every request; OpenRouter uses them to
    attribute usage to this project in its dashboards/public rankings.
    """
    return openai.OpenAI(
        api_key=get_llm_api_key(),
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://behavioral-advocate-tool.streamlit.app/",
            "X-Title": "Animal Advocacy Messaging Assistant",
        },
    )


def load_prompt(fn):
    """Read one of the prompt*.txt files and return its contents as a string."""
    with open(fn, encoding="utf-8") as f:
        return f.read()


def extract_tags(client, comment, draft, model=MODEL_NAME, usage_log=None):
    """Ask GPT to label the comment/draft with a handful of tone tags.

    These tags (e.g. "defensive", "curious") are later used to pick relevant
    strategies from strategies.json. Returns an empty list if the call or
    the JSON parsing fails, so the rest of the app can carry on without tags.

    "model" defaults to the app's configured MODEL_NAME; the eval harness in
    eval/run_eval.py passes a different model id here to compare several
    models against the same prompt without needing its own copy of this
    function. "usage_log" is optional - see _record_usage above.
    """
    # str.format(...) fills in the {comment} and {draft} placeholders inside
    # prompt1.txt with the actual values.
    prompt = load_prompt("prompt1.txt").format(comment=comment or "N/A", draft=draft or "N/A")
    try:
        r = _create_completion(
            client,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=TAG_EXTRACTION_TEMPERATURE,
            max_tokens=TAG_EXTRACTION_MAX_TOKENS,
        )
        _record_usage(r, usage_log)
        return json.loads(r.choices[0].message.content.strip())
    except openai.RateLimitError:
        logger.exception("Tag extraction rate-limited")
        st.warning(_RATE_LIMIT_MESSAGE)
        return []
    except Exception:
        # logger.exception(...) records the full error details (including
        # where it happened) to the server logs, while st.warning(...)
        # shows a short, friendly message to the person using the app.
        logger.exception("Tag extraction failed")
        st.warning("⚠️ Tag extraction failed.")
        return []


def assess_engagement(client, comment, model=MODEL_NAME, usage_log=None):
    """Ask whether this comment is likely worth a genuine persuasive reply.

    Based on research on online discourse (bad-faith/troll engagement,
    explicit refusals to discuss, and extreme entrenchment risking a
    "boomerang effect"), most comments should still get a real persuasive
    reply - this only flags the few that clearly match one of those three
    patterns. Returns EngagementAssessment(worth_engaging=True) - i.e. "go
    ahead as normal" - on any failure; see EngagementAssessment above for
    why that's the safe default.
    """
    try:
        prompt = load_prompt("prompt4.txt").format(comment=comment or "N/A")
        r = _create_completion(
            client,
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=TAG_EXTRACTION_TEMPERATURE,
            max_tokens=TAG_EXTRACTION_MAX_TOKENS,
        )
        _record_usage(r, usage_log)
        parsed = parse_json_object(r.choices[0].message.content)
        return EngagementAssessment.model_validate(parsed)
    except Exception:
        # Deliberately no st.warning() here - a failed assessment just
        # means the app proceeds as if nothing was flagged, so surfacing
        # it to the visitor would be noise, not useful information.
        logger.exception("Engagement assessment failed")
        return EngagementAssessment()


def generate_reply(client, prompt, comment, draft, model=MODEL_NAME, usage_log=None):
    """Ask GPT to write (or improve) the persuasive reply.

    "prompt" is the full system prompt built by app.py (prompt2.txt plus the
    matched strategies, and any previous feedback). Returns a validated
    ReplyResponse - e.g. ReplyResponse(message=..., explanation=..., ...).
    If the call fails or the model's JSON doesn't match the expected shape,
    returns a ReplyResponse that asks the user to try again, reusing the
    same "needs_clarification" path the UI already handles below.

    "model" defaults to the app's configured MODEL_NAME - see extract_tags
    above for why it's a parameter. "usage_log" is optional - see
    _record_usage above.
    """
    content = ""
    try:
        r = _create_completion(
            client,
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps({"comment": comment, "draft_reply": draft}),
                },
            ],
            temperature=REPLY_TEMPERATURE,
            max_tokens=REPLY_MAX_TOKENS,
        )
        _record_usage(r, usage_log)
        # Captured before parsing, so it's still available below even if
        # parsing/validation is what ends up failing.
        content = r.choices[0].message.content or ""
        parsed = parse_json_object(content)
        response = ReplyResponse.model_validate(parsed)
        response.raw_text = content
        return response
    except openai.RateLimitError:
        logger.exception("Reply generation rate-limited")
        st.warning(_RATE_LIMIT_MESSAGE)
        return ReplyResponse(
            needs_clarification=True,
            follow_up_question="The assistant is temporarily busy - please wait and try again.",
            raw_text=content,
        )
    except Exception:
        logger.exception("Reply generation failed")
        st.warning("⚠️ Reply generation failed.")
        return ReplyResponse(
            needs_clarification=True,
            follow_up_question="Something went wrong generating a reply. Please try again.",
            raw_text=content,
        )
