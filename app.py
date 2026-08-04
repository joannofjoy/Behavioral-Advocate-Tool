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

from firebase_logger import init_firebase, log_to_firestore
from llm import extract_tags, generate_rebuttal, generate_reply, get_openai_client, load_prompt
from strategies import filter_strategies_by_tags, load_strategies

# Give this browser session a unique ID (used to group its log entries in
# Firestore), but only the first time this code runs for this session -
# "not in st.session_state" is False on every later re-run, so the ID stays
# the same for as long as the user keeps this tab open.
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "history" not in st.session_state:
    st.session_state.history = []  # list of reply blocks

client = get_openai_client()
db = init_firebase()
strategies = load_strategies()

# ------------------- UI -------------------
# This block injects some custom CSS (styling rules) into the page - things
# Streamlit doesn't offer built-in controls for, like tightening up the
# spacing above the title and making the reply text a bit smaller.
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    .reply-line { font-size: 0.9rem; margin-bottom: 0.5rem; }
    .reply-label { font-weight: bold; margin-right: 0.25rem; }
    </style>
""",
    unsafe_allow_html=True,
)

st.markdown("## Animal Advocacy Messaging Assistant")
st.write(
    "This tool helps improve social media comments for better "
    "persuasiveness using behavioral science."
)

comment = st.text_area(
    "What did the other person say? Who are they? Any additional context?",
    key="comment_input",
    placeholder="Paste the other person's comment and add any additional context here...",
)

with st.expander("Optional: Your draft reply"):
    draft = st.text_area(
        "",
        key="draft_input",
        placeholder=(
            "Write your reply draft here, or leave blank for the assistant to generate it..."
        ),
        label_visibility="collapsed",
    )

if st.button("Generate a reply"):
    if not comment.strip() and not draft.strip():
        st.warning("Enter context or draft.")
    else:
        # Setting this flag and calling st.rerun() immediately re-runs the
        # script from the top. We do this (instead of just continuing
        # below) so the "Thinking..." spinner further down shows up right
        # away, on its own re-run, rather than only after the whole button
        # click's work is already done.
        st.session_state.run = True
        st.rerun()

if st.session_state.get("run"):
    # st.spinner shows a small loading animation for as long as the
    # indented block underneath it is still running.
    with st.spinner("Thinking..."):
        session_id = st.session_state["session_id"]
        tags = extract_tags(client, comment.strip(), draft.strip())
        strats, matched_tags = filter_strategies_by_tags(strategies, tags)
        strat_block = (
            "\n".join(f"- {s['title']}: {s['description']}" for s in strats)
            or "No strategies matched."
        )

        base_prompt = load_prompt("prompt2.txt").format(formatted_strategies=strat_block)

        feedback_txt = st.session_state.get("feedback", "").strip()
        rating_val = st.session_state.get("rating")

        if feedback_txt or rating_val is not None:
            feedback_block = (
                f"You just received the following feedback on your previous reply:\n"
                f'- Written feedback: "{feedback_txt}"\n'
                f"- Rating: {rating_val}/5\n\n"
                f"Revise your reply accordingly before applying the rest of the instructions. You should still ask for clarifictaion if the input is not relate dto animal advocacy. \n"  # noqa: E501
                f"If the rating is under 4, that means the user wasn’t fully satisfied — make sure to address their concerns. The lower the rating, the more you should change the reply. \n"  # noqa: E501
                f"After applying the feedback, in <explanation> field include describing how you changed the reply in response to the feedback. If you did not include any part of the feedback, explain why. \n"  # noqa: E501
            )

            prompt = feedback_block + "\n" + base_prompt
        else:
            prompt = base_prompt

        parsed = generate_reply(client, prompt, comment, draft)

        user_in = json.dumps({"comment": comment, "draft_reply": draft})
        itype = parsed.get("input_type", "unknown")
        msg = parsed.get("message", parsed.get("follow_up_question", ""))
        expl = parsed.get("explanation") or (
            "Needs clarification" if parsed.get("needs_clarification") else ""
        )
        just = parsed.get("tags", [])
        if parsed.get("needs_clarification"):
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
                    "rebuttal": None,
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
                written_feedback=feedback_txt,
                session_id=session_id,
            )
            st.session_state.run = False
            st.rerun()
        rebuttal = generate_rebuttal(client, msg, comment)

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
                "rebuttal": rebuttal,
                "session_id": session_id,
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
            written_feedback=feedback_txt,
            session_id=session_id,
            rebuttal=rebuttal,
        )

        st.session_state.run = False
        st.session_state.rating = None
        st.session_state.feedback = None

if st.session_state.history:
    if len(st.session_state.history) == 1:
        # Only one reply exists yet, so just show it - no need for the
        # "previous versions" browser below.
        #
        # The reply/explanation/rebuttal text below comes from GPT, and
        # GPT's output is itself shaped by whatever the visitor typed in as
        # the comment/draft - so it isn't fully trusted. html.escape(...)
        # converts characters like < and > into their safe HTML entities
        # (&lt;, &gt;) so that text can never be interpreted as actual HTML
        # tags/scripts when it's inserted into the page below.
        latest = st.session_state.history[-1]
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
        if latest.get("rebuttal"):
            st.markdown(
                f"<div class='reply-line'><span class='reply-label'>Possible rebuttal:</span>"
                f"{html.escape(latest['rebuttal'])}</div>",
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
            if latest.get("rebuttal"):
                st.markdown(
                    f"<div class='reply-line'>"
                    f"<span class='reply-label'>Possible rebuttal:</span>"
                    f"{html.escape(latest['rebuttal'])}</div>",
                    unsafe_allow_html=True,
                )

        with col2:
            total_versions = len(st.session_state.history) - 1  # Exclude latest

            if total_versions > 0:
                if "history_index" not in st.session_state:
                    st.session_state.history_index = 0

                col_l, col_m, col_r = st.columns([1, 3.5, 1])
                with col_l:
                    # on_click takes a function to run when the button is
                    # pressed. Here that function is a "lambda" - a small,
                    # unnamed function written inline - which moves the
                    # history browser one step back, but never below 0.
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
                        "<div style='text-align:center; font-weight:bold;'>Previous Versions</div>",
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
                if selected.get("rebuttal"):
                    st.markdown(
                        f"<div class='reply-line'>"
                        f"<span class='reply-label'>Possible rebuttal:</span>"
                        f"{html.escape(selected['rebuttal'])}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No previous versions yet.")

    st.markdown("---")
    st.markdown("### Feedback")
    rate = st.slider("How do you like the most recent response?", 1, 5, 3, key="rating_input")
    fb = st.text_area("Optional feedback (used only if you regenerate):", key="fb_input")
    st.session_state.rating = rate
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
