# GPT is asked to answer in JSON, but it doesn't always send back *just*
# JSON - sometimes it wraps the answer in a "```json ... ```" code block, or
# adds a sentence of chit-chat before or after it. This file's one function
# cleans that up and gives back a real Python dictionary.

import json
import re


def parse_json_object(text: str) -> dict:
    """Pull a JSON object out of a GPT response and parse it into a dict.

    Handles two messy cases GPT sometimes produces:
    1. The JSON wrapped in a markdown code fence, e.g. ```json ... ```
    2. Extra text before/after the JSON object itself.
    """
    text = text.strip()

    # If the response starts with a code fence, strip the fence markers off.
    # re.sub(pattern, replacement, text) finds every part of "text" matching
    # "pattern" and swaps it for "replacement". The pattern here matches
    # a fence at the very start of the text (^```json or ^```) OR one at the
    # very end (```$); flags=re.MULTILINE makes "^" and "$" match the start
    # and end of each line, not just the start/end of the whole string.
    if text.startswith("```json") or text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    # Even after removing fences, there can still be stray text around the
    # JSON object. re.search looks for the first place in "text" that matches
    # the pattern; "\{.*\}" means "a { followed by anything, followed by a
    # }", and re.DOTALL makes "." also match newlines, so this grabs
    # everything from the first { to the last } in the whole response.
    match = re.search(r"\{.*\}", text, re.DOTALL)

    # match.group(0) is the actual matched text (the JSON object as a
    # string); json.loads turns that string into a real Python dict.
    return json.loads(match.group(0))
