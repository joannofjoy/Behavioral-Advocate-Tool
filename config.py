# This file is the one place that knows how to find configuration values:
# the OpenAI API key, the Firebase credentials, and a few constants (which
# GPT model to call, and how long/creative its answers can be) that used to
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
# st.secrets instead (see get_openai_api_key/get_firebase_config below).
load_dotenv()

# The exact GPT model used for every call the app makes.
MODEL_NAME = "gpt-4o"

# "Temperature" controls how random/creative the model's replies are: 0 is
# very predictable and repetitive, 1 is much more varied. "max_tokens" caps
# how long the model's reply is allowed to be.
TAG_EXTRACTION_TEMPERATURE = 0.3
TAG_EXTRACTION_MAX_TOKENS = 100

REPLY_TEMPERATURE = 0.7
REPLY_MAX_TOKENS = 400

REBUTTAL_MAX_TOKENS = 400

STRATEGIES_PATH = "strategies.json"


def get_openai_api_key():
    """Work out which OpenAI API key to use.

    Locally, this comes from the "api_key" entry in a .env file (loaded
    above). When deployed on Streamlit Cloud, it instead comes from
    Streamlit's built-in secrets manager (st.secrets), which is why we try
    that second and let it override the local value when it's available.
    """
    api_key = os.getenv("api_key")
    # A try/except block runs the "try" code, and if any error happens
    # inside it, jumps straight to "except" instead of crashing the app.
    # Here, st.secrets["openai"] raises an error whenever no Streamlit
    # secrets are configured (e.g. when running locally), and in that case
    # we just want to keep the .env value, so "except" does nothing ("pass").
    try:
        api_key = st.secrets["openai"]["api_key"]
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
