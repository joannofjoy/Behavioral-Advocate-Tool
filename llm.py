# This file is the only place that actually talks to the OpenAI API. It has
# three jobs, matching the three prompt files in this repo:
#   - extract_tags: read the conversation and label its emotional tone
#     (prompt1.txt)
#   - generate_reply: write the persuasive reply itself (prompt2.txt, built
#     by app.py using the strategies picked out in strategies.py)
#   - generate_rebuttal: play devil's advocate against our own reply, so the
#     user can see likely pushback in advance (prompt3.txt)

import json
import logging

import openai
import streamlit as st

from config import (
    MODEL_NAME,
    REBUTTAL_MAX_TOKENS,
    REPLY_MAX_TOKENS,
    REPLY_TEMPERATURE,
    TAG_EXTRACTION_MAX_TOKENS,
    TAG_EXTRACTION_TEMPERATURE,
    get_openai_api_key,
)
from jsonutils import parse_json_object

# A "logger" writes messages to the console/server logs, separately from
# whatever the user sees in the Streamlit UI. __name__ is a built-in
# variable holding the current module's name ("llm"), which is used here so
# log lines say which file they came from.
logger = logging.getLogger(__name__)


def get_openai_client():
    """Create an OpenAI client configured with our API key."""
    return openai.OpenAI(api_key=get_openai_api_key())


def load_prompt(fn):
    """Read one of the prompt*.txt files and return its contents as a string."""
    with open(fn, encoding="utf-8") as f:
        return f.read()


def extract_tags(client, comment, draft):
    """Ask GPT to label the comment/draft with a handful of tone tags.

    These tags (e.g. "defensive", "curious") are later used to pick relevant
    strategies from strategies.json. Returns an empty list if the call or
    the JSON parsing fails, so the rest of the app can carry on without tags.
    """
    # str.format(...) fills in the {comment} and {draft} placeholders inside
    # prompt1.txt with the actual values.
    prompt = load_prompt("prompt1.txt").format(comment=comment or "N/A", draft=draft or "N/A")
    try:
        r = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=TAG_EXTRACTION_TEMPERATURE,
            max_tokens=TAG_EXTRACTION_MAX_TOKENS,
        )
        return json.loads(r.choices[0].message.content.strip())
    except Exception:
        # logger.exception(...) records the full error details (including
        # where it happened) to the server logs, while st.warning(...)
        # shows a short, friendly message to the person using the app.
        logger.exception("Tag extraction failed")
        st.warning("⚠️ Tag extraction failed.")
        return []


def generate_reply(client, prompt, comment, draft):
    """Ask GPT to write (or improve) the persuasive reply.

    "prompt" is the full system prompt built by app.py (prompt2.txt plus the
    matched strategies, and any previous feedback). Returns the parsed JSON
    dict GPT replied with - e.g. {"message": ..., "explanation": ...}.
    """
    r = client.chat.completions.create(
        model=MODEL_NAME,
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
    txt = r.choices[0].message.content
    return parse_json_object(txt)


def generate_rebuttal(client, reply: str, comment: str) -> str:
    """Ask GPT to play skeptic and push back on our own reply.

    Returns the rebuttal text, or an empty string if generation fails.
    """
    try:
        rebuttal_prompt = load_prompt("prompt3.txt").format(reply=reply, comment=comment)
        r = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    # Two string literals written next to each other like
                    # this are automatically joined into one string by
                    # Python - it's just a way to keep long lines short.
                    "content": (
                        "You are a skeptical, articulate critic of vegan "
                        "arguments, tasked with challenging the assistant’s "
                        "message."
                    ),
                },
                {"role": "user", "content": rebuttal_prompt},
            ],
            temperature=REPLY_TEMPERATURE,
            max_tokens=REBUTTAL_MAX_TOKENS,
        )
        parsed = parse_json_object(r.choices[0].message.content)
        return parsed.get("rebuttal", "[Rebuttal missing]")
    except Exception as e:
        logger.exception("Rebuttal generation failed")
        st.warning(f"⚠️ Rebuttal generation failed: {e}")
        return ""
