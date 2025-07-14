import streamlit as st
import openai
from dotenv import load_dotenv
import os
import json
import sqlite3
import csv
import uuid
import datetime
import firebase_admin
from firebase_admin import credentials, firestore




# Load environment variables from .env (only works locally)
# Load environment variables from .env (only works locally)
load_dotenv()

# ------------------- OPENAI API KEY -------------------

openai_api_key = os.getenv("api_key")  # Default from .env

try:
    # Check if Streamlit secrets is available and includes OpenAI key
    openai_api_key = st.secrets["openai"]["api_key"]
    print("🔐 Loaded OpenAI key from Streamlit secrets")
except Exception:
    print("🔐 Loaded OpenAI key from .env")

# ------------------- OPENAI CLIENT -------------------

client = openai.OpenAI(api_key=openai_api_key)

# ------------------- FIREBASE INITIALIZATION -------------------

db = None

try:
    firebase_config = None
    try:
        firebase_config = dict(st.secrets["firebase"])
        # Fix the private_key field by replacing \\n with \n
        firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
        print("📦 Firebase config loaded from Streamlit secrets")
    except Exception:
        if os.path.exists("firebase_key.json"):
            with open("firebase_key.json", "r") as f:
                firebase_config = json.load(f)
            print("📦 Firebase config loaded from firebase_key.json")

    if firebase_config:
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        st.session_state.firebase_app = True
except Exception as e:
    st.warning(f"⚠️ Firebase initialization failed.")



def log_to_firestore(user_input, input_type, message, explanation):
    if not db:
        st.warning("❌ Firestore is not initialized.")
        return

    doc_id = str(uuid.uuid4())
    timestamp = datetime.datetime.utcnow().isoformat()

    data = {
        "timestamp": timestamp,
        "user_input": user_input,
        "input_type": input_type,
        "llm_message": message,
        "llm_explanation": explanation,
    }



    try:
        db.collection("session_logs").document(doc_id).set(data)
       
    except Exception as e:
        st.warning(f"❌ Firestore logging failed.")


# Set up local SQLite database
conn = sqlite3.connect('session_logs.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        timestamp TEXT,
        user_input TEXT,
        input_type TEXT,
        llm_message TEXT,
        llm_explanation TEXT
    )
