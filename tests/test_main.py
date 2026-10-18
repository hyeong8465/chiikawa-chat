import json

import pytest

import app.main
from app import messages
from app.config import CHARACTER_DIR
from app.llm import CreditExhausted, StreamError

U = {"role": "user", "content": "안녕"}
A = {"role": "assistant", "content": "응"}


def post(client, msgs):
    return client.post("/api/chat", json={"messages": msgs})


def fake(events=None, exc=None):
    def f(messages):
        for e in events or []:
            yield e
        if exc:
            raise exc
    return f


@pytest.fixture
def ok(monkeypatch):
    monkeypatch.setattr(
        app.main, "stream_chat",
        fake([("delta", "안"), ("delta", "녕"), ("done", {"usage": None, "trace_id": "t1"})]),
    )


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_sse_test_removed(client):
    assert client.get("/api/sse-test").status_code == 404


def test_chat_streams(client, ok):
    r = post(client, [A, U])
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in r.text and "event: done" in r.text and '"trace_id": "t1"' in r.text


def test_chat_builds_prompt_with_history(client, monkeypatch):
    seen = {}
    def f(m):
        seen["m"] = m
        return iter([("done", {"trace_id": "t"})])
    monkeypatch.setattr(app.main, "stream_chat", f)
    post(client, [A, U])
    assert seen["m"][0]["role"] == "system" and seen["m"][-1]["role"] == "user"


def test_rejects_system_role(client):
    r = post(client, [{"role": "system", "content": "x"}, U])
    assert r.status_code == 400 and r.json()["code"] == "invalid"


def test_rejects_last_assistant(client):
    r = post(client, [U, A])
    assert r.status_code == 400 and r.json()["code"] == "invalid"


@pytest.mark.parametrize("c", ["", "   ", None, 5])
def test_rejects_empty_or_blank(client, c):
    r = post(client, [{"role": "user", "content": c}])
    assert r.status_code == 400 and r.json()["code"] == "invalid"


@pytest.mark.parametrize("body", [{}, {"messages": []}, {"messages": "x"}, {"messages": ["x"]}])
def test_rejects_malformed(client, body):
    assert client.post("/api/chat", json=body).json()["code"] == "invalid"


def test_rejects_non_json(client):
    assert client.post("/api/chat", content="not json").status_code == 400


def test_rejects_too_long(client):
    r = post(client, [{"role": "user", "content": "가" * 1001}])
    assert r.status_code == 400 and r.json() == {"code": "too_long", "message": messages.TOO_LONG}


def test_accepts_exactly_limit(client, ok):
    assert post(client, [{"role": "user", "content": "가" * 1000}]).status_code == 200


def test_rejects_long_assistant(client):
    r = post(client, [{"role": "assistant", "content": "가" * 2001}, U])
    assert r.status_code == 400 and r.json()["code"] == "too_long"


def test_rejects_too_many(client):
    msgs = [U if i % 2 == 0 else A for i in range(201)]
    assert post(client, msgs).json()["code"] == "too_many"


def test_credit_exhausted_event(client, monkeypatch):
    monkeypatch.setattr(app.main, "stream_chat", fake(exc=CreditExhausted()))
    r = post(client, [U])
    assert "event: error" in r.text and '"code": "credit"' in r.text


def test_midstream_error_event(client, monkeypatch):
    monkeypatch.setattr(app.main, "stream_chat", fake([("delta", "안")], exc=StreamError("x")))
    r = post(client, [U])
    assert "event: error" in r.text and '"code": "retry"' in r.text and "event: done" not in r.text


def test_intro(client):
    expected = (CHARACTER_DIR / "intro.md").read_text(encoding="utf-8").strip()
    assert client.get("/api/intro").json() == {"text": expected}


# --- 추천 답변·피드백 ---
def suggest(client, msgs=None):
    return client.post("/api/suggest", json={"messages": msgs or [U, A]})


