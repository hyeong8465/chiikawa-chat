import importlib

import pytest

import app.config as c


@pytest.fixture
def env():
    # 환경 변수를 되돌린 뒤 config를 다시 리로드해 오염 방지
    with pytest.MonkeyPatch.context() as mp:
        yield mp
    importlib.reload(c)


def test_prompt_version_falls_back(env):
    env.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    importlib.reload(c)
    assert isinstance(c.PROMPT_VERSION, str) and c.PROMPT_VERSION


def test_provider_pinned():
    assert c.PROVIDER["allow_fallbacks"] is False


def test_model_aliases():
    assert set(c.MODELS) == {"sonnet", "haiku", "judge", "judge_strong"}


def test_chat_model_env_override(env):
    env.setenv("CHAT_MODEL", "x/y")
    importlib.reload(c)
    assert c.CHAT_MODEL == "x/y"


def test_chat_model_default_is_sonnet(env):
    env.delenv("CHAT_MODEL", raising=False)
    importlib.reload(c)
    assert c.CHAT_MODEL == c.MODELS["sonnet"]


def test_reload_cleanup_after_override():
    # 앞선 override 테스트 뒤에도 실제 기본값이어야 함
    assert c.CHAT_MODEL != "x/y"
