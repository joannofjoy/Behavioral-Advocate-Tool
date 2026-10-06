# This is the Streamlit app itself: everything the user sees and clicks on.
# It doesn't talk to OpenAI or Firebase directly - that logic lives in
# llm.py and firebase_logger.py - this file just wires the UI up to those
# modules and keeps track of the conversation as the user interacts with it.
#
# Streamlit re-runs this entire script from top to bottom every time the
# user does something (types text, clicks a button, moves a slider). To
# remember things between those re-runs (like the conversation history),
# Streamlit gives every user session a dictionary called
# st.session_state that keeps its values across re-runs.

import html
import json
import uuid

import streamlit as st

from config import MAX_GENERATIONS_PER_SESSION, MAX_INPUT_CHARS, TESTING_MODE
from firebase_logger import init_firebase, log_to_firestore
from llm import (
    assess_engagement,
    extract_tags,
    generate_reply,
    get_llm_client,
    load_prompt,
    score_reply_quality,
)
from strategies import filter_strategies_by_tags, load_strategies

# Give this browser session a unique ID (used to group its log entries in
# Firestore), but only the first time this code runs for this session -
# "not in st.session_state" is False on every later re-run, so the ID stays
# the same for as long as the user keeps this tab open.
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "history" not in st.session_state:
    st.session_state.history = []  # list of reply blocks
if "generation_count" not in st.session_state:
    st.session_state.generation_count = 0  # replies generated so far this session
if "rating_touched" not in st.session_state:
    st.session_state.rating_touched = False  # did the user actually move the rating slider?


def _mark_rating_touched():
    """Set when the rating slider's on_change fires - i.e. the user actually
    dragged it, as opposed to it just sitting at its default value. Without
    this, hitting "Regenerate" without touching the slider silently logs a
    rating of 3 as if the user had deliberately chosen it.
    """
    st.session_state.rating_touched = True


# The two options for "who is this reply going to," and the extra prompt
# instruction added for the second one. A stranger online is a one-off
# exchange; someone the user actually knows is an ongoing relationship, so
# the tone guidance shifts accordingly - family, friends, and partners all
# get lumped into one "someone I know" option rather than separate ones,
# since the real distinction that changes the advice is "ongoing
# relationship vs. one-off," not the exact kind of relationship.
AUDIENCE_STRANGER = "A stranger online"
AUDIENCE_KNOWN = "Someone I know (family, friend, etc.)"

RELATIONSHIP_GUIDANCE = {
    AUDIENCE_KNOWN: (
        "You are helping reply to someone the user actually knows well - a family "
        "member, friend, or similar - not an anonymous stranger online. This is an "
        "ongoing relationship, not a one-off exchange, so prioritize preserving "
        "warmth and long-term openness over winning this specific exchange. It's "
        "fine to plant a seed rather than push for full conversion right now, and "
        "avoid anything that would sting coming from someone they're close to.\n\n"
    ),
}

# Prepended to the prompt instead of the normal persuasion instructions
# when assess_engagement() flags the comment (bad-faith engagement,
# explicit refusal to discuss, or extreme entrenchment) - research on these
# situations suggests a full persuasive push is unlikely to help and can
# even backfire, so the reply shifts to something much smaller: state
# values calmly, correct any factual inaccuracy once, and stop there.
LOW_ENGAGEMENT_MODE_BLOCK = (
    "This comment has been flagged as unlikely to benefit from a persuasive reply "
    "(bad-faith engagement, an explicit refusal to discuss this topic, or extreme "
    "entrenchment where persuasion attempts risk pushing someone further away "
    "instead of closer). Do NOT attempt to persuade, convince, or debate. Instead:\n"
    "- Briefly and calmly state your values in a positive, non-confrontational way, not a counter-argument.\n"  # noqa: E501
    "- If the comment contains a factual inaccuracy, correct it once, respectfully, without elaborating further.\n"  # noqa: E501
    "- Do not ask questions, invite further discussion, or try to change their mind.\n"
    "- Keep it to 1-2 sentences, shorter than a normal reply.\n\n"
)


