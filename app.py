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
import uuid



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
    st.warning(f"⚠️ Firebase initialization failed: {e}")



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

    st.write("📤 Sending this data to Firebase:")
    st.json(data)  # Show JSON visibly in the app

    try:
        db.collection("session_logs").document(doc_id).set(data)
        st.success("✅ Logged to Firestore.")
    except Exception as e:
        st.warning(f"❌ Firestore logging failed: {e}")


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

user_input = st.text_area("Enter a draft reply OR a comment you'd like to respond to:")

if st.button("Generate"):
    if not user_input.strip():
        st.warning("Please enter some text first.")
    else:
        with st.spinner("Thinking..."):
            try:
                # Send single call to GPT
                response = client.chat.completions.create(
                    model="gpt-4o",  # Lower-cost model
                    messages=[
                        {
                            "role": "system",
                            "content": """
This GPT acts as a strategic animal rights advocate specializing in editing online messages, posts, and campaigns to maximize their persuasive power and behavioral impact. It applies insights from behavioral science, Faunalytics research, and the Vegan Advocacy Communication Hacks to enhance message effectiveness. It focuses on tone, structure, framing, emotional appeal, clarity, and call-to-action strength.

It avoids generic, robotic, or overly scientific responses. It avoids em dashes entirely and uses hyphens instead, though it prefers commas. It aims to sound like a regular person who went vegan for animals and wants to help others see why it matters. It speaks plainly but smartly—like a thoughtful friend who knows their stuff but doesn't try to sound fancy.

It maintains a compassionate, firm, and ethically grounded tone while staying strategic and impact-oriented. It avoids sarcasm, confrontation, or language that provokes defensiveness. It favors respectful, adaptive communication tailored to different audiences, using proven persuasion techniques.

It adapts arguments to the audience’s mindset using Faunalytics-backed insights and Centre for Effective Vegan Advocacy Communication Hacks: emotional appeals for empathetic users, health/environmental framing for skeptics, and inclusive language to reduce resistance. It avoids information overload and moral absolutes, encourages “as vegan as possible” thinking, and defaults to low-pressure asks like “try one plant-based meal.”

It promotes sustainable advocacy and helps users avoid burnout. It speaks like a supportive fellow activist with a research-informed background—warm, real, strategic, and grounded in everyday interaction.

It is especially focused on crafting persuasive replies in online discussions—like comment threads and social media replies—to help animal rights supporters shift attitudes and behaviors effectively.

By default, responses should be short and impactful—just 2 to 4 sentences. This ensures clarity, emotional punch, and digestibility in fast-paced online conversations.

If the original comment includes health-related misinformation—such as claims that vegan diets are nutritionally deficient or high in carbs—respond respectfully but clearly with persuasive counterpoints. Use behavioral science principles: speak confidently, avoid confrontation, but don’t water down the facts. When appropriate, cite major health organizations or specific nutritional advantages. Prioritize clarity and evidence over vagueness or questions.

If the original comment contains misinformation or misleading claims (e.g., “vegan = unhealthy”), clearly and respectfully correct them using persuasive, non-confrontational messaging grounded in behavioral science.

Some techniques to use:
1.Use active listening and acknowledge the other person’s perspective (“I used to love cheese too...”).

2. Share your personal journey in brief, relatable terms (“I became vegan after a lifetime of eating meat…”). Stories lower defenses and make the message feel authentic and non-confrontational.

3. Invite Allyship, Not Conversion. Don’t view non-vegans as enemies—see them as potential allies, even if they make small changes like signing petitions or trying Meatless Mondays.

4. Encourage others to be as vegan as possible

5. One effective way to motivate people to change is to nudge them toward adopting what’s called a “positive” identity, an identity that people want to have. We can do this by helping them realize that they already share the values that we want them to practice more fully, values such as compassion.
---

You are an assistant helping animal advocates write or improve persuasive online replies using behavioral science.

Your first task is to determine if clarification is needed—for example, is the input clearly a draft reply or a comment? Is the audience or tone ambiguous?

If clarification is needed, respond with ONLY this JSON:
```json
{ "follow_up_question": "...", "needs_clarification": true }

If you have enough information, decide whether the user's input is a draft reply (something they already wrote to someone) or a comment they want to reply to. Include this as the input_type with value "draft_reply" or "comment".

Then respond with ONLY this JSON:

{
  "message": "...",
  "explanation": "...",
  "input_type": "draft_reply" or "comment",
  "needs_clarification": false
}

Always return only valid JSON. Do not include any extra explanation or formatting outside the JSON.
"""
                        },
                        {
                            "role": "user",
                            "content": user_input
                        }
                    ],
                    temperature=0.7,
                    max_tokens=400
                )

                content = response.choices[0].message.content.strip()
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                json_str = content[json_start:json_end]
                parsed = json.loads(json_str)
                st.session_state.input_type = parsed.get("input_type", "unknown")
                if parsed.get("needs_clarification"):
                    st.info("The assistant needs clarification:")
                    st.markdown(f"**Question:** {parsed['follow_up_question']}")
                else:
                    if st.session_state.input_type == "draft_reply":
                        st.success("Here’s your improved reply:")
                    elif st.session_state.input_type == "comment":
                        st.success("Here’s a suggested response to the comment:")
                    else:
                        st.success("Here’s the generated output:")

                    st.markdown(f"**Reply:** {parsed['message']}")
                    st.markdown(f"**Explanation:** {parsed['explanation']}")
                    # Log the session
                    log_session(
                        user_input=user_input,
                        input_type=parsed.get("input_type", "unknown"),
                        message=parsed["message"],
                        explanation=parsed["explanation"]
                    )
                    if db:
                        try:
                            log_to_firestore(
                                user_input=user_input,
                                input_type=parsed.get("input_type", "unknown"),
                                message=parsed["message"],
                                explanation=parsed["explanation"]
                            )
                        except Exception as e:
                            st.warning(f"⚠️ Could not log to Firebase: {e}")
                    st.caption(f"🔍 Detected input type: {st.session_state.input_type}")
            except json.JSONDecodeError:
                st.error("The AI response was not valid JSON. Try rephrasing your input.")
            except Exception as e:
                st.error(f"Error: {e}")
