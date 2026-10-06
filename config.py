# This file is the one place that knows how to find configuration values:
# the OpenRouter API key, the Firebase credentials, and a few constants
# (which model to call, how long/creative its answers can be) that used to
# be scattered as literal numbers and strings throughout the app. Keeping
# them here means changing a model name or a token limit only has to happen
# in one place.

import json
import os

import streamlit as st
from dotenv import load_dotenv

# load_dotenv() reads a local ".env" file (if one exists) and copies its
# key=value pairs into this process's environment variables, so the
# os.getenv(...) call below can see them. This is only used for local
# development - when the app runs on Streamlit Cloud, secrets come from
# st.secrets instead (see get_llm_api_key/get_firebase_config below).
load_dotenv()

# OpenRouter exposes an OpenAI-compatible API - the same "openai" Python
# package works, it just needs to be pointed at this URL instead of
# OpenAI's own servers.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# The model used for every call the app makes, in OpenRouter's
# "provider/model-name" format. Reading it from an environment variable
# means the model can be swapped (e.g. to compare cost/quality) without a
# code change - see the OPENROUTER_MODEL entry in .env.
#
# Cheapest model that's still genuinely good for this task, not just the
# cheapest model period: OpenAI's "nano"-tier models are cheaper per token
# but are explicitly positioned for simple, high-volume tasks and show
# higher hallucination rates - a bad trade for an app whose whole job is
# careful, persuasive phrasing. Once output tokens (the bulk of the cost
# here) are factored in, gpt-4o-mini is actually cheaper than every newer
# "mini"-tier successor too, and it's the one model already validated via
# eval/run_eval.py (scored 4.3-5.0/5 across every rubric dimension).
MODEL_NAME = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

# "Temperature" controls how random/creative the model's replies are: 0 is
# very predictable and repetitive, 1 is much more varied. "max_tokens" caps
# how long the model's reply is allowed to be.
TAG_EXTRACTION_TEMPERATURE = 0.3
TAG_EXTRACTION_MAX_TOKENS = 100

REPLY_TEMPERATURE = 0.7
# Raised from 400 now that the explanation field is meant to be genuinely
# educational (naming techniques and reasoning), not just a short summary -
# the old cap risked truncating a fuller explanation into invalid JSON.
REPLY_MAX_TOKENS = 600

STRATEGIES_PATH = "strategies.json"

# Caps used to bound cost/abuse on the public demo: the longest comment or
# draft reply the app will send to the model, and the most replies one
# browser session is allowed to generate.
MAX_INPUT_CHARS = 2000
MAX_GENERATIONS_PER_SESSION = 15


def get_llm_api_key():
    """Work out which OpenRouter API key to use.

    Locally, this comes from the "OPENROUTER_API_KEY" entry in a .env file
    (loaded above). When deployed on Streamlit Cloud, it instead comes from
    Streamlit's built-in secrets manager (st.secrets), which is why we try
    that second and let it override the local value when it's available.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    # A try/except block runs the "try" code, and if any error happens
    # inside it, jumps straight to "except" instead of crashing the app.
    # Here, st.secrets["openrouter"] raises an error whenever no Streamlit
    # secrets are configured (e.g. when running locally), and in that case
    # we just want to keep the .env value, so "except" does nothing ("pass").
    try:
        api_key = st.secrets["openrouter"]["api_key"]
    except Exception:
        pass
    return api_key


def get_firebase_config():
    """Work out the Firebase service-account credentials to use, if any.

    Tries Streamlit secrets first (used on Streamlit Cloud), then falls back
    to a local firebase_key.json file (used for local development). Returns
    None if neither is available, meaning Firestore logging gets skipped.
    """
    try:
        # dict(...) turns Streamlit's secrets object into a plain Python
        # dictionary, which is the format the Firebase library expects.
        firebase_config = dict(st.secrets["firebase"])
        # Streamlit secrets store the private key with literal backslash-n
        # text instead of real newline characters, so this swaps them back
        # in - the Firebase library needs actual newlines to work.
        firebase_config["private_key"] = firebase_config["private_key"].replace("\\n", "\n")
        return firebase_config
    except Exception:
        pass
    if os.path.exists("firebase_key.json"):
        # "with open(...) as f" is a context manager: it opens the file,
        # hands it to us as "f", and automatically closes it again once the
        # indented block below finishes - even if an error happens inside.
        with open("firebase_key.json") as f:
            return json.load(f)
    return None