client = get_llm_client()
db = init_firebase()
strategies = load_strategies()

# ------------------- UI -------------------
# This block injects some custom CSS (styling rules) into the page - things
# Streamlit doesn't offer built-in controls for, like tightening up the
# spacing above the title and making the reply text a bit smaller.
#
# st.html() (rather than st.markdown with unsafe_allow_html) is the
# correct way to inject a <style> tag - Streamlit sanitizes <style> tags
# out of st.markdown's HTML, so that older pattern silently does nothing.
st.html(
    """
    <style>
    /* Streamlit's floating header toolbar (the hamburger/Deploy menu) is
       fixed at the top of the page and about 60px tall - padding-top needs
       to clear it, or the title renders mostly hidden underneath it. */
    .block-container { padding-top: 4rem; padding-bottom: 1rem; }
    /* Streamlit's own stylesheet styles h1 with higher specificity than a
       plain tag selector, so !important is needed for this to actually win. */
    h1 { font-size: 1.5rem !important; margin-bottom: 0.25rem !important; }
    h3 { margin-top: 0.5rem !important; margin-bottom: 0.25rem !important; }
    .reply-line { font-size: 0.9rem; margin-bottom: 0.4rem; }
    .reply-label { font-weight: bold; margin-right: 0.25rem; }
    /* Streamlit puts a fairly generous default gap between every element
       on the page (the comment box, the button, each reply line, the
       feedback widgets, ...) - tightening it here is the single biggest
       lever for fitting more content in one screen without touching any
       individual element. */
    [data-testid="stVerticalBlock"] { gap: 0.5rem !important; }
    hr { margin: 0.5rem 0 !important; }
    div[data-testid="stButton"] button { padding-top: 0.25rem; padding-bottom: 0.25rem; }
    /* Streamlit auto-stacks st.columns() into separate rows below a width
       breakpoint, which would break the ◀ / "Previous Versions" / ▶ row
       into three disconnected blocks on mobile. The "version_nav" keyed
       container (wrapped around just that row in app.py) gets a
       ".st-key-version_nav" class we can scope this override to, without
       touching any other column layout in the app - !important is needed
       here because Streamlit's own responsive rule wins otherwise. */
    .st-key-version_nav [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; }
    .st-key-version_nav [data-testid="stColumn"] {
        width: auto !important;
        min-width: 0 !important;
    }
    .st-key-version_nav [data-testid="stColumn"]:nth-of-type(1),
    .st-key-version_nav [data-testid="stColumn"]:nth-of-type(3) { flex: 1 1 0 !important; }
    .st-key-version_nav [data-testid="stColumn"]:nth-of-type(2) { flex: 3.5 1 0 !important; }
    </style>
"""
)

st.markdown("# Animal Advocacy Messaging Assistant")
st.write(
    "This tool helps improve social media comments for better "
    "persuasiveness using behavioral science."
)

audience = st.radio(
    "Who are you replying to?",
    [AUDIENCE_STRANGER, AUDIENCE_KNOWN],
    key="audience_input",
    horizontal=True,
)

comment = st.text_area(
    "What did the other person say? Who are they? Any additional context?",
    key="comment_input",
    placeholder="Paste the other person's comment and add any additional context here...",
    height=80,
)

with st.expander("Optional: Your draft reply"):
    draft = st.text_area(
        "",
        key="draft_input",
        placeholder=(
            "Write your reply draft here, or leave blank for the assistant to generate it..."
        ),
        label_visibility="collapsed",
        height=80,
    )

if st.button("Generate a reply"):
    if not comment.strip() and not draft.strip():
        st.warning("Enter context or draft.")
    elif len(comment) > MAX_INPUT_CHARS or len(draft) > MAX_INPUT_CHARS:
        st.warning(f"Please keep each field under {MAX_INPUT_CHARS} characters.")
    else:
        # Setting this flag and calling st.rerun() immediately re-runs the
        # script from the top. We do this (instead of just continuing
        # below) so the "Thinking..." spinner further down shows up right
        # away, on its own re-run, rather than only after the whole button
        # click's work is already done.
        st.session_state.run = True
        st.rerun()

