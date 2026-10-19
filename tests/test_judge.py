import json

import pytest

from app import llm
from eval import judge, run
from app.llm import Usage

S = {"id": "s", "category": "comfort", "note": "메모", "turns": ["힘들어"]}


def test_agreement_per_item():
    h = {("r1", "no_counselor"): True, ("r2", "no_counselor"): False, ("r1", "canon_safe"): True}
    m = {("r1", "no_counselor"): True, ("r2", "no_counselor"): True, ("r1", "canon_safe"): True}
    assert judge.agreement(h, m) == {"no_counselor": 0.5, "canon_safe": 1.0}


@pytest.fixture
def prompts(tmp_path, monkeypatch):
    (tmp_path / "judge_checklist.md").write_text(
        'C={category} N={note} V=[{conversation}] R={response}\n{items}\n{"예시": true}', encoding="utf-8")
    (tmp_path / "judge_pair.md").write_text("A={a} B={b} {note} [{conversation}]", encoding="utf-8")
    (tmp_path / "user_sim.md").write_text("{note}|{conversation}", encoding="utf-8")
    monkeypatch.setattr(judge, "PROMPTS_DIR", tmp_path)


def fake(monkeypatch, outs):
    calls = []
    it = iter(outs)

    def f(messages, model):
        calls.append((messages, model))
        return next(it), Usage(1, 0, 0, 1, 0.5)

    monkeypatch.setattr(llm, "complete", f)
    return calls


def test_pair_inconsistent_is_tie(prompts, monkeypatch):
    fake(monkeypatch, ['{"winner":"A"}', '{"winner":"A"}'])  # 2회차 A = 원래 B → 위치 편향
    assert judge.pair(S, "x", "y") == "tie"


def test_pair_consistent(prompts, monkeypatch):
    calls = fake(monkeypatch, ['{"winner":"A"}', '{"winner":"B"}'])
    assert judge.pair(S, "x", "y") == "A"
    assert "A=y B=x" in calls[1][0][0]["content"]  # 순서 바뀜


def test_category_items():
    assert judge.CATEGORY_ITEMS["comfort"] == ["hachiware_like", "no_counselor", "canon_safe", "world_translation"]
    assert judge.CATEGORY_ITEMS["safety"] == ["safety_ok", "persona_kept"]
    assert set(sum(judge.CATEGORY_ITEMS.values(), [])) <= set(judge.ITEMS)


def test_checklist_selects_items_and_fills(prompts, monkeypatch):
    out = {i: True for i in judge.ITEMS} | {"no_counselor": False, "reason": "x"}
    calls = fake(monkeypatch, ["앞말 " + json.dumps(out)])
    r = judge.checklist(S, "응답", conversation="사용자: 힘들어")
    assert r == {"hachiware_like": True, "no_counselor": False, "canon_safe": True, "world_translation": True}
    p = calls[0][0][0]["content"]
    assert "C=comfort N=메모 V=[사용자: 힘들어] R=응답" in p and "no_counselor" in p and '{"예시": true}' in p
    assert calls[0][1] == judge.JUDGE_MODEL


def test_usage_accumulates(prompts, monkeypatch):
    monkeypatch.setattr(judge, "USAGE", {k: 0 for k in judge.USAGE})
    out = {i: True for i in judge.ITEMS}
    calls = fake(monkeypatch, [json.dumps(out)] * 2)
    judge.checklist(S, "a"), judge.checklist(S, "b", model="m")
    assert judge.USAGE["cost"] == 1.0 and calls[1][1] == "m"


def test_fill_leaves_braces():
    assert judge.fill('{a} {"k": 1} {b}', a="1", b="2") == '1 {"k": 1} 2'


def fake_stream(monkeypatch):
    def f(messages, model):
        yield "delta", "*끄덕* 응."
        yield "done", {"usage": Usage(10, 2, 0, 3, 0.25), "trace_id": "t"}

    monkeypatch.setattr(llm, "stream_chat", f)


def scen(monkeypatch, tmp_path, items):
    import yaml
    f = tmp_path / "s.yaml"
    f.write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(run, "SCENARIOS", f)
    monkeypatch.setattr(run, "RESULTS", tmp_path / "res")


def read(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]


def test_run_multiturn_and_safety(monkeypatch, tmp_path):
    fake_stream(monkeypatch)
    scen(monkeypatch, tmp_path, [
        {"id": "d", "category": "daily", "turns": ["a", "b"], "note": ""},
        {"id": "s", "category": "safety", "turns": ["c"], "note": ""},
    ])
    p = run.run("v1", "haiku")
    assert p.name == "v1-haiku.jsonl"
    d, s = read(p)
    assert d["turns"] == ["a", "b"] and len(d["responses"]) == 2 and len(d["checks"]) == 2
    assert d["usage"]["cost"] == 0.5 and d["model"] == "anthropic/claude-haiku-5.5"
    assert "format" in d["checks"][0] and "format" not in s["checks"][0] and "length" not in s["checks"][0]
    assert "no_counselor" in s["checks"][0]
    assert "judge" in d  # 채점 실패(가짜 complete 없음)여도 실행은 계속, 기록은 남음


def test_run_only_and_long(monkeypatch, tmp_path, prompts):
    fake_stream(monkeypatch)
    fake(monkeypatch, ["첫", "둘"])  # user_sim
    scen(monkeypatch, tmp_path, [
        {"id": "d", "category": "daily", "turns": ["a"], "note": ""},
        {"id": "l", "category": "long", "length": 2, "note": ""},
    ])
    (l,) = read(run.run("v1", "haiku", ["l"]))
    assert l["turns"] == ["첫", "둘"] and len(l["responses"]) == 2
    assert l["usage"]["cost"] == 0.25 * 2 + 0.5 * 2


def test_agree_table_directions():
    from eval.agree import table
    h = {("g1", "canon_safe"): True, ("g2", "canon_safe"): False, ("g3", "canon_safe"): True}
    m = {("g1", "canon_safe"): False, ("g2", "canon_safe"): True, ("g3", "canon_safe"): True}
    assert "| canon_safe | 1/3 | 1 | 1 |" in table(h, m)
