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

# Load environment variables from .env
load_dotenv()

# ------------------- OPENAI API KEY -------------------
# Attempt to read API key from environment, then from Streamlit secrets
openai_api_key = os.getenv("api_key")
try:
    openai_api_key = st.secrets["openai"]["api_key"]
except Exception:
    pass
# Initialize OpenAI client with the loaded API key
client = openai.OpenAI(api_key=openai_api_key)

# ------------------- FIREBASE INITIALIZATION -------------------
db = None
try:
    firebase_config = None
    try:
        # Try loading Firebase config from Streamlit secrets
        firebase_config = dict(st.secrets["firebase"])
        # Fix newline escapes in the private key
        firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
    except Exception:
        # Fallback: load config from local JSON file if available
        if os.path.exists("firebase_key.json"):
            with open("firebase_key.json") as f:
                firebase_config = json.load(f)
    if firebase_config:
        # Initialize Firebase app only once
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
        # Get Firestore client
        db = firestore.client()
        st.session_state.firebase_app = True
except Exception as e:
    st.warning(f"⚠️ Firebase init failed: {e}")

# ------------------- HELPERS -------------------
def load_prompt(fn):
    """
    Read and return the content of a prompt file.
    """
    with open(fn, encoding="utf-8") as f:
        return f.read()