if st.session_state.get("run") and st.session_state.generation_count >= MAX_GENERATIONS_PER_SESSION:
    st.warning(
        f"You've reached the {MAX_GENERATIONS_PER_SESSION}-reply limit for this session. "
        "Start a new session to continue."
    )
    st.session_state.run = False

if st.session_state.get("run"):
    st.session_state.generation_count += 1
    # st.spinner shows a small loading animation for as long as the
    # indented block underneath it is still running.
    with st.spinner("Thinking..."):
        session_id = st.session_state["session_id"]
        # Collects token/cost info from every LLM call made during this one
        # interaction (tags, engagement assessment, and reply), so the
        # totals can be logged alongside the rest of the record. See
        # llm.py's _record_usage for what each entry looks like.
        usage_log = []
        tags = extract_tags(client, comment.strip(), draft.strip(), usage_log=usage_log)
        # Only worth assessing when there's an actual comment to read - a
        # draft-only input has no other person's comment to judge for bad
        # faith, explicit refusal, or entrenchment.
        engagement = (
            assess_engagement(client, comment.strip(), usage_log=usage_log)
            if comment.strip()
            else None
        )
        strats, matched_tags = filter_strategies_by_tags(strategies, tags)
        # Includes each strategy's source (e.g. "Faunalytics", "Paul
        # Slovic") alongside its description, not just the description
        # alone - the explanation field is meant to teach the user
        # something, and naming where a technique comes from makes that
        # explanation genuinely informative rather than a vague summary.
        strat_block = (
            "\n".join(f"- {s['title']} (source: {s['source']}): {s['description']}" for s in strats)
            or "No strategies matched."
        )

        base_prompt = load_prompt("prompt2.txt").format(formatted_strategies=strat_block)

        feedback_txt = st.session_state.get("feedback", "").strip()
        rating_val = st.session_state.get("rating")

        relationship_block = RELATIONSHIP_GUIDANCE.get(audience, "")
        low_engagement_block = (
            LOW_ENGAGEMENT_MODE_BLOCK if engagement and not engagement.worth_engaging else ""
        )

        if feedback_txt or rating_val is not None:
            feedback_block = (
                f"You just received the following feedback on your previous reply:\n"
                f'- Written feedback: "{feedback_txt}"\n'
                f"- Rating: {rating_val}/5\n\n"
                f"Revise your reply accordingly before applying the rest of the instructions. You should still ask for clarifictaion if the input is not relate dto animal advocacy. \n"  # noqa: E501
                f"If the rating is under 4, that means the user wasn’t fully satisfied — make sure to address their concerns. The lower the rating, the more you should change the reply. \n"  # noqa: E501
                f"After applying the feedback, in <explanation> field include describing how you changed the reply in response to the feedback. If you did not include any part of the feedback, explain why. \n"  # noqa: E501
            )

            prompt = low_engagement_block + relationship_block + feedback_block + "\n" + base_prompt
        else:
            prompt = low_engagement_block + relationship_block + base_prompt

        parsed = generate_reply(client, prompt, comment, draft, usage_log=usage_log)

        user_in = json.dumps({"comment": comment, "draft_reply": draft})
        itype = parsed.input_type
        msg = parsed.message or parsed.follow_up_question
        expl = parsed.explanation or ("Needs clarification" if parsed.needs_clarification else "")
        just = []
        if parsed.needs_clarification:
            st.session_state.history.append(
                {
                    "reply": msg,
                    "explanation": expl,
                    "user_input": user_in,
                    "input_type": itype,
                    "tags": tags,
                    "justification": just,
                    "matched_tags": matched_tags,
                    "strategies": strats,
                    "confidence_score": None,
                    "evaluation_justification": None,
                    "suggested_improvements": None,
                    "ultimate_reply": None,
                    "session_id": session_id,
                }
            )

            log_to_firestore(
                db,
                version=len(st.session_state.history),
                user_input=user_in,
                input_type=itype,
                message=msg,
                explanation=expl,
                tags_input=tags,
                tags_justification=just,
                matched_tags=matched_tags,
                matched_tags_in_strategies=matched_tags,
                strategies=strats,
                rating=rating_val,
                rating_confirmed=st.session_state.rating_touched,
                written_feedback=feedback_txt,
                session_id=session_id,
                usage_details=usage_log,
                tokens_used=sum(u["total_tokens"] or 0 for u in usage_log),
                cost_usd=sum(u["cost"] or 0 for u in usage_log),
                relationship_context=audience,
                worth_engaging=engagement.worth_engaging if engagement else None,
                engagement_reason=engagement.reason if engagement else None,
                is_test=TESTING_MODE,
            )
            st.session_state.run = False
            st.rerun()

        # Quietly score the reply for internal quality monitoring - never
        # shown in the UI, just logged for later analysis. Uses a separate
        # fixed judge model (see llm.score_reply_quality) rather than the
        # model that wrote the reply.
        quality_scores = score_reply_quality(client, comment, msg, usage_log=usage_log)

        st.session_state.history.append(
            {
                "reply": msg,
                "explanation": expl,
                "user_input": user_in,
                "input_type": itype,
                "tags": tags,
                "justification": just,
                "matched_tags": matched_tags,
                "strategies": strats,
                "session_id": session_id,
                "engagement_reason": (
                    engagement.reason if engagement and not engagement.worth_engaging else None
                ),
            }
        )
        if len(st.session_state.history) > 1:
            st.session_state.history_index = len(st.session_state.history) - 2

        log_to_firestore(
            db,
            version=len(st.session_state.history),
            user_input=user_in,
            input_type=itype,
            message=msg,
            explanation=expl,
            tags_input=tags,
            tags_justification=just,
            matched_tags=matched_tags,
            matched_tags_in_strategies=matched_tags,
            strategies=strats,
            rating=rating_val,
            rating_confirmed=st.session_state.rating_touched,
            written_feedback=feedback_txt,
            session_id=session_id,
            usage_details=usage_log,
            tokens_used=sum(u["total_tokens"] or 0 for u in usage_log),
            cost_usd=sum(u["cost"] or 0 for u in usage_log),
            relationship_context=audience,
            worth_engaging=engagement.worth_engaging if engagement else None,
            engagement_reason=engagement.reason if engagement else None,
            quality_scores=quality_scores.model_dump(),
            is_test=TESTING_MODE,
        )

        st.session_state.run = False
        st.session_state.rating = None
        st.session_state.feedback = None
        st.session_state.rating_touched = False

