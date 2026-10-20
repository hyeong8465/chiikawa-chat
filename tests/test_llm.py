import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest
from langfuse.openai import OpenAI

import app.llm as llm
from app.llm import CreditExhausted, StreamError, Usage, complete, extract_json, stream_chat

MSGS = [{"role": "user", "content": "안녕"}]
FAKE_CACHED, FAKE_WRITE, FAKE_COST = 100, 20, 0.0123
USAGE = {
    "prompt_tokens": 150, "completion_tokens": 7, "cost": FAKE_COST,
    "prompt_tokens_details": {"cached_tokens": FAKE_CACHED, "cache_write_tokens": FAKE_WRITE},
}


def _c(text=None, finish=None, **extra):
    ch = [{"index": 0, "delta": {"content": text} if text else {}, "finish_reason": finish}]
    return {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "m", "choices": ch, **extra}


def sse(*chunks):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


GOOD = lambda: sse(_c("안"), _c("녕"), _c(finish="stop"), _c(choices=[], usage=USAGE))


def err(code, body=None):
    return httpx.Response(code, json={"error": body or {"message": "e", "code": code}})


def install(monkeypatch, *responses):
    """실제 Langfuse OpenAI 클라이언트 + MockTransport. 요청 목록 반환"""
    reqs, queue = [], list(responses)

    def handler(req):
        reqs.append(json.loads(req.content))
        return queue.pop(0)()

    client = OpenAI(
        base_url="https://x/api/v1", api_key="k", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(llm, "_client", lambda: client)
    return reqs


def test_extract_json_with_prose():
    assert extract_json('여기 있어\n{"a": [1]}\n끝') == {"a": [1]}


def test_extract_json_raises():
    with pytest.raises(ValueError):
        extract_json("없음")


def test_extract_json_scalar_raises():
    with pytest.raises(ValueError):
        extract_json("123")


def test_stream_yields_deltas_then_done(monkeypatch):
    install(monkeypatch, GOOD)
    ev = list(stream_chat(MSGS))
    assert [k for k, _ in ev] == ["delta", "delta", "done"]
    assert isinstance(ev[-1][1]["usage"], Usage) and ev[-1][1]["trace_id"]


def test_usage_mapping(monkeypatch):
    install(monkeypatch, GOOD)
    u = list(stream_chat(MSGS))[-1][1]["usage"]
    assert (u.input_tokens, u.output_tokens) == (150, 7)
    assert (u.cache_read_tokens, u.cache_write_tokens, u.cost) == (FAKE_CACHED, FAKE_WRITE, FAKE_COST)


def test_request_body_sent(monkeypatch):
    reqs = install(monkeypatch, GOOD)
    list(stream_chat(MSGS))
    b = reqs[0]
    assert b["provider"]["allow_fallbacks"] is False
    assert b["usage"] == {"include": True} and b["reasoning"]
    assert b["max_tokens"] == 1024


def test_provider_only_for_anthropic(monkeypatch):
    res = lambda: httpx.Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0, "model": "m", "usage": USAGE,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
    })
    reqs = install(monkeypatch, res, res, res)
    text, u = complete(MSGS, model="openai/gpt-5.6-luna")
    assert text == "ok" and u.output_tokens == 7
    assert "provider" not in reqs[0] and "reasoning" not in reqs[0]
    complete(MSGS, model="anthropic/claude-haiku-5.5")
    assert reqs[1]["reasoning"] == {"enabled": False}
    complete(MSGS, model="anthropic/claude-sonnet-5.5", reasoning=True)  # 변환기
    assert reqs[2]["reasoning"] == llm.REASONING


def test_402_raises_credit_exhausted(monkeypatch):
    install(monkeypatch, lambda: err(402))
    with pytest.raises(CreditExhausted):
        list(stream_chat(MSGS))


def test_403_key_limit_raises_credit_exhausted(monkeypatch):
    install(monkeypatch, lambda: err(403, {"message": "x", "metadata": {"limit_source": "key"}}))
    with pytest.raises(CreditExhausted):
        list(stream_chat(MSGS))


def test_403_without_limit_is_plain_error(monkeypatch):
    install(monkeypatch, lambda: err(403))
    with pytest.raises(openai.APIStatusError):
        list(stream_chat(MSGS))


def test_midstream_error_raises(monkeypatch):
    install(monkeypatch, lambda: sse(_c("안"), {"error": {"message": "boom", "code": 500}}))
    with pytest.raises(StreamError):
        list(stream_chat(MSGS))


def test_midstream_402_raises_credit(monkeypatch):
    install(monkeypatch, lambda: sse(_c("안"), {"error": {"message": "no", "code": 402}}))
    with pytest.raises(CreditExhausted):
        list(stream_chat(MSGS))


def test_finish_reason_error_raises(monkeypatch):
    install(monkeypatch, lambda: sse(_c("안"), _c(finish="error")))
    with pytest.raises(StreamError):
        list(stream_chat(MSGS))


def test_no_finish_reason_raises(monkeypatch):
    install(monkeypatch, lambda: sse(_c("안")))
    with pytest.raises(StreamError):
        list(stream_chat(MSGS))


def test_complete_200_with_error_body_raises(monkeypatch):
    install(monkeypatch, lambda: httpx.Response(200, json={"error": {"code": 500}, "choices": None}))
    with pytest.raises(StreamError):
        complete(MSGS, model="openai/gpt-5.6-luna")


def test_usage_cost_missing_is_zero():
    assert llm._usage(NS(prompt_tokens=1, completion_tokens=1)).cost == 0.0


def test_retry_once_on_429(monkeypatch):
    reqs = install(monkeypatch, lambda: err(429), GOOD)
    assert list(stream_chat(MSGS))[-1][0] == "done"
    assert len(reqs) == 2


def test_no_third_attempt(monkeypatch):
    reqs = install(monkeypatch, lambda: err(503), lambda: err(503))
    with pytest.raises(openai.APIStatusError):
        list(stream_chat(MSGS))
    assert len(reqs) == 2


def test_retry_on_connection_error(monkeypatch):
    def boom():
        raise httpx.ConnectError("x")
    reqs = install(monkeypatch, boom, GOOD)
    assert list(stream_chat(MSGS))[-1][0] == "done"
    assert len(reqs) == 2


def test_real_client_settings_without_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    llm._client.cache_clear()
    c = llm._client()
    llm._client.cache_clear()
    assert c.max_retries == 0 and c.timeout == 60


def test_score_records_feedback(monkeypatch):
    import langfuse
    seen = {}
    class C:
        def create_score(self, **kw):
            seen.update(kw)
    monkeypatch.setattr(langfuse, "get_client", lambda: C())
    llm.score("t1", 1)
    assert seen["name"] == "feedback" and seen["trace_id"] == "t1" and seen["value"] == 1
    assert seen["score_id"] == "t1-feedback"  # 바꾸거나 취소하면 덮어씀


def test_score_ignores_errors(monkeypatch):
    import langfuse
    class C:
        def create_score(self, **kw):
            raise RuntimeError("boom")
    monkeypatch.setattr(langfuse, "get_client", lambda: C())
    llm.score("t1", -1)
    monkeypatch.setattr(langfuse, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    llm.score("t1", -1)