''')
conn.commit()

def log_session(user_input, input_type, message, explanation):
    entry_id = str(uuid.uuid4())
    timestamp = str(datetime.datetime.utcnow())

    # Log to SQLite
    c.execute('INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?)', 
              (entry_id, timestamp, user_input, input_type, message, explanation))
    conn.commit()

    # Also log to CSV
    with open('session_logs.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, entry_id, user_input, input_type, message, explanation])

st.title("Behavioral Science Based Advocate Assistant")
st.write("""This tool helps improve social media comments for better persuasiveness using behavioral science.""")

with st.expander("Optional: Include the comment you are replying to or context"):
    comment_input = st.text_area(
        "What did the other person say? Who are they? Any additional context?",
        placeholder="Paste the comment here...",
        key="comment_input"
    )

draft_input = st.text_area(
    "What do you want to say in reply?",
    placeholder="Write your reply draft here, or leave blank for GPT to generate it...",
    key="draft_input"
)

if st.button("Generate"):
    if not comment_input.strip() and not draft_input.strip():
        st.warning("Please enter a comment, a draft reply, or both.")
    else:
        with st.spinner("Thinking..."):
            try:
                # Send to GPT
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "system",
                            "content": """
You are a strategic animal rights advocate specializing in rewriting and crafting persuasive online replies, posts, and comments. Your goal is to maximize behavioral impact using research from behavioral science, Faunalytics, and the Vegan Advocacy Communication Hacks.

Your focus is on improving:
- Tone
- Structure and clarity
- Framing
- Emotional appeal
- Strength of call-to-action

Speak in a warm, relatable, and confident tone—like a thoughtful friend who went vegan for animals and wants to help others understand why it matters. Avoid sounding robotic, generic, overly academic, or confrontational.

Language rules:
- Avoid em dashes entirely; prefer commas or hyphens when needed.
- Use simple, conversational English that’s still intelligent and persuasive.
- Keep responses short: 2–4 sentences to ensure clarity and emotional impact in fast-paced online discussions.

Persuasion strategies:
- Adjust arguments based on the audience. Use emotional appeals for empathetic users, health/environmental framing for skeptics, and inclusive language to reduce resistance.
- Avoid moral absolutes or information overload. Encourage “as vegan as possible” thinking and low-pressure asks like “try one plant-based meal.”
- Avoid sarcasm, confrontation, or anything that provokes defensiveness.
- Promote sustainable advocacy and help users avoid burnout.
- Stick to the facts. Clarify misinformation or health trends that are unhealthy.
- Never endorse or normalize animal use.
- Never validate meat-eating, even with ex-vegans. 
- When talking about ex-vegans, remind about animal suffering, values, and the role of getting adequate support and nutrition information when going vegan.

When correcting misinformation (e.g. “vegan = unhealthy” or “high-carb = bad”), be respectful and clear. Use facts confidently, not aggressively. Refer to reputable sources (like major health organizations) when needed. Always prioritize clarity and empathy.

Effective techniques to use:
1. Acknowledge the other person’s perspective: “I used to love cheese too…”
2. Briefly share your personal story: “I became vegan after a lifetime of eating meat…”
3. With sceptics, invite allyship, not conversion: praise small steps like Meatless Mondays or signing petitions.
4. Encourage identity alignment: help others see how their values already match vegan ethics.
5. Use emotionally resonant, hopeful, and inclusive framing.

---

You will receive two inputs as a JSON object:

- comment: what someone else said (may be empty)
- draft_reply: a draft message or reply from the user (may be empty)
-If both are empty, return:
```json
{ "follow_up_question": "Please provide either a comment or a draft reply.", "needs_clarification": true }
- If both are provided, improve the draft in the context of the comment to make it more persuasive using behavioral science.
- If draft_reply is provided. It is not a comment to respond to. Improve it using behavioral science. If it is vague, ask for clarification.
- If only comment is provided, generate a persuasive reply from scratch.



If clarification is needed:

```json
{
  "follow_up_question": "string",  // ask a helpful clarifying question
  "needs_clarification": true
}
Always provide final output in this format:

```json
{
  "message": "...",
  "explanation": "...",
  "input_type": "draft_reply" or "comment" or "both",
  "needs_clarification": false
}
```
⚠️ Output only valid JSON. Do not include any extra explanation or formatting outside the JSON.
                       """
                        },
                        {
                            "role": "user",
                            "content": json.dumps({
                                "comment": comment_input.strip(),
                                "draft_reply": draft_input.strip()
                            })
                        }
                    ],
                    temperature=0.7,
                    max_tokens=400
                )

                # Raw response
                content = response.choices[0].message.content.strip()
                

                # Try parsing JSON safely
                try:
                    # Remove ```json if it exists
                    if content.startswith("```json"):
                        content = content.replace("```json", "").replace("```", "").strip()

                    # Regex fallback
                    import re
                    match = re.search(r"\{.*\}", content, re.DOTALL)
                    if match:
                        json_str = match.group(0)
                    else:
                        raise json.JSONDecodeError("No JSON object found", content, 0)

                    parsed = json.loads(json_str)
  

                    user_input = {
                        "comment": comment_input.strip(),
                        "draft_reply": draft_input.strip()
                    }

                    input_type = parsed.get("input_type", "unknown")
                    message = parsed.get("message") or parsed.get("follow_up_question", "⚠️ No message or question received.")
                    explanation = parsed.get("explanation") or ("Needs clarification" if parsed.get("needs_clarification") else "⚠️ No explanation provided.")

                    # UI display
                    if parsed.get("needs_clarification"):
                        st.info("The assistant needs clarification:")
                        st.markdown(f"**Question:** {message}")
                    else:
                        if input_type == "draft_reply":
                            st.success("Here’s your improved reply:")
                        elif input_type == "comment":
                            st.success("Here’s a suggested response to the comment:")
                        else:
                            st.success("Here’s the generated output:")

                        st.markdown(f"**Reply:** {message}")
                        st.markdown(f"**Explanation:** {explanation}")

                    # Save all sessions, including clarification cases
                    log_session(
                        user_input=json.dumps(user_input),
                        input_type=input_type + ("_clarification" if parsed.get("needs_clarification") else ""),
                        message=message,
                        explanation=explanation
                    )
                    if db:
                        try:
                            log_to_firestore(
                                user_input=json.dumps(user_input),
                                input_type=input_type + ("_clarification" if parsed.get("needs_clarification") else ""),
                                message=message,
                                explanation=explanation
                            )
                        except Exception:
                            st.warning("⚠️ Could not log to Firebase.")

                    st.caption(f"🔍 Detected input type: {input_type}")

                except json.JSONDecodeError:
                    st.error("❌ The AI response was not valid JSON.")
                    st.text_area("🔍 Full response from GPT:", value=content, height=150)

            except Exception as e:
                st.error("🚨 An unexpected error occurred.")
                st.exception(e)
