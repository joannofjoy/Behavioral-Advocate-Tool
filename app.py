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

from config import (
    MAX_GENERATIONS_PER_SESSION,
    MAX_INPUT_CHARS,
    STRATEGY_RETRIEVAL,
    TESTING_MODE,
)
from firebase_logger import init_firebase, log_to_firestore
from llm import (
    assess_engagement,
    extract_tags,
    generate_reply,
    get_llm_client,
    score_reply_quality,
)
from prompt_builder import MODE_FAMILY, MODE_ONLINE, MODE_STREET, MODES, build_reply_prompt
from retrieval import load_strategy_embeddings, select_strategies
from strategies import load_strategies

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


# The label and placeholder for the main text box change with the mode, so
# each one asks for the kind of input that actually makes sense for it.
MODE_INPUT_TEXT = {
    MODE_ONLINE: (
        "What did they say?",
        "Paste their comment here. You can add context too, like who they are "
        "or where it was posted.",
    ),
    MODE_STREET: (
        "What did they say, or which objection do you want to practice?",
        'e.g. "But humans have always eaten meat." You can add context too, '
        "like the setting or who you were talking to.",
    ),
    MODE_FAMILY: (
        "What did they say, and who are they to you?",
        "e.g. My dad said at dinner that veganism is just a trend.",
    ),
}

client = get_llm_client()
db = init_firebase()
strategies = load_strategies()


# @st.cache_resource runs this function once per server start and then
# hands back the same result on every rerun and to every visitor, instead
# of reloading the strategy embeddings each time someone clicks something.
@st.cache_resource
def get_strategy_vectors():
    """Embeddings for every strategy, used by ranked retrieval (retrieval.py)."""
    try:
        return load_strategy_embeddings(client, strategies)
    except Exception:
        # select_strategies() falls back to tag matching when this is None
        # and the embeddings still can't be loaded.
        return None


strategy_vectors = get_strategy_vectors() if STRATEGY_RETRIEVAL == "ranked" else None

# The steps shown in the "How it works" popup.
INSTRUCTION_STEPS = [
    "Pick what you're using it for: online comments, street outreach practice, "
    "or talking with family and friends.",
    "Paste what the other person said, plus any context that helps.",
    "Get a reply, along with a short explanation of the behavioral science technique behind it.",
    'Rate the reply and say what should change, then click "Revise this reply" '
    "for an improved version. Earlier versions are kept at the bottom.",
]


# @st.dialog is a decorator: it turns the function below it into a popup
# window. Calling show_instructions() opens the popup and runs the code
# inside it there, instead of on the main page.
@st.dialog("Welcome! Here's how it works")
def show_instructions():
    """Popup with short instructions for first-time visitors."""
    # enumerate(..., start=1) hands back each step together with its number,
    # starting the count at 1 instead of 0.
    st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(INSTRUCTION_STEPS, start=1)))
    if st.button("Got it", type="primary"):
        # Re-running the script is what closes the popup.
        st.rerun()


def reply_card_html(label, entry, show_context=True, show_draft=True):
    """Build the HTML for one version's card.

    "entry" is one item from st.session_state.history. The card shows, in
    order: a heading, a short line saying why this version exists (e.g.
    "Revised from version 1 using your feedback"), the user's own draft if
    they gave one, the reply, and the explanation in a tinted box.

    Everything shown here comes from the visitor or from the model (whose
    output is shaped by what the visitor typed), so none of it is fully
    trusted. html.escape(...) turns characters like < and > into harmless
    text (&lt;, &gt;), so they can never be read as real HTML tags or
    scripts once inserted into the page.
    """
    parts = [f"<div class='reply-card'><h4>{html.escape(label)}</h4>"]
    # .get() returns None instead of raising an error when a key is missing,
    # which keeps this working for history entries made before these
    # fields existed.
    if show_context and entry.get("context"):
        parts.append(f"<div class='context'>{html.escape(entry['context'])}</div>")
    if show_draft and entry.get("draft"):
        parts.append(
            f"<div class='draft'><span>Your draft</span>{html.escape(entry['draft'])}</div>"
        )
    parts.append(f"<p>{html.escape(entry['reply'])}</p>")
    if entry.get("what_changed"):
        parts.append(
            f"<div class='explain changed'><strong>"
            f"{html.escape(entry.get('what_changed_label', 'What changed'))}:</strong> "
            f"{html.escape(entry['what_changed'])}</div>"
        )
    # A clarifying question has no technique to explain.
    if not entry.get("is_clarification"):
        parts.append(
            f"<div class='explain'><strong>Why this works:</strong> "
            f"{html.escape(entry['explanation'])}</div>"
        )
    parts.append("</div>")
    return "".join(parts)