if st.session_state.history:
    if len(st.session_state.history) == 1:
        # Only one reply exists yet, so just show it - no need for the
        # "previous versions" browser below.
        #
        # The reply/explanation text below comes from GPT, and
        # GPT's output is itself shaped by whatever the visitor typed in as
        # the comment/draft - so it isn't fully trusted. html.escape(...)
        # converts characters like < and > into their safe HTML entities
        # (&lt;, &gt;) so that text can never be interpreted as actual HTML
        # tags/scripts when it's inserted into the page below.
        latest = st.session_state.history[-1]
        if latest.get("engagement_reason"):
            st.warning(
                f"⚠️ This comment may not be worth a full persuasive reply: "
                f"{latest['engagement_reason']} The reply below sticks to stating "
                f"values and correcting facts rather than trying to persuade."
            )
        st.markdown(
            f"<div class='reply-line'><span class='reply-label'>Reply:</span>"
            f"{html.escape(latest['reply'])}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='reply-line'><span class='reply-label'>Explanation:</span>"
            f"{html.escape(latest['explanation'])}</div>",
            unsafe_allow_html=True,
        )

    else:
        # More than one reply exists (the user regenerated at least once),
        # so show the latest reply next to a small browser for earlier ones.
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown(
                "<div style='text-align:center; font-weight:bold;'>Latest Version</div><br>",
                unsafe_allow_html=True,
            )
            latest = st.session_state.history[-1]
            if latest.get("engagement_reason"):
                st.warning(
                    f"⚠️ This comment may not be worth a full persuasive reply: "
                    f"{latest['engagement_reason']} The reply below sticks to stating "
                    f"values and correcting facts rather than trying to persuade."
                )
            st.markdown(
                f"<div class='reply-line'><span class='reply-label'>Latest Reply:</span>"
                f"{html.escape(latest['reply'])}</div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='reply-line'><span class='reply-label'>Explanation:</span>"
                f"{html.escape(latest['explanation'])}</div>",
                unsafe_allow_html=True,
            )

        with col2:
            total_versions = len(st.session_state.history) - 1  # Exclude latest

            if total_versions > 0:
                if "history_index" not in st.session_state:
                    st.session_state.history_index = 0

                # st.columns() normally stacks into separate rows on narrow
                # screens, which would break up the ◀ / label / ▶ row into
                # three disconnected blocks on mobile. Wrapping it in a
                # keyed container gives Streamlit's generated markup a
                # distinctive CSS class (".st-key-version_nav") that the
                # scoped rule up in the st.html() block at the top of this
                # file uses to force this one row to stay horizontal,
                # without affecting any other column layout in the app.
                with st.container(key="version_nav"):
                    col_l, col_m, col_r = st.columns([1, 3.5, 1])
                    with col_l:
                        # on_click takes a function to run when the button
                        # is pressed. Here that function is a "lambda" - a
                        # small, unnamed function written inline - which
                        # moves the history browser one step back, but
                        # never below 0.
                        st.button(
                            " ◀ ",
                            key="prev_btn",
                            on_click=lambda: st.session_state.update(
                                {"history_index": max(0, st.session_state.history_index - 1)}
                            ),
                            use_container_width=True,
                        )
                    with col_m:
                        st.markdown(
                            "<div style='text-align:center; font-weight:bold;'>"
                            "Previous Versions</div>",
                            unsafe_allow_html=True,
                        )
                    with col_r:
                        st.button(
                            " ▶ ",
                            key="next_btn",
                            on_click=lambda: st.session_state.update(
                                {
                                    "history_index": min(
                                        total_versions - 1,
                                        st.session_state.history_index + 1,
                                    )
                                }
                            ),
                            use_container_width=True,
                        )

                selected = st.session_state.history[st.session_state.history_index]
                st.markdown(
                    f"<div class='reply-line'>"
                    f"<span class='reply-label'>"
                    f"Reply Version {st.session_state.history_index + 1}:</span>"
                    f"{html.escape(selected['reply'])}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='reply-line'><span class='reply-label'>Explanation:</span>"
                    f"{html.escape(selected['explanation'])}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.info("No previous versions yet.")

    st.markdown("---")
    st.markdown("### Feedback")
    # st.feedback("stars") is Streamlit's purpose-built rating widget - a
    # compact row of star icons instead of a full-width slider, and it
    # natively returns None until the user actually clicks one (unlike the
    # old slider, which always reported a default value of 3 whether
    # touched or not). "stars" returns a 0-based index (0 = one star), so
    # +1 converts it back to the 1-5 scale the rest of the app expects.
    stars = st.feedback("stars", key="rating_input", on_change=_mark_rating_touched)
    rate = stars + 1 if stars is not None else None
    fb = st.text_area("Optional feedback (used only if you regenerate):", key="fb_input", height=68)
    # Only treat the rating as real if a star was actually clicked -
    # otherwise nothing has been selected yet, not a deliberate opinion,
    # and shouldn't be logged as though it were one.
    st.session_state.rating = rate if st.session_state.rating_touched else None
    st.session_state.feedback = fb

    if st.button("🔁 Regenerate with feedback"):
        st.session_state.run = True
        st.rerun()

    if st.button("🆕 New session"):
        # Delete every key currently in session_state, which wipes the
        # conversation history, session id, etc. - the next re-run then
        # falls through to the "if ... not in st.session_state" checks near
        # the top of this file and starts fresh.
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
