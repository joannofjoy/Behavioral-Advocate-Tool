import streamlit as st  # Streamlit for UI
import openai            # OpenAI client library
from dotenv import load_dotenv  # Load .env files
import os                # OS utilities (env vars, file paths)
import json              # JSON encoding/decoding
import uuid              # Generate unique IDs
import datetime          # Timestamps
import firebase_admin    # Firebase Admin SDK
from firebase_admin import credentials, firestore  # Firestore client
import re                # Regular expressions for parsing

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "history" not in st.session_state:
    st.session_state.history = []  # list of reply blocks

# Load environment variables
load_dotenv()

# OpenAI API Key setup
openai_api_key = os.getenv("api_key")
try:
    openai_api_key = st.secrets["openai"]["api_key"]
except Exception:
    pass
client = openai.OpenAI(api_key=openai_api_key)

# Firebase initialization
db = None
try:
    firebase_config = None
    try:
        firebase_config = dict(st.secrets["firebase"])
        firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
    except Exception:
        if os.path.exists("firebase_key.json"):
            with open("firebase_key.json") as f:
                firebase_config = json.load(f)
    if firebase_config:
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        st.session_state.firebase_app = True
except Exception as e:
    st.warning(f"⚠️ Firebase init failed: {e}")

# Load prompt
def load_prompt(fn):
    with open(fn, encoding="utf-8") as f:
        return f.read()

def load_strategies(path="strategies.json"):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        st.warning("⚠️ Could not load strategies.json")
        return []

strategies = load_strategies()

def filter_strategies_by_tags(all_strats, tags):
    matched = [s for s in all_strats if any(t in s.get("tags", []) for t in tags)]
    matched_tags = sorted({t for s in matched for t in s.get("tags", []) if t in tags})
    return matched, matched_tags

def extract_tags(comment, draft):
    prompt = load_prompt("prompt1.txt").format(comment=comment or "N/A", draft=draft or "N/A")
    try:
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        return json.loads(r.choices[0].message.content.strip())
    except Exception:
        st.warning("⚠️ Tag extraction failed.")
        return []

def generate_rebuttal(reply: str, comment: str, model="gpt-4o", temperature=0.7) -> str:
    try:
        rebuttal_prompt = load_prompt("prompt3.txt").format(reply=reply, comment=comment)
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a skeptical, articulate critic of vegan arguments, tasked with challenging the assistant’s message."},
                {"role": "user", "content": rebuttal_prompt}
            ],
            temperature=temperature,
            max_tokens=400
        )
        txt = r.choices[0].message.content.strip()

        # Clean up code block formatting if GPT adds it
        if txt.startswith("```json") or txt.startswith("```"):
            txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.MULTILINE).strip()

        parsed = json.loads(re.search(r"\{.*\}", txt, re.DOTALL).group(0))
        return parsed.get("rebuttal", "[Rebuttal missing]")
    except Exception as e:
        st.warning(f"⚠️ Rebuttal generation failed: {e}")
        return ""


# Logging setup

def log_to_firestore(
    user_input,
    input_type,
    message,
    explanation,
    tags_input,
    tags_justification,
    matched_tags,
    matched_tags_in_strategies,
    strategies,
    session_id=None,
    rating=None,
    written_feedback=None,
    rebuttal=None,
    confidence_score=None,
    evaluation_justification=None,
    suggested_improvements=None,
    ultimate_reply=None,
):
    if not db:
        return
    version = len(st.session_state.history)  # monotonic per session
    doc = {
        'version': version,
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'session_id': session_id,
        'user_input': user_input,                # JSON string you already pass
        'input_type': input_type,                # "comment" | "draft_reply" | "both" | "unknown"
        'llm_message': message,                  # final reply
        'llm_explanation': explanation,
        'tags_input': tags_input,                # raw extracted tags (normalized list)
        'tags_justification': tags_justification,# what model returned in "tags" field
        'matched_tags': matched_tags,            # intersection with strategies
        'matched_tags_in_strategies': matched_tags_in_strategies,
        'strategies': [s.get('title', '') for s in strategies],
        'rating': rating,
        'written_feedback': written_feedback,
        # NEW fields:
        'rebuttal': rebuttal,
        'confidence_score': confidence_score,
        'evaluation_justification': evaluation_justification,
        'suggested_improvements': suggested_improvements,
        'ultimate_reply': ultimate_reply,
    }
    try:
        # Prefer hierarchical path for easy querying:
        db.collection('sessions').document(str(session_id)) \
          .collection('versions').document(str(version)).set(doc)
    except Exception as e:
        st.warning(f"❌ Firestore log failed: {e}")

