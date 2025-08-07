import streamlit as st  # Streamlit for UI
import openai            # OpenAI client library
from dotenv import load_dotenv  # Load .env files
import os                # OS utilities (env vars, file paths)
import json              # JSON encoding/decoding
import sqlite3           # SQLite for local logging
import csv               # CSV writing for backup logs
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

def evaluate_reply(reply: str, rebuttal: str, model="gpt-4o", temperature=0.3) -> dict:
    txt = ""
    try:
        eval_prompt = load_prompt("prompt4.txt").format(
        comment=comment,
        reply=reply,
        rebuttal=rebuttal,
        strategies_used=strat_block  # ✅ Injects the strategies from prompt2
        )
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an expert in persuasive communication and behavioral science. Respond only with raw JSON. Do not use markdown."},
                {"role": "user", "content": eval_prompt}
            ],
            temperature=temperature,
            max_tokens=500
        )

        txt = r.choices[0].message.content.strip()

        # Remove code fences just in case
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)

        match = re.search(r"\{[\s\S]*\}", txt)
        if not match:
            raise ValueError("No JSON object found in GPT output.")

        json_block = match.group(0)
        parsed = json.loads(json_block)

        return {
            "confidence_score": parsed.get("confidence_score"),
            "justification": parsed.get("justification", "").strip(),
            "suggested_improvements": parsed.get("suggested_improvements", "").strip(),
            "ultimate_reply": parsed.get("ultimate_reply", "").strip()
        }

    except Exception as e:
        st.warning(f"⚠️ Evaluation failed: {e}")
        st.markdown("### 🐞 Debug: Raw GPT output")
        st.code(txt or "[No GPT output]", language="json")
        return {
            "confidence_score": None,
            "justification": "Evaluation failed.",
            "suggested_improvements": "",
            "ultimate_reply": ""
        }

