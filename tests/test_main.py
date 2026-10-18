import app.main


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_sse_test_streams_three_events(client, monkeypatch):
    monkeypatch.setattr(app.main, "SSE_TEST_INTERVAL", 0)
    r = client.get("/api/sse-test")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["x-accel-buffering"] == "no"
    assert r.text.count("data:") == 3