def fake_complete(text=None, exc=None):
    def f(messages, model):
        if exc:
            raise exc
        return text, None
    return f


def test_suggest_three(client, monkeypatch):
    seen = {}
    def f(m, model):
        seen["m"], seen["model"] = m, model
        return '["나도 그래","왜 그래?","ㅋㅋ 진짜?"]', None
    monkeypatch.setattr(app.main, "complete", f)
    r = suggest(client)
    assert r.json() == {"suggestions": ["나도 그래", "왜 그래?", "ㅋㅋ 진짜?"]}
    assert seen["model"] == app.main.SUGGEST_MODEL and "안녕" in seen["m"][0]["content"]


def test_suggest_uses_only_last_6(client, monkeypatch):
    seen = {}
    def f(m, model):
        seen["t"] = m[0]["content"]
        return '["a","b","c"]', None
    monkeypatch.setattr(app.main, "complete", f)
    msgs = [{"role": "assistant" if i % 2 == 0 else "user", "content": f"m{i:02d}"} for i in range(10)]
    suggest(client, msgs[:9] + [{"role": "assistant", "content": "m99"}])
    assert "m99" in seen["t"] and "m03" not in seen["t"] and "m04" in seen["t"]


def test_suggest_broken_json_returns_empty(client, monkeypatch):
    monkeypatch.setattr(app.main, "complete", fake_complete("죄송해요"))
    assert suggest(client).json() == {"suggestions": []}


def test_suggest_credit_returns_empty(client, monkeypatch):
    monkeypatch.setattr(app.main, "complete", fake_complete(exc=CreditExhausted()))
    r = suggest(client)
    assert r.status_code == 200 and r.json() == {"suggestions": []}


def test_suggest_network_error_returns_empty(client, monkeypatch):
    monkeypatch.setattr(app.main, "complete", fake_complete(exc=StreamError("x")))
    assert suggest(client).json() == {"suggestions": []}


def test_suggest_last_user_is_400(client):
    assert suggest(client, [A, U]).status_code == 400


def test_chat_last_assistant_still_400(client):
    assert post(client, [U, A]).status_code == 400


def test_suggest_drops_over_30_chars(client, monkeypatch):
    long = "가" * 31
    monkeypatch.setattr(app.main, "complete", fake_complete(f'["a","b","{long}"]'))
    assert suggest(client).json() == {"suggestions": []}


def test_suggest_strips_and_drops_empty(client, monkeypatch):
    monkeypatch.setattr(app.main, "complete", fake_complete('[" a ","","b","c"]'))
    assert suggest(client).json() == {"suggestions": ["a", "b", "c"]}


def test_suggest_non_string_items_empty(client, monkeypatch):
    monkeypatch.setattr(app.main, "complete", fake_complete('[1,2,3]'))
    assert suggest(client).json() == {"suggestions": []}


def fb(client, body):
    return client.post("/api/feedback", json=body)


def test_feedback_204(client, monkeypatch):
    seen = []
    monkeypatch.setattr(app.main, "score", lambda t, v: seen.append((t, v)))
    assert fb(client, {"trace_id": "abc", "value": -1}).status_code == 204
    assert seen == [("abc", -1)]


@pytest.mark.parametrize("body", [
    {"trace_id": "abc", "value": 0},
    {"trace_id": "abc", "value": True},
    {"trace_id": "abc", "value": "1"},
    {"trace_id": "", "value": 1},
    {"trace_id": "  ", "value": 1},
    {"trace_id": 5, "value": 1},
    {"trace_id": "x" * 65, "value": 1},
    {"value": 1},
    [],
])
def test_feedback_bad(client, monkeypatch, body):
    monkeypatch.setattr(app.main, "score", lambda t, v: None)
    assert fb(client, body).status_code == 400


def test_feedback_bad_json(client):
    r = client.post("/api/feedback", content=b"{", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "비공식 팬메이드" in r.text


def test_static_app_js(client):
    assert client.get("/static/app.js").status_code == 200
