# Tests for config.py's key-resolution fallback logic: local .env/environment
# variables versus Streamlit Cloud's st.secrets, and which one wins when both
# are present.

import config


def test_llm_api_key_falls_back_to_env_var_when_no_secrets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    # Streamlit's st.secrets normally raises when no secrets.toml is
    # configured; a plain empty dict reproduces that same "nothing here"
    # behavior (st.secrets["openrouter"] raises KeyError) without needing a
    # real Streamlit run context.
    monkeypatch.setattr(config.st, "secrets", {})
    assert config.get_llm_api_key() == "env-key"


def test_llm_api_key_prefers_secrets_over_env_var(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    monkeypatch.setattr(config.st, "secrets", {"openrouter": {"api_key": "secrets-key"}})
    assert config.get_llm_api_key() == "secrets-key"


def test_firebase_config_returns_none_when_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(config.st, "secrets", {})
    # Move to an empty temp directory so a real firebase_key.json elsewhere
    # on disk can't accidentally make this test pass for the wrong reason.
    monkeypatch.chdir(tmp_path)
    assert config.get_firebase_config() is None


def test_firebase_config_reads_local_file_when_no_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(config.st, "secrets", {})
    monkeypatch.chdir(tmp_path)
    (tmp_path / "firebase_key.json").write_text('{"project_id": "demo"}', encoding="utf-8")
    assert config.get_firebase_config() == {"project_id": "demo"}


def test_firebase_config_from_secrets_restores_real_newlines(monkeypatch):
    monkeypatch.setattr(
        config.st,
        "secrets",
        {"firebase": {"project_id": "demo", "private_key": "line1\\nline2"}},
    )
    result = config.get_firebase_config()
    assert result["private_key"] == "line1\nline2"
