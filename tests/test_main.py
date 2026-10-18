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