# ------------------- UI -------------------
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    .reply-line { font-size: 0.9rem; margin-bottom: 0.5rem; }
    .reply-label { font-weight: bold; margin-right: 0.25rem; }
    </style>
""", unsafe_allow_html=True)

st.markdown("## Animal Advocacy Messaging Assistant")
st.write("""This tool helps improve social media comments for better persuasiveness using behavioral science.""")

comment = st.text_area("What did the other person say? Who are they? Any additional context?",
    key='comment_input',
    placeholder="Paste the other person's comment and add any additional context here...")

with st.expander("Optional: Your draft reply"):
    draft = st.text_area("", key='draft_input', placeholder="Write your reply draft here, or leave blank for the assistant to generate it...", label_visibility="collapsed")

if st.button("Generate a reply"):
    if not comment.strip() and not draft.strip():
        st.warning("Enter context or draft.")
    else:
        st.session_state.run = True
        st.rerun()

if st.session_state.get('run'):
    with st.spinner("Thinking..."):
        session_id = st.session_state["session_id"]
        tags = extract_tags(comment.strip(), draft.strip())
        strats, matched_tags = filter_strategies_by_tags(strategies, tags)
        strat_block = "\n".join(f"- {s['title']}: {s['description']}" for s in strats) or "No strategies matched."

        base_prompt = load_prompt("prompt2.txt").format(formatted_strategies=strat_block)

        feedback_txt = st.session_state.get('feedback', '').strip()
        rating_val = st.session_state.get('rating')

        if feedback_txt or rating_val is not None:
            feedback_block = (
                f"You just received the following feedback on your previous reply:\n"
                f"- Written feedback: \"{feedback_txt}\"\n"
                f"- Rating: {rating_val}/5\n\n"
                f"Revise your reply accordingly before applying the rest of the instructions. You should still ask for clarifictaion if the input is not relate dto animal advocacy. \n"
                f"If the rating is under 4, that means the user wasn’t fully satisfied — make sure to address their concerns. The lower the rating, the more you should change the reply. \n"
                f"After applying the feedback, in <explanation> field include describing how you changed the reply in response to the feedback. If you did not include any part of the feedback, explain why. \n"
            )

            prompt = feedback_block + "\n" + base_prompt
        else:
            prompt = base_prompt

       # st.markdown("#### Prompt passed to GPT")
       # st.code(prompt)

        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({'comment': comment, 'draft_reply': draft})}
            ],
            temperature=0.7,
            max_tokens=400
        )
        txt = r.choices[0].message.content
        if txt.startswith("```json"):
            txt = txt.strip('```json').strip('```')
        parsed = json.loads(re.search(r"\{.*\}", txt, re.DOTALL).group(0))

        user_in = json.dumps({'comment': comment, 'draft_reply': draft})
        itype = parsed.get('input_type', 'unknown')
        msg = parsed.get('message', parsed.get('follow_up_question', ''))
        expl = parsed.get('explanation') or ('Needs clarification' if parsed.get('needs_clarification') else '')
        just = parsed.get('tags', [])
        if parsed.get("needs_clarification"):
            st.session_state.history.append({
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
                "session_id": session_id
            })
         
            log_to_firestore(user_input=user_in, input_type=itype, message=msg, explanation=expl,
                            tags_input=tags, tags_justification=just,
                            matched_tags=matched_tags, matched_tags_in_strategies=matched_tags,
                            strategies=strats, rating=rating_val, written_feedback=feedback_txt,
                            session_id=session_id)
            st.session_state.run = False
            st.rerun()
        rebuttal = generate_rebuttal(msg, comment)



        st.session_state.history.append({
            "reply": msg,
            "explanation": expl,
            "user_input": user_in,
            "input_type": itype,
            "tags": tags,
            "justification": just,
            "matched_tags": matched_tags,
            "strategies": strats,
            "rebuttal": rebuttal,
            "session_id": session_id
        })
        if len(st.session_state.history) > 1:
            st.session_state.history_index = len(st.session_state.history) - 2

      
        log_to_firestore(
            user_input=user_in, input_type=itype, message=msg, explanation=expl,
            tags_input=tags, tags_justification=just,
            matched_tags=matched_tags, matched_tags_in_strategies=matched_tags,
            strategies=strats, rating=rating_val, written_feedback=feedback_txt,
            session_id=session_id, rebuttal=rebuttal   
        )

        st.session_state.run = False
        st.session_state.rating = None
        st.session_state.feedback = None

if st.session_state.history:

    if len(st.session_state.history) == 1:
        latest = st.session_state.history[-1]
        st.markdown(f"<div class='reply-line'><span class='reply-label'>Reply:</span>{latest['reply']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='reply-line'><span class='reply-label'>Explanation:</span>{latest['explanation']}</div>", unsafe_allow_html=True)
        if latest.get("rebuttal"):
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Possible rebuttal:</span>{latest['rebuttal']}</div>", unsafe_allow_html=True)
 

    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("<div style='text-align:center; font-weight:bold;'>Latest Version</div><br>", unsafe_allow_html=True)
            latest = st.session_state.history[-1]
            latest = st.session_state.history[-1]
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Latest Reply:</span>{latest['reply']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Explanation:</span>{latest['explanation']}</div>", unsafe_allow_html=True)
            if latest.get("rebuttal"):
                st.markdown(f"<div class='reply-line'><span class='reply-label'>Possible rebuttal:</span>{latest['rebuttal']}</div>", unsafe_allow_html=True)
 
        with col2:
            total_versions = len(st.session_state.history) - 1  # Exclude latest

            if total_versions > 0:
                if "history_index" not in st.session_state:
                    st.session_state.history_index = 0

                col_l, col_m, col_r = st.columns([1, 3.5, 1])
                with col_l:
                    st.button(" ◀ ", key="prev_btn", on_click=lambda: st.session_state.update({"history_index": max(0, st.session_state.history_index - 1)}),  use_container_width=True)
                with col_m:
                    st.markdown("<div style='text-align:center; font-weight:bold;'>Previous Versions</div>", unsafe_allow_html=True)
                with col_r:
                    st.button(" ▶ ", key="next_btn", on_click=lambda: st.session_state.update({"history_index": min(total_versions - 1, st.session_state.history_index + 1)}),  use_container_width=True)

                selected = st.session_state.history[st.session_state.history_index]
                st.markdown(f"<div class='reply-line'><span class='reply-label'>Reply Version {st.session_state.history_index+1}:</span>{selected['reply']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='reply-line'><span class='reply-label'>Explanation:</span>{selected['explanation']}</div>", unsafe_allow_html=True)
                if selected.get("rebuttal"):
                    st.markdown(f"<div class='reply-line'><span class='reply-label'>Possible rebuttal:</span>{selected['rebuttal']}</div>", unsafe_allow_html=True)
            else:
                st.info("No previous versions yet.")


    st.markdown("---")
    st.markdown("### Feedback")
    rate = st.slider('How do you like the most recent response?', 1, 5, 3, key='rating_input')
    fb = st.text_area('Optional feedback (used only if you regenerate):', key='fb_input')
    st.session_state.rating = rate
    st.session_state.feedback = fb

    if st.button("🔁 Regenerate with feedback"):
        st.session_state.run = True
        st.rerun()

    if st.button("🆕 New session"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.experimental_rerun()
