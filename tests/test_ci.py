import json

from eval import ci
from eval.report import MARK


def write(p, rows, meta):
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [{"meta": meta}, *rows]), encoding="utf-8")
    return p


ROW = {"id": "a", "label": "x", "model": "m", "checks": [{"format": True}], "judge": {"canon_safe": True}, "usage": {"cost": 0.1}}
J = {"model": "j", "prompt": "p1", "reference": "r1", "code": "c1"}


def test_judge_changed():
    assert not ci.judge_changed({"judge": J}, {"judge": J})
    assert ci.judge_changed({"judge": J | {"prompt": "p2"}}, {"judge": J})
    assert ci.judge_changed(None, {"judge": J})  # 옛 기준선은 채점자 모름 → 다시 채점


def test_pr_body_no_baseline(tmp_path):
    pr = write(tmp_path / "p.jsonl", [ROW], {"commit": "c2", "judge": J})
    t = ci.pr_body(None, pr, "c2")
    assert t.startswith(MARK) and "기준선 없음" in t and "| x |" in t


def test_pr_body_rejudges_when_judge_changed(tmp_path, monkeypatch):
    base = write(tmp_path / "b.jsonl", [ROW], {"commit": "c1", "judge": J | {"prompt": "old"}})
    pr = write(tmp_path / "p.jsonl", [ROW], {"commit": "c2", "judge": J})
    called = []

    def fake(path):
        called.append(path)
        return write(tmp_path / "b.rejudge.jsonl", [ROW], {"commit": "c1", "judge": J, "source": "b.jsonl"})
    monkeypatch.setattr(ci.run, "rejudge", fake)
    t = ci.pr_body(base, pr, "c1")
    assert called == [base] and "기준선 다시 채점: 함(b.jsonl)" in t


def test_pr_body_same_judge_no_rejudge(tmp_path, monkeypatch):
    base = write(tmp_path / "b.jsonl", [ROW], {"commit": "c1", "judge": J})
    pr = write(tmp_path / "p.jsonl", [ROW], {"commit": "c2", "judge": J})
    monkeypatch.setattr(ci.run, "rejudge", lambda p: (_ for _ in ()).throw(AssertionError("다시 채점 안 함")))
    assert "기준선 다시 채점: 안 함" in ci.pr_body(base, pr, "c1")


def test_failure_body_marker():
    t = ci.failure_body("CreditExhausted")
    assert t.startswith(MARK) and "CreditExhausted" in t and "실패" in t