def load_strategies(path="strategies.json"):
    """
    Load the list of behavioral strategies from a JSON file.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        st.warning("⚠️ Could not load strategies.json")
        return []

# Load strategies into memory
strategies = load_strategies()

def filter_strategies_by_tags(all_strats, tags):
    """
    Given all strategies and a list of detected tags,
    return the subset of strategies whose tags match,
    and the list of matched tags.
    """
    matched = [s for s in all_strats if any(t in s.get("tags", []) for t in tags)]
    matched_tags = sorted({t for s in matched for t in s.get("tags", []) if t in tags})
    return matched, matched_tags

def extract_tags(comment, draft):
    """
    Call the tag-extraction prompt to classify the emotional/contextual tags
    for the provided comment and draft text.
    """
    prompt = load_prompt("prompt1.txt").format(comment=comment or "N/A", draft=draft or "N/A")
    try:
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"user","content":prompt}],
            temperature=0.3,
            max_tokens=100
        )
        return json.loads(r.choices[0].message.content.strip())
    except Exception:
        st.warning("⚠️ Tag extraction failed.")
        return []

# ------------------- LOGGING SETUP -------------------
# Initialize SQLite connection and cursor
conn = sqlite3.connect('session_logs.db', check_same_thread=False)
c = conn.cursor()
# Create logs table if it doesn't exist
c.execute('''
CREATE TABLE IF NOT EXISTS logs (
  id TEXT PRIMARY KEY,
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
  written_feedback TEXT
)''')
conn.commit()

def log_session(user_input, input_type, message, explanation,
                tags_input, tags_justification,
                matched_tags, matched_tags_in_strategies,
                strategies, rating=None, feedback=None):
    """
    Log a session entry to SQLite and append it to a CSV file.
    """
    entry_id = str(uuid.uuid4())  # Unique row ID
    ts = datetime.datetime.utcnow().isoformat()
    # Insert into SQLite
    c.execute(
        'INSERT INTO logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (entry_id, ts, user_input, input_type, message, explanation,
         json.dumps(tags_input), json.dumps(tags_justification),
         json.dumps(matched_tags), json.dumps(matched_tags_in_strategies),
         json.dumps([s['title'] for s in strategies]),
         str(rating) if rating is not None else None,
         feedback)
    )
    conn.commit()
    # Append to CSV as a backup
    with open('session_logs.csv','a',newline='',encoding='utf-8') as f:
        csv.writer(f).writerow([
            ts, entry_id, user_input, input_type, message, explanation,
            json.dumps(tags_input), json.dumps(tags_justification),
            json.dumps(matched_tags), json.dumps(matched_tags_in_strategies),
            json.dumps([s['title'] for s in strategies]), rating, feedback
        ])

def log_to_firestore(user_input, input_type, message, explanation,
                     tags_input, tags_justification,
                     matched_tags, matched_tags_in_strategies,
                     strategies, rating=None, written_feedback=None):
    """
    Log the session entry to Firestore (if initialized).
    """
    if not db:
        return
    doc = {
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
        'written_feedback': written_feedback
    }
    try:
        db.collection('session_logs').document(str(uuid.uuid4())).set(doc)
    except Exception:
        st.warning("❌ Firestore log failed.")

# ------------------- UI -------------------
# App title
st.markdown("""
    <style>
    /* Reduce top padding in main container */
    .block-container { padding-top: 1rem; }
    /* Make the title smaller */
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    </style>
""", unsafe_allow_html=True)

# Smaller title
st.markdown("## Behavioral Science Based Advocate Assistant")
st.write("""This tool helps improve social media comments for better persuasiveness using behavioral science.""")
# Input areas for context and draft reply

# Input for context/comment with placeholder instruction
comment = st.text_area(
    "What did the other person say? Who are they? Any additional context?",
    key='comment_input',
    placeholder="Paste the other person's comment and add any additional context here..."
)

# Draft reply as an optional collapsible section, with placeholder
with st.expander("Optional: Your draft reply"):
    draft = st.text_area(
        "",
        key='draft_input',
        placeholder="Write your reply draft here, or leave blank for the assistant to generate it...",
        label_visibility="collapsed"
    )

# Generate button: starts the LLM generation flow
if st.button("Generate a reply"):
    if not comment.strip() and not draft.strip():
        st.warning("Enter context or draft.")
    else:
        # Set flags and reset feedback state
        st.session_state.run = True
        st.session_state.initial_logged = False
        #st.session_state.feedback = ''         # initialize feedback storage
        st.session_state.rating = None
        st.rerun()



# Main generation & feedback flow
if st.session_state.get('run'):
    with st.spinner("Thinking..."):
        # Extract tags and match strategies
        tags = extract_tags(comment.strip(), draft.strip())
        strats, matched_tags = filter_strategies_by_tags(strategies, tags)

        # Build strat block
        strat_block = "\n".join(f"- {s['title']}: {s['description']}" for s in strats) or "No strategies matched."

        # ← Inject saved feedback into prompt2 when present
        base_prompt = load_prompt("prompt2.txt").format(formatted_strategies=strat_block)
        if st.session_state.get('feedback'):
            prompt = f"User feedback: \"{st.session_state['feedback']}\"\n\n" + base_prompt
        else:
            prompt = base_prompt

        # Call OpenAI to get the rewritten reply
        r = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role":"system","content":prompt},
                {"role":"user","content":json.dumps({'comment':comment,'draft_reply':draft})}
            ],
            temperature=0.7,
            max_tokens=400
        )
        # Clean up and parse the JSON response
        txt = r.choices[0].message.content
        if txt.startswith("```json"):
            txt = txt.strip('```json').strip('```')
        parsed = json.loads(re.search(r"\{.*\}", txt, re.DOTALL).group(0))

        # Prepare values for logging & display
        user_in = json.dumps({'comment':comment,'draft_reply':draft})
        itype = parsed.get('input_type','unknown')
        msg = parsed.get('message', parsed.get('follow_up_question',''))
        expl = parsed.get('explanation') or ('Needs clarification' if parsed.get('needs_clarification') else '')
        just = parsed.get('tags', [])

        # Initial log (only once per generation)
        if not st.session_state.initial_logged:
            log_session(user_in, itype, msg, expl, tags, just, matched_tags, matched_tags, strats)
            log_to_firestore(user_in, itype, msg, expl, tags, just, matched_tags, matched_tags, strats)
            st.session_state.initial_logged = True

        # Display the reply and explanation
        st.subheader('Reply')
        st.write(msg)
        st.subheader('Explanation')
        st.write(expl)

        # Feedback inputs (slider & text area)
        rate = st.slider('How helpful?', 1, 5, 3, key='rating_input')
        fb = st.text_area('Any feedback?', key='fb_input')
        st.session_state.feedback = fb         # ← store feedback for regeneration
        st.session_state.rating = rate

        # Save feedback on button click (logs but doesn't rerun)
        if st.button('Send Feedback'):
            log_session(user_in, itype, msg, expl, tags, just, matched_tags, matched_tags, strats, rate, fb)
            log_to_firestore(user_in, itype, msg, expl, tags, just, matched_tags, matched_tags, strats, rate, fb)
            st.success('Feedback saved!')
        if st.button("Regenerate with feedback"):
            st.session_state.run = True      # marks that we should re-call the LLM
            st.session_state.initial_logged = False
            # (don’t clear feedback here)
            st.rerun()
        # New conversation button clears all state
        if st.button('New session'):
            st.session_state.clear()
