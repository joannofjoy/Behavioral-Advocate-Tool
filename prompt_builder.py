# Builds the full instructions ("system prompt") sent to the model when it
# writes a reply: the main prompt in prompt2.txt, plus the matched
# strategies, plus any extra guidance for the chosen mode or for a comment
# flagged as not worth a full persuasive reply.
#
# This lives in its own file, rather than inside app.py, so the eval in
# eval/run_eval.py can build exactly the same prompt the live app does.
# If the two built their prompts separately, the eval would slowly drift
# away from what users actually get, and stop catching real problems.

from llm import load_prompt

# The three things the app can be used for. The main prompt (prompt2.txt)
# is written for online comments, so that mode needs no extra instructions;
# the other two get a short block of guidance put in front of the prompt
# that changes what kind of message to write.
#
# - Online comments: a one-off exchange with a stranger, in writing.
# - Street outreach: an activist practicing what to say out loud to a
#   passer-by, so the reply has to work as spoken words.
# - Family & friends: an ongoing relationship, so keeping things warm
#   matters more than winning this one conversation.
MODE_ONLINE = "Online comments"
MODE_STREET = "Street outreach practice"
MODE_FAMILY = "Family & friends"
MODES = [MODE_ONLINE, MODE_STREET, MODE_FAMILY]

MODE_GUIDANCE = {
    MODE_STREET: (
        "You are helping an activist prepare for in-person street outreach (for "
        "example, talking with a passer-by at an outreach stall or demonstration), "
        "not write an online comment. Write the message as words to be said out "
        "loud: short, natural spoken sentences, no links, no references to 'your "
        "comment' or 'this post', and nothing that sounds scripted or recited. "
        "Street conversations are a back-and-forth, so keep it brief and usually "
        "end with a genuine, open question that invites the person to keep "
        "talking.\n\n"
    ),
    MODE_FAMILY: (
        "You are helping reply to someone the user actually knows well - a family "
        "member, friend, or similar - not an anonymous stranger online. This is an "
        "ongoing relationship, not a one-off exchange, so prioritize preserving "
        "warmth and long-term openness over winning this specific exchange. It's "
        "fine to plant a seed rather than push for full conversion right now, and "
        "avoid anything that would sting coming from someone they're close to. "
        "Write the message so it works either said out loud or sent as a text.\n\n"
    ),
}

# Extra instructions added at the very end of the prompt rather than the
# start. The main prompt has its own rules for the explanation field ("2-4
# sentences..."), and the model tends to follow whichever instruction it
# read last - a request placed at the start kept getting ignored.
MODE_EXPLANATION_ADDON = {
    MODE_STREET: (
        "\n\nFor this street outreach reply, the explanation field must end with "
        "one extra sentence starting with 'Delivery tip:' that gives the activist "
        "one practical tip for saying this face to face (tone, pacing, or when to "
        "pause and let the other person think)."
    ),
}

# Put in front of the prompt when assess_engagement() flags the comment
# (bad-faith engagement, explicit refusal to discuss, or extreme
# entrenchment) - research on these situations suggests a full persuasive
# push is unlikely to help and can even backfire, so the reply shifts to
# something much smaller: state values calmly, correct any factual
# inaccuracy once, and stop there.
LOW_ENGAGEMENT_MODE_BLOCK = (
    "This comment has been flagged as unlikely to benefit from a persuasive reply "
    "(bad-faith engagement, an explicit refusal to discuss this topic, or extreme "
    "entrenchment where persuasion attempts risk pushing someone further away "
    "instead of closer). Do NOT attempt to persuade, convince, or debate. Instead:\n"
    "- Briefly and calmly state your values in a positive, non-confrontational way, "
    "not a counter-argument.\n"
    "- If the comment contains a factual inaccuracy, correct it once, respectfully, "
    "without elaborating further.\n"
    "- Do not ask questions, invite further discussion, or try to change their mind.\n"
    "- Keep it to 1-2 sentences, shorter than a normal reply.\n\n"
)


def format_strategies(strats):
    """Turn the matched strategies into the bullet list prompt2.txt expects.

    Each line includes the strategy's source (e.g. "Faunalytics", "Paul
    Slovic") alongside its description, because the explanation is meant to
    teach the user something, and naming where a technique comes from makes
    that explanation genuinely informative.
    """
    lines = [f"- {s['title']} (source: {s['source']}): {s['description']}" for s in strats]
    # "or" falls back to the right-hand side when the left is empty: an
    # empty list joins into "", which counts as false.
    return "\n".join(lines) or "No strategies matched."


def build_reply_prompt(strats, mode=MODE_ONLINE, worth_engaging=True):
    """Assemble the full reply-generation prompt.

    "strats" are the matched strategies, "mode" is one of MODES, and
    "worth_engaging" is False when assess_engagement() flagged the comment.
    The order matters: flag and mode guidance go first, then the main
    prompt, then any mode-specific rule for the explanation field at the end.
    """
    base_prompt = load_prompt("prompt2.txt").format(formatted_strategies=format_strategies(strats))
    low_engagement_block = "" if worth_engaging else LOW_ENGAGEMENT_MODE_BLOCK
    return (
        low_engagement_block
        + MODE_GUIDANCE.get(mode, "")
        + base_prompt
        + MODE_EXPLANATION_ADDON.get(mode, "")
    )
