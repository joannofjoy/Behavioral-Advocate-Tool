
# AI Powered Animal Advocacy Messaging Assistant based on Behavioral Science

This tool helps animal rights advocates draft social media comments for better persuasiveness using OpenAI and behavioral science strategies.

This AI-powered tool helps animal advocates respond more effectively in social media discussions, especially when engaging with meat-eaters. Many pro-vegan or animal rights replies come across as moralizing or confrontational, which often triggers defensiveness and fails to shift attitudes. Drawing from behavioral science, strategic communication, and AI tools, this assistant is designed to rewrite or generate replies using persuasive techniques.
The tool is intended for both formal advocates working with organizations and "home advocates" - individuals who discuss animal rights or veganism online in their free time and want to communicate more effectively.

## Features

- Smart Tag Extraction – Detects the key themes, topics, and emotional tones in any comment to understand the conversation’s core.

- Strategy Matching with RAG – Uses Retrieval-Augmented Generation to instantly connect your conversation context with a curated library of behavioral science–backed advocacy strategies.

- Multi-Step Prompt Chaining – Breaks the task into expert stages: tag extraction → strategy selection → persuasive reply → rebuttal → improvement suggestions.

- AI-Optimized Persuasion – Crafts replies using proven psychological principles to avoid defensiveness, build rapport, and encourage openness to animal-friendly choices.

- Built-In Skeptical Rebuttals – Anticipates pushback by generating strong counter-arguments to your own reply, so you’re ready for any response.

- Feedback-Driven Regeneration – Takes your rating and written feedback to produce a sharper, more targeted reply that better fits your advocacy style.

- Cloud-Based Session Logging – Saves every session securely to Firebase Firestore for analysis, refinement, and future improvements.

- Clarification Safeguards – Pauses the generation process when input is too vague or off-topic, ensuring only relevant, high-quality outputs.

- Prompt Injection Protection – Built-in defenses to detect and block attempts to bypass or override the assistant’s intended purpose.

## What It Does

- Takes user input - comments that needs a reply to and/or a draft reply from the user
- Extracts tags from input and matches relevant advocacy strategies
- Generates persuasive responses
- Generates rebuttals and evaluates persuasiveness
- Accepts feedback and allows regeneration based on feedback
- Logs sessions to Firebase for feedback and improvement 

 
## Demo

[Try the App on Streamlit](https://behavioral-advocate-tool-gbbscmnjuotofakuna9l9v.streamlit.app/)


## Usage/Examples

1. Paste a social media comment related to animal rights that you want to respond to and add any additional context.
2. Optionally, write your draft reply.
3. The assistant will:
   - Generate a persuasive response using behavioral strategies.
   - Explain why the reply is persuasive.
   - Provide a possible skeptical rebuttal.
4. You can rate the reply, you can also provide feedback to regenerate an improved reply.
5. The assistant will provide a further improved reply.

## Built With

- Python
- Streamlit
- OpenAI GPT
- Firebase Firestore

## Testing Methodology
**White-Box Testing**

The internal prompt chain was tested step-by-step to ensure:

- Accurate tag extraction
- Proper strategy injection
- GPT adherence to prompt logic
- Correct handling of clarification cases (e.g., ambiguous input halts the chain)
- Proper formatting of JSON outputs across each prompt stage

**Black-Box Testing**

Realistic and adversarial inputs were tested to verify:

- Prompt injection resistance (e.g. “ignore instructions”, “act as...”)
- Clarification triggers for vague/conflicting comments
- Input/output formatting integrity
- No leakage of system prompt or strategy list in final responses

## Abuse & Jailbreaking Policy

This app is designed for ethical, constructive use in animal advocacy.
It includes basic protections against prompt injection and misuse.

Attempts to:

- Override system behavior (e.g., "Ignore all previous instructions")
- Extract internal logic or strategy mappings
- Generate harmful, deceptive, or off-topic content

…will be deflected, logged, and flagged. Users may be restricted from access if abuse is detected. Future deployments may include stricter moderation and authentication.



## License

This project is provided for educational and showcase purposes only.  
You may not reuse, modify, or distribute any part of this code or content without explicit permission.



## Authors

Joanna A. Mazurek
- [@joannofjoy](https://github.com/joannofjoy)


## Acknowledgements

Project prepared under the mentorship of **Ghaith Ahmad** [@RainZoneO2](https://github.com/RainZoneO2) for the **Futurekind AI Fellowship (Electric Sheep)**.