# Logging setup
conn = sqlite3.connect('session_logs.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
CREATE TABLE IF NOT EXISTS logs (
  id TEXT PRIMARY KEY,
  version INTEGER,
  timestamp TEXT,
  user_input TEXT,
  input_type TEXT,
  llm_message TEXT,
  llm_explanation TEXT,
  tags_input TEXT,
  tags_justification TEXT,
  matched_tags TEXT,
  matched_tags_in_strategies TEXT,
  strategies TEXT,
  rating TEXT,
  written_feedback TEXT,
  session_id TEXT
)''')
conn.commit()

def log_session(user_input, input_type, message, explanation,
                tags_input, tags_justification,
                matched_tags, matched_tags_in_strategies,
                strategies, rating=None, feedback=None, session_id=None):
    entry_id = str(uuid.uuid4())
    ts = datetime.datetime.utcnow().isoformat()
    c.execute(
        'INSERT INTO logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (entry_id, len(st.session_state.history), ts, user_input, input_type, message, explanation,
         json.dumps(tags_input), json.dumps(tags_justification),
         json.dumps(matched_tags), json.dumps(matched_tags_in_strategies),
         json.dumps([s['title'] for s in strategies]),
         str(rating) if rating is not None else None,
         feedback, session_id)
    )
    conn.commit()
    try:
        with open('session_logs.csv', 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([
                ts, entry_id, len(st.session_state.history), user_input, input_type, message, explanation,
                json.dumps(tags_input), json.dumps(tags_justification),
                json.dumps(matched_tags), json.dumps(matched_tags_in_strategies),
                json.dumps([s['title'] for s in strategies]), rating, feedback, session_id
            ])
    except PermissionError:
        st.warning("⚠️ Could not write to CSV. File may be open or locked.")

def log_to_firestore(user_input, input_type, message, explanation,
                     tags_input, tags_justification,
                     matched_tags, matched_tags_in_strategies,
                     strategies, rating=None, written_feedback=None, session_id=None):
    if not db:
        return
    doc = {
        'version': len(st.session_state.history),
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'user_input': user_input,
        'input_type': input_type,
        'llm_message': message,
        'llm_explanation': explanation,
        'tags_input': tags_input,
        'tags_justification': tags_justification,
        'matched_tags': matched_tags,
        'matched_tags_in_strategies': matched_tags_in_strategies,
        'strategies': [s['title'] for s in strategies],
        'rating': rating,
        'written_feedback': written_feedback,
        'session_id': session_id
    }
    try:
        db.collection('session_logs').document(str(uuid.uuid4())).set(doc)
    except Exception:
        st.warning("❌ Firestore log failed.")

# ------------------- UI -------------------
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    .reply-line { font-size: 0.9rem; margin-bottom: 0.5rem; }
    .reply-label { font-weight: bold; margin-right: 0.25rem; }
    </style>
""", unsafe_allow_html=True)

st.markdown("## Behavioral Science Based Advocate Assistant")
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
            log_session(user_in, itype, msg, expl, tags, just, matched_tags, matched_tags, strats,
                        rating=rating_val, feedback=feedback_txt, session_id=session_id)
            log_to_firestore(user_input=user_in, input_type=itype, message=msg, explanation=expl,
                            tags_input=tags, tags_justification=just,
                            matched_tags=matched_tags, matched_tags_in_strategies=matched_tags,
                            strategies=strats, rating=rating_val, written_feedback=feedback_txt,
                            session_id=session_id)
            st.session_state.run = False
            st.rerun()
        rebuttal = generate_rebuttal(msg, comment)
        evaluation = evaluate_reply(msg, rebuttal)


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
            "confidence_score": evaluation["confidence_score"],
            "evaluation_justification": evaluation["justification"],
            "suggested_improvements": evaluation["suggested_improvements"],
            "ultimate_reply": evaluation["ultimate_reply"],
            "session_id": session_id
        })
        if len(st.session_state.history) > 1:
            st.session_state.history_index = len(st.session_state.history) - 2

        log_session(user_in, itype, msg, expl, tags, just, matched_tags, matched_tags, strats,
                    rating=rating_val, feedback=feedback_txt, session_id=session_id)
        log_to_firestore(user_input=user_in, input_type=itype, message=msg, explanation=expl,
                         tags_input=tags, tags_justification=just,
                         matched_tags=matched_tags, matched_tags_in_strategies=matched_tags,
                         strategies=strats, rating=rating_val, written_feedback=feedback_txt,
                         session_id=session_id)

        st.session_state.run = False
        st.session_state.rating = None
        st.session_state.feedback = None

if st.session_state.history:

    if len(st.session_state.history) == 1:
        latest = st.session_state.history[-1]
        st.markdown(f"<div class='reply-line'><span class='reply-label'>Reply:</span>{latest['reply']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='reply-line'><span class='reply-label'>Explanation:</span>{latest['explanation']}</div>", unsafe_allow_html=True)
        if latest.get("rebuttal"):
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Rebuttal:</span>{latest['rebuttal']}</div>", unsafe_allow_html=True)
        if latest.get("confidence_score") is not None:
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Confidence Score:</span>{latest['confidence_score']}/10</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Why this score?</span>{latest['evaluation_justification']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Suggested Improvements:</span>{latest['suggested_improvements']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Ultimate Reply:</span>{latest['ultimate_reply']}</div>", unsafe_allow_html=True)


    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            latest = st.session_state.history[-1]
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Latest Reply:</span>{latest['reply']}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='reply-line'><span class='reply-label'>Explanation:</span>{latest['explanation']}</div>", unsafe_allow_html=True)
        with col2:
            total_versions = len(st.session_state.history) - 1  # Exclude latest

            if total_versions > 0:
                if "history_index" not in st.session_state:
                    st.session_state.history_index = 0

                col_l, col_m, col_r = st.columns([1, 3.5, 1])
                with col_l:
                    st.button(" < ", key="prev_btn", on_click=lambda: st.session_state.update({"history_index": max(0, st.session_state.history_index - 1)}),  use_container_width=True)
                with col_m:
                    st.markdown("<div style='text-align:center; font-weight:bold;'>Previous Versions</div>", unsafe_allow_html=True)
                with col_r:
                    st.button(" > ", key="next_btn", on_click=lambda: st.session_state.update({"history_index": min(total_versions - 1, st.session_state.history_index + 1)}),  use_container_width=True)

                selected = st.session_state.history[st.session_state.history_index]
                st.markdown(f"<div class='reply-line'><span class='reply-label'>v{st.session_state.history_index+1}:</span>{selected['reply']}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='reply-line'><span class='reply-label'>Explanation:</span>{selected['explanation']}</div>", unsafe_allow_html=True)
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
