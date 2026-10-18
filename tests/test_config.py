def test_prompt_version_falls_back(monkeypatch):
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    import importlib, app.config as c
    importlib.reload(c)
    assert isinstance(c.PROMPT_VERSION, str) and c.PROMPT_VERSION


def test_provider_pinned():
    from app.config import PROVIDER
    assert PROVIDER["allow_fallbacks"] is False


def test_model_aliases():
    from app.config import MODELS
    assert set(MODELS) == {"sonnet", "haiku", "judge", "judge_strong"}


def test_chat_model_env_override(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "x/y")
    import importlib, app.config as c
    importlib.reload(c)
    assert c.CHAT_MODEL == "x/y"
