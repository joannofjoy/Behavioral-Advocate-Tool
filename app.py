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
import pandas as pd
import re

# Load environment variables from .env (only works locally)
load_dotenv()

# ------------------- OPENAI API KEY -------------------
openai_api_key = os.getenv("api_key")  # Default from .env

try:
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

# ------------------- STRATEGY JSON LOADING -------------------
def load_strategies(path="strategies.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            strategies = json.load(f)
        return strategies
    except Exception as e:
        st.warning("⚠️ Could not load strategies.json")
        return []

strategies = load_strategies()

def filter_strategies_by_tags(all_strategies, detected_tags):
    matched_strategies = [s for s in all_strategies if any(tag in s["tags"] for tag in detected_tags)]
    matched_tags = sorted(set(tag for s in matched_strategies for tag in s["tags"] if tag in detected_tags))
    return matched_strategies, matched_tags

def extract_tags_from_input(comment, draft, client):
    prompt = f"""
You are a tag classifier for an AI assistant. Given this input:

Comment: {comment or 'N/A'}
Draft: {draft or 'N/A'}

Return a JSON list of 1–5 relevant tags that describe the emotional or messaging context. Use simple words like: angry, skeptical, defensive, curious, moral outrage, vegetarian, identity, confused, etc.

Example:
["skeptical", "identity", "open"]

Only return the JSON list. No explanation.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        raw = response.choices[0].message.content.strip()
        tags = json.loads(raw)
        return tags
    except Exception as e:
        st.warning("⚠️ Tag extraction failed. Proceeding without matching strategies.")
        return []

# ------------------- LOGGING -------------------
def log_to_firestore(user_input, input_type, message, explanation, tags_input, tags_justification, matched_tags_in_strategies, strategies):
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
        "tags_input": tags_input,
        "tags_justification": tags_justification,
        "matched_tags_in_strategies": matched_tags_in_strategies,
        "strategies": [s["title"] for s in strategies]
    }

    try:
        db.collection("session_logs").document(doc_id).set(data)
    except Exception as e:
        st.warning(f"❌ Firestore logging failed.")

conn = sqlite3.connect('session_logs.db', check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        timestamp TEXT,
        user_input TEXT,
        input_type TEXT,
        llm_message TEXT,
        llm_explanation TEXT,
        tags TEXT,
        strategies TEXT,
        tags_input TEXT,
        tags_justification TEXT,
        matched_tags_in_strategies TEXT
    )
''')
conn.commit()

def log_session(user_input, input_type, message, explanation, tags_input, tags_justification, matched_tags_in_strategies, strategies):
    entry_id = str(uuid.uuid4())
    timestamp = str(datetime.datetime.utcnow())

    c.execute('INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', 
              (
                  entry_id, timestamp, user_input, input_type, message, explanation,
                  json.dumps(tags_justification),
                  json.dumps([s["title"] for s in strategies]),
                  json.dumps(tags_input),
                  json.dumps(tags_justification),
                  json.dumps(matched_tags_in_strategies)
              ))
    conn.commit()

    with open('session_logs.csv', 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp, entry_id, user_input, input_type, message, explanation,
            ", ".join(tags_justification), ", ".join([s["title"] for s in strategies])
        ])

# ------------------- UI -------------------
st.markdown("## Behavioral Science Based Advocate Assistant")
st.write("""This tool helps improve social media comments for better persuasiveness using behavioral science.""")

with st.expander("Optional: Include the comment you are replying to or context"):
    comment_input = st.text_area("What did the other person say? Who are they? Any additional context?", placeholder="Paste the comment here...", key="comment_input")

draft_input = st.text_area("What do you want to say in reply?", placeholder="Write your reply draft here, or leave blank for GPT to generate it...", key="draft_input")

if st.button("Generate"):
    if not comment_input.strip() and not draft_input.strip():
        st.warning("Please enter a comment, a draft reply, or both.")
    else:
        with st.spinner("Thinking..."):
            try:
                detected_tags = extract_tags_from_input(comment_input.strip(), draft_input.strip(), client)
                matched_strategies, matched_tags_in_strategies = filter_strategies_by_tags(strategies, detected_tags)
                formatted_strategies = "\n".join([f"- {s['title']}: {s['description']}" for s in matched_strategies]) or "No specific strategies matched."

                system_prompt = f"""
You are a strategic animal rights advocate specializing in rewriting and crafting persuasive online replies, posts, and comments. Your goal is to maximize behavioral impact using research from behavioral science, Faunalytics, and the Vegan Advocacy Communication Hacks.

Use the following behavioral strategies when applicable:
{formatted_strategies}

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
{{ "follow_up_question": "Please provide either a comment or a draft reply.", "needs_clarification": true }}
- If both are provided, improve the draft in the context of the comment to make it more persuasive using behavioral science.
- If draft_reply is provided. It is not a comment to respond to. Improve it using behavioral science. If it is vague, ask for clarification.
- If only comment is provided, generate a persuasive reply from scratch.



If clarification is needed:

```json
{{
  "follow_up_question": "string",  // ask a helpful clarifying question
  "needs_clarification": true
}}
Always provide final output in this format:

```json
{{
  "message": "...",
  "explanation": "...",
  "input_type": "draft_reply" or "comment" or "both",
  "needs_clarification": false
}}
```
⚠️ Output only valid JSON. Do not include any extra explanation or formatting outside the JSON.
                       
"""

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps({"comment": comment_input.strip(), "draft_reply": draft_input.strip()})}
                    ],
                    temperature=0.7,
                    max_tokens=400
                )

                content = response.choices[0].message.content.strip()

                if content.startswith("```json"):
                    content = content.replace("```json", "").replace("```", "").strip()
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    json_str = match.group(0)
                    parsed = json.loads(json_str)
                else:
                    raise json.JSONDecodeError("No JSON object found", content, 0)

                user_input = {
                    "comment": comment_input.strip(),
                    "draft_reply": draft_input.strip()
                }

                input_type = parsed.get("input_type", "unknown")
                message = parsed.get("message") or parsed.get("follow_up_question", "⚠️ No message or question received.")
                explanation = parsed.get("explanation") or ("Needs clarification" if parsed.get("needs_clarification") else "⚠️ No explanation provided.")

                if parsed.get("needs_clarification"):
                    st.info("The assistant needs clarification:")
                    st.markdown(f"**Question:** {message}")
                else:
                    st.success("Here’s your result:")
                    st.markdown(f"**Reply:** {message}")
                    st.markdown(f"**Explanation:** {explanation}")
                with st.expander("🧠 Debug: Detected Tags and Strategies"):
                    st.write("Tags:", detected_tags)
                    st.write("Strategies:", [s["title"] for s in matched_strategies])

                tags_justification = parsed.get("tags", [])

                log_session(
                    user_input=json.dumps(user_input),
                    input_type=input_type + ("_clarification" if parsed.get("needs_clarification") else ""),
                    tags_input=detected_tags,
                    tags_justification=tags_justification,
                    matched_tags_in_strategies=matched_tags_in_strategies,
                    strategies=matched_strategies,
                    message=message,
                    explanation=explanation
                )
                if db:
                    try:
                        log_to_firestore(
                            user_input=json.dumps(user_input),
                            input_type=input_type + ("_clarification" if parsed.get("needs_clarification") else ""),
                            tags_input=detected_tags,
                            tags_justification=parsed.get("tags", []), 
                            matched_tags_in_strategies = matched_tags_in_strategies,
                            strategies=matched_strategies,
                            message=message,
                            explanation=explanation
                        )
                    except Exception:
                        st.warning("⚠️ Could not log to Firebase.")

                st.caption(f"🔍 Detected input type: {input_type}")

            except Exception as e:
                st.error("🚨 An unexpected error occurred.")
                st.exception(e)
