from types import SimpleNamespace as NS

import httpx
import openai
import pytest

import app.llm as llm
from app.llm import CreditExhausted, StreamError, Usage, complete, extract_json, stream_chat

MSGS = [{"role": "user", "content": "안녕"}]
FAKE_CACHED, FAKE_WRITE, FAKE_COST = 100, 20, 0.0123


def _chunk(text=None, usage=None, error=None, finish=None):
    ch = [NS(delta=NS(content=text), finish_reason=finish)]
    return NS(choices=ch, usage=usage, error=error)


USAGE = NS(
    prompt_tokens=150, completion_tokens=7, cost=FAKE_COST,
    prompt_tokens_details=NS(cached_tokens=FAKE_CACHED, cache_write_tokens=FAKE_WRITE),
)
GOOD = [_chunk("안"), _chunk("녕"), NS(choices=[], usage=USAGE, error=None)]


def _status_err(code, body=None):
    req = httpx.Request("POST", "http://x")
    return openai.APIStatusError("e", response=httpx.Response(code, request=req), body=body)


class Fake:
    def __init__(self, script):
        self.script = list(script)  # 호출마다 하나씩: 예외 또는 결과
        self.calls = 0
        self.last_kwargs = None
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls += 1
        self.last_kwargs = kw
        r = self.script.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def install(monkeypatch, *script):
    f = Fake(script or [iter(GOOD)])
    monkeypatch.setattr(llm, "_client", lambda: f)
    return f


def test_extract_json_with_prose():
    assert extract_json('여기 있어\n{"a": [1]}\n끝') == {"a": [1]}


def test_extract_json_raises():
    with pytest.raises(ValueError):
        extract_json("없음")


def test_stream_yields_deltas_then_done(monkeypatch):
    install(monkeypatch)
    ev = list(stream_chat(MSGS))
    assert [k for k, _ in ev] == ["delta", "delta", "done"]
    assert isinstance(ev[-1][1]["usage"], Usage) and ev[-1][1]["trace_id"]


def test_provider_and_version_sent(monkeypatch):
    f = install(monkeypatch)
    list(stream_chat(MSGS))
    kw = f.last_kwargs
    assert kw["extra_body"]["provider"]["allow_fallbacks"] is False
    assert kw["extra_body"]["usage"] == {"include": True}
    assert kw["extra_body"]["reasoning"]
    assert kw["metadata"]["prompt_version"]


def test_402_raises_credit_exhausted(monkeypatch):
    install(monkeypatch, _status_err(402))
    with pytest.raises(CreditExhausted):
        list(stream_chat(MSGS))


def test_403_key_limit_raises_credit_exhausted(monkeypatch):
    install(monkeypatch, _status_err(403, {"metadata": {"limit_source": "key"}}))
    with pytest.raises(CreditExhausted):
        list(stream_chat(MSGS))


def test_403_without_limit_is_plain_error(monkeypatch):
    install(monkeypatch, _status_err(403, {"message": "x"}))
    with pytest.raises(openai.APIStatusError):
        list(stream_chat(MSGS))


def test_midstream_error_raises(monkeypatch):
    install(monkeypatch, iter([_chunk("안"), _chunk(error={"code": 500})]))
    with pytest.raises(StreamError):
        list(stream_chat(MSGS))


def test_finish_reason_error_raises(monkeypatch):
    install(monkeypatch, iter([_chunk("안"), _chunk(finish="error")]))
    with pytest.raises(StreamError):
        list(stream_chat(MSGS))


def test_complete_200_with_error_body_raises(monkeypatch):
    install(monkeypatch, NS(error={"code": 500}, choices=None, usage=None))
    with pytest.raises(StreamError):
        complete(MSGS, model="openai/gpt-5.6-luna")


def test_provider_only_for_anthropic(monkeypatch):
    res = NS(error=None, choices=[NS(message=NS(content="ok"), finish_reason="stop")], usage=USAGE)
    f = install(monkeypatch, res)
    text, u = complete(MSGS, model="openai/gpt-5.6-luna")
    assert text == "ok" and u.output_tokens == 7
    assert "provider" not in f.last_kwargs["extra_body"]
    assert "reasoning" not in f.last_kwargs["extra_body"]


def test_usage_mapping(monkeypatch):
    install(monkeypatch)
    u = list(stream_chat(MSGS))[-1][1]["usage"]
    assert (u.input_tokens, u.output_tokens) == (150, 7)
    assert (u.cache_read_tokens, u.cache_write_tokens, u.cost) == (FAKE_CACHED, FAKE_WRITE, FAKE_COST)


def test_usage_cost_missing_is_zero():
    assert llm._usage(NS(prompt_tokens=1, completion_tokens=1)).cost == 0.0


def test_retry_once_on_429(monkeypatch):
    f = install(monkeypatch, _status_err(429), iter(GOOD))
    assert list(stream_chat(MSGS))[-1][0] == "done"
    assert f.calls == 2


def test_no_third_attempt(monkeypatch):
    f = install(monkeypatch, _status_err(503), _status_err(503))
    with pytest.raises(openai.APIStatusError):
        list(stream_chat(MSGS))
    assert f.calls == 2


def test_client_works_without_langfuse_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert llm._client() is not None
