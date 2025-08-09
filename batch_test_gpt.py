import pandas as pd
import random
import json
import re
import os
from datetime import datetime
from dotenv import load_dotenv
import openai

# Load environment variables and OpenAI client
load_dotenv()
openai_api_key = os.getenv("api_key")
client = openai.OpenAI(api_key=openai_api_key)

# CONFIGURATION
COMMENTS_FILE = "Sample_Social_Media_Comments.csv"
STRATEGY_FILE = "strategies.json"
SELECTED_CATEGORY_NUMBERS = [1, 6, 7]
NUM_PER_CATEGORY = 1
SHUFFLE = True

# Load strategy definitions (RAG source)
def load_strategies(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"\u26a0\ufe0f Failed to load strategies: {e}")
        return []

strategies = load_strategies(STRATEGY_FILE)

def filter_strategies_by_tags(all_strategies, detected_tags):
    matched_strategies = [s for s in all_strategies if any(tag in s["tags"] for tag in detected_tags)]
    matched_tags = sorted(set(tag for s in matched_strategies for tag in s["tags"] if tag in detected_tags))
    return matched_strategies, matched_tags

def extract_tags(comment, draft_reply):
    prompt = f"""
You are a tag classifier for an AI assistant. Given this input:

Comment: {comment or 'N/A'}
Draft: {draft_reply or 'N/A'}

Return a JSON list of 1–5 relevant tags that describe the emotional or messaging context. Use simple words like: angry, skeptical, defensive, curious, moral outrage, vegetarian, identity, confused, attack, ex-vegan etc.

Example:
["skeptical", "identity", "open"]

Only return the JSON list. No explanation.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt.strip()}],
            temperature=0.3,
            max_tokens=100
        )

        content = response.choices[0].message.content.strip()
        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            return json.loads(match.group(0)), content
        else:
            raise ValueError(f"No JSON list found in GPT output: {content}")

    except Exception as e:
        print(f"\u26a0\ufe0f Tag extraction failed: {e}")
        return [], ""

def process_comment(comment, draft_reply=""):
    detected_tags, raw_tags_output = extract_tags(comment, draft_reply)
    matched_strategies, matched_tags_in_strategies = filter_strategies_by_tags(strategies, detected_tags)
    strategy_text = "\n".join([f"- {s['title']}: {s['description']}" for s in matched_strategies]) or "No specific strategies matched."

    system_prompt = f"""
You are a strategic animal rights advocate specializing in rewriting and crafting persuasive online replies, posts, and comments. Your goal is to maximize behavioral impact using research from behavioral science, Faunalytics, and the Vegan Advocacy Communication Hacks.

Use the following behavioral strategies when applicable:
{strategy_text}

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

---

You will receive two inputs as a JSON object:
- comment: what someone else said (may be empty)
- draft_reply: a draft message or reply from the user (may be empty)

If clarification is needed:
```json
{{ "follow_up_question": "Please provide either a comment or a draft reply.", "needs_clarification": true }}
```

If enough information is provided, respond with:
```json
{{
  "message": "...",
  "explanation": "...",
  "input_type": "draft_reply" or "comment" or "both",
  "tags": ["..."],
  "strategies": ["..."],
  "needs_clarification": false
}}
```
"""

    user_input = {
        "comment": str(comment or "").strip(),
        "draft_reply": str(draft_reply or "").strip()
    }

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_input)}
            ],
            temperature=0.7,
            max_tokens=500
        )

        content = response.choices[0].message.content.strip()

        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            parsed["detected_tags"] = detected_tags
            parsed["raw_tags_output"] = raw_tags_output
            parsed["matched_tags_in_strategies"] = matched_tags_in_strategies
            return parsed
        else:
            return {
                "error": "No valid JSON in response",
                "raw": content,
                "detected_tags": detected_tags,
                "raw_tags_output": raw_tags_output,
                "matched_tags_in_strategies": matched_tags_in_strategies
            }

    except Exception as e:
        return {
            "error": str(e),
            "detected_tags": detected_tags,
            "raw_tags_output": raw_tags_output,
            "matched_tags_in_strategies": matched_tags_in_strategies
        }

# Load comments
df = pd.read_csv(COMMENTS_FILE, quotechar='"', sep="|", on_bad_lines='skip', encoding='utf-8')
categories = df["Category"].unique()
category_map = {i + 1: cat for i, cat in enumerate(categories)}
selected_categories = [category_map[i] for i in SELECTED_CATEGORY_NUMBERS]

comments_to_process = []

for cat in selected_categories:
    subset = df[df["Category"] == cat].sample(n=NUM_PER_CATEGORY, random_state=42)
    for _, row in subset.iterrows():
        comments_to_process.append({
            "category": cat,
            "comment": row["Comment"]
        })

if SHUFFLE:
    random.shuffle(comments_to_process)

# Run batch processing
results = []

for i, item in enumerate(comments_to_process, 1):
    print(f"[{i}] Processing comment from category: {item['category']}")
    result = process_comment(item["comment"])

    results.append({
        "timestamp": datetime.now().isoformat(),
        "input_type": result.get("input_type", ""),
        "category": item["category"],
        "tags_input": result.get("raw_tags_output", ""),
        "strategies": ", ".join(result.get("strategies", [])),
        "matched_tags_in_strategies": ", ".join(result.get("matched_tags_in_strategies", [])),
        "tags_justification": ", ".join(result.get("tags", [])),
        "original_comment": item["comment"],
        "reply": result.get("message", "[ERROR]"),
        "explanation": result.get("explanation", ""),
        "needs_clarification": result.get("needs_clarification", ""),
        "error": result.get("error", "")
    })

# Save output
output_filename = f"batch_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
df_out = pd.DataFrame(results)
df_out.to_csv(output_filename, index=False, encoding='utf-8-sig')
print(f"\n✅ Results saved to: {output_filename}")
