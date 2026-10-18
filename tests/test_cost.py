import json

import pytest

from app.llm import Usage
from eval import cost_check, report


def test_savings():
    assert cost_check.savings({"none": 1.0, "system": 0.4, "full": 0.2}) == {"system": 0.6, "full": 0.8}


def test_replay_and_file(tmp_path, monkeypatch):
    seen = []

    def fake_stream(messages, model=None):
        # cache 조건은 build_messages 결과의 cache_control 개수로 역추적
        n = sum("cache_control" in p for m in messages for p in (m["content"] if isinstance(m["content"], list) else []))
        seen.append((n, len(messages)))
        yield "delta", f"답{len(seen)}"
        yield "done", {"usage": Usage(100, 50 if n == 2 else 0, 5, 3, 0.1 if n == 2 else 0.2), "trace_id": "t"}

    monkeypatch.setattr(cost_check.llm, "stream_chat", fake_stream)
    monkeypatch.setattr(cost_check, "RESULTS", tmp_path)
    monkeypatch.setattr(cost_check, "USER_TURNS", ["a", "b", "c"])
    out = cost_check.run(3)
    assert [n for n, _ in seen] == [0] * 3 + [1] * 3 + [2] * 3  # none, system, full 순
    assert seen[2][1] == 1 + 5  # 3턴째 메시지: system + user/assistant 5개
    d = json.loads((tmp_path / "cost.json").read_text(encoding="utf-8"))
    assert set(d["totals"]) == {"none", "system", "full"} and len(d["turns"]["full"]) == 3
    assert d["turns"]["full"][1]["cache_read"] == 50
    assert d["totals"]["full"]["cost"] == 0.1 * 3 and d["savings"]["full"] == pytest.approx(0.5)
    assert d["ok"] is True and out == d


def _row(id, cat, model, label, ok, judge, cost, seconds=None):
    r = {"id": id, "model": model, "label": label, "checks": [{"format": ok}, {"format": True}],
         "judge": judge, "usage": {"cost": cost}}
    if seconds is not None:
        r["seconds"] = seconds
    return r


def test_summarize(tmp_path, monkeypatch):
    p = tmp_path / "v1-haiku.jsonl"
    rows = [_row("daily-01", "daily", "m/haiku", "v1", False, {"hachiware_like": True}, 0.2, 2.0),
            _row("long-01", "long", "m/haiku", "v1", True, {"error": "x"}, 0.4, 4.0)]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    t = report.summarize([p])
    assert "m/haiku" in t and "v1" in t and "75%" in t and "100%" in t and "$0.3000" in t and "3.0" in t
    t2 = report.summarize([p], exclude_category="long")
    assert "50%" in t2 and "$0.2000" in t2