# ------------------- UI -------------------
# This block injects some custom CSS (styling rules) into the page - things
# Streamlit's theme settings (.streamlit/config.toml) don't cover, like the
# green title banner, the reply card, and tighter spacing.
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
    /* The green title banner at the top of the page. */
    .hero {
        background: linear-gradient(135deg, #0f766e 0%, #16a34a 100%);
        border-radius: 14px;
        padding: 1.25rem 1.4rem;
        color: #ffffff;
    }
    /* Streamlit's own stylesheet styles h1 with higher specificity than a
       plain selector, so !important is needed for these to actually win. */
    .hero h1 {
        color: #ffffff !important;
        font-size: 1.55rem !important;
        line-height: 1.2 !important;
        letter-spacing: -0.02em;
        margin: 0 0 0.35rem !important;
        padding: 0 !important;
    }
    .hero p { margin: 0; color: rgba(255, 255, 255, 0.9); font-size: 0.95rem; }
    h3 {
        font-size: 1.2rem !important;
        margin-top: 0.5rem !important;
        margin-bottom: 0.25rem !important;
    }
    /* The currently selected mode pill: solid green with white text, so it
       clearly stands out from the other two (Streamlit's default is a pale
       tint). aria-checked="true" is how Streamlit marks the selected one. */
    .st-key-mode_input button[aria-checked="true"] {
        background: #15803d !important;
        border-color: #15803d !important;
        color: #ffffff !important;
    }
    .st-key-mode_input button[aria-checked="true"] * { color: #ffffff !important; }
    /* The reply and its explanation: a white card with a green left edge. */
    .reply-card {
        background: #ffffff;
        border-left: 4px solid #15803d;
        border-radius: 14px;
        box-shadow: 0 4px 14px rgba(20, 60, 35, 0.08);
        padding: 1rem 1.1rem;
        margin-bottom: 0.25rem;
    }
    .reply-card h4 {
        margin: 0 0 0.4rem !important;
        padding: 0 !important;
        font-size: 0.72rem !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #15803d;
    }
    .reply-card p { margin: 0 0 0.75rem; }
    .reply-card .explain {
        background: #e6f4ea;
        border-radius: 10px;
        padding: 0.7rem 0.85rem;
        font-size: 0.88rem;
    }
    .reply-card .explain strong { color: #15803d; }
    /* "What changed" sits right above "Why this works", with a white
       background and green outline so the two boxes read as separate. */
    .reply-card .explain.changed {
        background: #ffffff;
        border: 1px solid #bfe3cb;
        margin-bottom: 0.5rem;
    }
    /* The short "why this version exists" line under a card's heading. */
    .reply-card .context {
        font-size: 0.82rem;
        color: #56655b;
        font-style: italic;
        margin: -0.2rem 0 0.6rem;
    }
    /* The user's own draft, shown above the improved reply for comparison. */
    .reply-card .draft {
        border: 1px dashed #c3d0c7;
        border-radius: 10px;
        padding: 0.55rem 0.8rem;
        margin-bottom: 0.75rem;
        font-size: 0.88rem;
        color: #56655b;
    }
    .reply-card .draft span {
        display: block;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.2rem;
    }
    /* "Earlier versions": scroll inside the box once the list gets long. */
    .st-key-earlier_versions { max-height: 32rem; overflow-y: auto; padding-right: 0.25rem; }
    /* Soft shadow on the filled green buttons, so the main actions pop. */
    [data-testid="stBaseButton-primary"] { box-shadow: 0 4px 12px rgba(21, 128, 61, 0.3); }
    .app-footer { text-align: center; font-size: 0.8rem; margin-top: 1.5rem; opacity: 0.7; }
    /* Streamlit puts a fairly generous default gap between every element
       on the page (the comment box, the button, each reply line, the
       feedback widgets, ...) - tightening it here is the single biggest
       lever for fitting more content in one screen without touching any
       individual element. */
    [data-testid="stVerticalBlock"] { gap: 0.5rem !important; }
    hr { margin: 0.5rem 0 !important; }
    div[data-testid="stButton"] button { padding-top: 0.25rem; padding-bottom: 0.25rem; }
    /* The draft box sits inside the "Optional: Your draft reply" expander,
       which already has its own frame - so the text box drops its border
       and background and the two read as one frame, not a box in a box.
       ":has(...)" picks out only the expander that contains the draft box. */
    .st-key-draft_input [data-testid="stTextAreaRootElement"],
    .st-key-draft_input [data-baseweb="textarea"],
    .st-key-draft_input textarea {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    [data-testid="stExpanderDetails"]:has(.st-key-draft_input) {
        padding: 0 0.4rem 0.4rem !important;
        border-top: 1px solid #d8e3dc;
    }
    </style>
"""
)

st.html(
    "<div class='hero'>"
    "<h1>Animal Advocacy Messaging Assistant</h1>"
    "<p>Talk about animals and veganism more persuasively - online, on the "
    "street, or with family - using behavioral science.</p>"
    "</div>"
)

# A small text-style button under the title that reopens the instructions.
if st.button("How it works", icon=":material/info:", type="tertiary", key="how_it_works"):
    show_instructions()
# On a visitor's first page load, open the instructions automatically.
# "seen_intro" stays set for the rest of the browser session (even after
# "New session", see below), so the popup only appears once.
elif "seen_intro" not in st.session_state:
    st.session_state.seen_intro = True
    show_instructions()

# st.segmented_control shows the options as a row of pill buttons.
# required=True stops the user from un-selecting the current option, which
# would otherwise leave no mode selected at all.
mode = st.segmented_control(
    "What are you using this for?",
    MODES,
    default=MODE_ONLINE,
    required=True,
    key="mode_input",
)

comment_label, comment_placeholder = MODE_INPUT_TEXT[mode]
comment = st.text_area(
    comment_label,
    key="comment_input",
    placeholder=comment_placeholder,
    height=80,
)

with st.expander("Optional: Your draft reply"):
    draft = st.text_area(
        "Your draft reply",
        key="draft_input",
        placeholder=(
            "Write your reply draft here, or leave blank for the assistant to generate it..."
        ),
        label_visibility="collapsed",
        height=80,
    )

if st.button("Generate a reply", type="primary"):
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
        # A fresh reply for whatever is in the input boxes right now, as
        # opposed to "Revise this reply", which revises the latest one.
        st.session_state.revising = False
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
        strats, matched_tags = select_strategies(
            client,
            strategies,
            tags,
            comment,
            draft,
            STRATEGY_RETRIEVAL,
            strategy_vectors=strategy_vectors,
            usage_log=usage_log,
        )
        prompt = build_reply_prompt(
            strats,
            mode=mode,
            worth_engaging=engagement.worth_engaging if engagement else True,
        )

        # Feedback only counts when the user clicked "Regenerate with
        # feedback" - a plain "Generate a reply" always starts fresh.
        revising = st.session_state.get("revising", False)
        feedback_txt = (st.session_state.get("feedback") or "").strip() if revising else ""
        rating_val = st.session_state.get("rating") if revising else None

        # The reply being revised: the most recent real reply (skipping any
        # clarifying questions). next(..., None) returns the first match from
        # the generator, or None if there isn't one.
        previous = next(
            (
                (i + 1, h)
                for i, h in reversed(list(enumerate(st.session_state.history)))
                if not h.get("is_clarification")
            ),
            None,
        )
        revision = None
        if revising and previous:
            prev_version, prev_entry = previous
            # Sent to the model alongside the comment and draft, so it can
            # actually see the reply it's being asked to improve.
            revision = {
                "previous_reply": prev_entry["reply"],
                "feedback": feedback_txt,
                "rating": rating_val,
            }
            if feedback_txt:
                context = (
                    f'Revised from version {prev_version} using your feedback: "{feedback_txt}"'
                )
            else:
                context = f"A different take on version {prev_version}"
            if rating_val is not None:
                context += f" (you rated it {rating_val}/5)"
        elif not st.session_state.history:
            context = "First reply"
        elif (
            json.dumps({"comment": comment, "draft_reply": draft})
            != (st.session_state.history[-1]["user_input"])
        ):
            context = "New reply for your updated input"
        else:
            context = "New reply for the same input"

        parsed = generate_reply(
            client, prompt, comment, draft, usage_log=usage_log, revision=revision
        )

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
                    "is_clarification": True,
                    "context": "The assistant needs a bit more information",
                    "draft": draft.strip(),
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
                use_case=mode,
                worth_engaging=engagement.worth_engaging if engagement else None,
                engagement_reason=engagement.reason if engagement else None,
                is_test=TESTING_MODE,
            )
            st.session_state.run = False
            st.session_state.revising = False
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
                # Why this version exists, shown above it (see "context" above).
                "context": context,
                # The model's note on what it changed, and what it's
                # comparing against (the previous version or the user's draft).
                "what_changed": parsed.what_changed if (revision or draft.strip()) else "",
                "what_changed_label": (
                    f"What changed from version {previous[0]}"
                    if revision
                    else "What changed from your draft"
                ),
                # The user's own draft, if any, shown above the reply so the
                # two are easy to compare.
                "draft": draft.strip(),
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
            use_case=mode,
            worth_engaging=engagement.worth_engaging if engagement else None,
            engagement_reason=engagement.reason if engagement else None,
            quality_scores=quality_scores.model_dump(),
            what_changed=parsed.what_changed,
            is_test=TESTING_MODE,
        )

        st.session_state.run = False
        st.session_state.revising = False
        st.session_state.rating = None
        st.session_state.feedback = None
        st.session_state.rating_touched = False
        # Empty the stars and the feedback box, so feedback on this version
        # isn't silently reused the next time the user regenerates. Setting a
        # widget's key here works because those widgets are only drawn
        # further down the script.
        st.session_state.rating_input = None
        st.session_state.fb_input = ""

if st.session_state.history:
    history = st.session_state.history
    latest = history[-1]
    total = len(history)

    # The newest version always comes first, in full. Earlier versions are
    # tucked away at the bottom of the page (see "Earlier versions" below).
    if latest.get("engagement_reason"):
        st.warning(
            f"⚠️ This comment may not be worth a full persuasive reply: "
            f"{latest['engagement_reason']} The reply below sticks to stating "
            f"values and correcting facts rather than trying to persuade."
        )
    latest_label = "Reply" if total == 1 else f"Version {total} · latest"
    st.markdown(
        reply_card_html(latest_label, latest, show_context=total > 1), unsafe_allow_html=True
    )

    st.markdown("### How was this reply?")
    # st.feedback("stars") is Streamlit's purpose-built rating widget - a
    # compact row of star icons instead of a full-width slider, and it
    # natively returns None until the user actually clicks one (unlike the
    # old slider, which always reported a default value of 3 whether
    # touched or not). "stars" returns a 0-based index (0 = one star), so
    # +1 converts it back to the 1-5 scale the rest of the app expects.
    stars = st.feedback("stars", key="rating_input", on_change=_mark_rating_touched)
    rate = stars + 1 if stars is not None else None
    fb = st.text_area(
        "What should change? (optional)",
        key="fb_input",
        height=68,
        placeholder="e.g. Make it shorter, or less formal",
    )
    # Only treat the rating as real if a star was actually clicked -
    # otherwise nothing has been selected yet, not a deliberate opinion,
    # and shouldn't be logged as though it were one.
    st.session_state.rating = rate if st.session_state.rating_touched else None
    st.session_state.feedback = fb

    # Two buttons side by side; st.columns returns one column per entry.
    regen_col, new_col = st.columns([1, 1])
    with regen_col:
        regenerate = st.button(
            "Revise this reply",
            icon=":material/refresh:",
            type="primary",
            use_container_width=True,
        )
    with new_col:
        new_session = st.button("New session", icon=":material/add:", use_container_width=True)

    if regenerate:
        st.session_state.run = True
        st.session_state.revising = True
        st.rerun()

    if new_session:
        # Delete every key in session_state, which wipes the conversation
        # history, session id, etc. - the next re-run then falls through to
        # the "if ... not in st.session_state" checks near the top of this
        # file and starts fresh. "seen_intro" is kept, so the instructions
        # popup doesn't reappear for someone who has already read it.
        for key in list(st.session_state.keys()):
            if key != "seen_intro":
                del st.session_state[key]
        st.rerun()

    if total > 1:
        # Older versions, newest first, collapsed by default. The keyed
        # container gets a max height in the CSS above, so a long list
        # scrolls inside the box instead of making the page very long.
        with st.expander(f"Earlier versions ({total - 1})"):
            with st.container(key="earlier_versions"):
                # range(total - 1, 0, -1) counts down: total-1, ..., 2, 1.
                for version in range(total - 1, 0, -1):
                    st.markdown(
                        reply_card_html(
                            f"Version {version}",
                            history[version - 1],
                            # Only repeat the draft if it differs from the
                            # one shown with the latest version.
                            show_draft=history[version - 1].get("draft") != latest.get("draft"),
                        ),
                        unsafe_allow_html=True,
                    )

# Footer shown on every page load, below everything else - a link back to
# the source code on GitHub.
st.markdown(
    "<div class='app-footer'>"
    "<a href='https://github.com/joannofjoy/Behavioral-Advocate-Tool' target='_blank'>"
    "View the source on GitHub</a></div>",
    unsafe_allow_html=True,
)
