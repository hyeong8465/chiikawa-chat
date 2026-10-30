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

    def f(messages, model, max_tokens=None, **k):
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


def test_checklist_adds_call_usage(prompts, monkeypatch):
    # 시나리오 줄마다 채점 비용을 남기려고 호출 단위 사용량을 넘겨받은 dict에 더함
    fake(monkeypatch, [json.dumps({i: True for i in judge.ITEMS})] * 2)
    u = {k: 0 for k in judge.USAGE}
    r = judge.checklist(S, "a", usage=u)
    judge.checklist(S, "b", usage=u)
    assert u["cost"] == 1.0 and u["input_tokens"] == 2 and "usage" not in r


def test_fill_leaves_braces():
    assert judge.fill('{a} {"k": 1} {b}', a="1", b="2") == '1 {"k": 1} 2'


def fake_stream(monkeypatch):
    def f(messages, model, max_tokens=None, **k):
        yield "delta", "*끄덕* 응."
        yield "done", {"usage": Usage(10, 2, 0, 3, 0.25), "trace_id": "t"}

    monkeypatch.setattr(llm, "stream_chat", f)


def scen(monkeypatch, tmp_path, items):
    import yaml
    f = tmp_path / "s.yaml"
    f.write_text(yaml.safe_dump(items, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(run, "SCENARIOS", f)
    monkeypatch.setattr(run, "RESULTS", tmp_path / "res")


def read(p):  # 시나리오 줄만(첫 줄 실행 정보 제외)
    return [r for r in map(json.loads, p.read_text(encoding="utf-8").splitlines()) if "meta" not in r]


def meta_of(p):
    return json.loads(p.read_text(encoding="utf-8").splitlines()[0])["meta"]


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


def test_run_writes_meta_first(monkeypatch, tmp_path):
    fake_stream(monkeypatch)
    scen(monkeypatch, tmp_path, [{"id": "d", "category": "daily", "turns": ["a"], "note": ""},
                                 {"id": "e", "category": "daily", "turns": ["b"], "note": ""}])
    m = meta_of(run.run("v1", "haiku"))
    assert set(m) >= {"prompts", "judge", "sim", "scenarios", "checks", "gen", "commit", "dirty", "time"}
    assert set(m["prompts"]) == {"platform", "character", "chat_guide", "examples", "intro", "episodes"}
    assert m["scenarios"]["count"] == 2 and m["scenarios"]["only"] == []
    assert m["gen"]["model"] == "anthropic/claude-haiku-5.5" and m["sim"]["model"] == "anthropic/claude-haiku-5.5"
    assert len(m["judge"]["reference"]) == 8 and m["judge"]["model"] == judge.JUDGE_MODEL


def test_meta_changes_with_prompt(monkeypatch, tmp_path):
    import shutil
    d = tmp_path / "c"
    shutil.copytree(run.CHARACTER_DIR, d)
    monkeypatch.setattr(run, "CHARACTER_DIR", d)
    a = run.run_meta("haiku", [], None)
    (d / "character.md").write_text((d / "character.md").read_text(encoding="utf-8") + "!", encoding="utf-8")
    b = run.run_meta("haiku", [], None)
    assert [k for k in a["prompts"] if a["prompts"][k] != b["prompts"][k]] == ["character"]


def test_row_usage_parts(monkeypatch, tmp_path, prompts):
    fake_stream(monkeypatch)
    fake(monkeypatch, ["첫", "둘"])  # user_sim

    def j(s, resp, convo, with_reason, usage):
        usage["cost"] += 0.1
        return {"ok": True}
    monkeypatch.setattr(judge, "checklist", j)
    scen(monkeypatch, tmp_path, [{"id": "l", "category": "long", "length": 2, "note": ""}])
    (l,) = read(run.run("v1", "haiku"))
    p = l["usage_parts"]
    assert p["chat"]["cost"] == 0.5 and p["sim"]["cost"] == 1.0 and p["judge"]["cost"] == 0.1
    assert l["usage"]["cost"] == 1.5  # 기존 뜻 그대로: 생성 + 사용자 흉내


TWO = [{"id": "d", "category": "daily", "turns": ["a"], "note": ""},
       {"id": "e", "category": "daily", "turns": ["b"], "note": ""}]


def ok_judge(monkeypatch):
    monkeypatch.setattr(judge, "checklist", lambda *a, **k: {"ok": True})


def count_stream(monkeypatch, fail_on=()):
    # 생성 횟수를 세는 가짜 stream. fail_on의 사용자 말이면 크레딧 소진
    calls = []

    def f(messages, model, max_tokens=None, **k):
        c = messages[-1]["content"]
        calls.append(c if isinstance(c, str) else c[0]["text"])  # 마지막 메시지는 캐시 표시가 붙은 블록
        if calls[-1] in fail_on:
            raise llm.CreditExhausted()
        yield "delta", "*끄덕* 응."
        yield "done", {"usage": Usage(1, 0, 0, 1, 0.1), "trace_id": "t"}
    monkeypatch.setattr(llm, "stream_chat", f)
    return calls


def write_rows(p, meta, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ([{"meta": meta}] if meta is not None else []) + rows
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8")


def test_existing_file_refused(monkeypatch, tmp_path):
    count_stream(monkeypatch), ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO)
    p = run.run("v1", "haiku")
    before = p.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="--resume"):
        run.run("v1", "haiku")
    assert p.read_text(encoding="utf-8") == before


def test_resume_skips_done_reruns_errors(monkeypatch, tmp_path):
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO)
    p = tmp_path / "res" / "v1-haiku.jsonl"
    write_rows(p, run.run_meta("haiku", TWO, None),
               [{"id": "d", "judge": {"ok": True}}, {"id": "e", "judge": {"error": "x"}}])
    calls = count_stream(monkeypatch)
    run.run("v1", "haiku", resume=True)
    rows = read(p)
    assert calls == ["b"]  # 성공한 d는 다시 생성 안 함
    assert sorted(r["id"] for r in rows) == ["d", "e"] and [r for r in rows if r["id"] == "e"][0]["judge"] == {"ok": True}


def test_resume_meta_mismatch_refused(monkeypatch, tmp_path):
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO), count_stream(monkeypatch)
    p = tmp_path / "res" / "v1-haiku.jsonl"
    m = run.run_meta("haiku", TWO, None)
    m["prompts"]["character"] = "다른값"
    write_rows(p, m, [])
    with pytest.raises(SystemExit, match="prompts.character"):
        run.run("v1", "haiku", resume=True)


def test_resume_ignores_time_commit(monkeypatch, tmp_path):
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO)
    p = tmp_path / "res" / "v1-haiku.jsonl"
    m = run.run_meta("haiku", TWO, None) | {"time": "2000-01-01T00:00:00", "commit": "0000000"}
    write_rows(p, m, [{"id": "d", "judge": {"ok": True}}])
    calls = count_stream(monkeypatch)
    run.run("v1", "haiku", resume=True)
    assert calls == ["b"] and len(read(p)) == 2


def test_resume_old_file_refused(monkeypatch, tmp_path):
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO), count_stream(monkeypatch)
    write_rows(tmp_path / "res" / "v1-haiku.jsonl", None, [{"id": "d", "judge": {"ok": True}}])
    with pytest.raises(SystemExit, match="실행 정보"):
        run.run("v1", "haiku", resume=True)


def test_credit_keeps_written_rows(monkeypatch, tmp_path):
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO)
    count_stream(monkeypatch, fail_on=("b",))
    with pytest.raises(llm.CreditExhausted):
        run.run("v1", "haiku")
    p = tmp_path / "res" / "v1-haiku.jsonl"
    assert meta_of(p)["scenarios"]["count"] == 2 and [r["id"] for r in read(p)] == ["d"]


def test_resume_twice_no_duplicates(monkeypatch, tmp_path):
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO), count_stream(monkeypatch)
    p = run.run("v1", "haiku")
    run.run("v1", "haiku", resume=True), run.run("v1", "haiku", resume=True)
    assert sorted(r["id"] for r in read(p)) == ["d", "e"]


def test_resume_ignores_dirty(monkeypatch, tmp_path):
    # 커밋만 해도 dirty가 바뀜. 내용 변경은 해시가 잡음
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO)
    p = tmp_path / "res" / "v1-haiku.jsonl"
    m = run.run_meta("haiku", TWO, None)
    write_rows(p, m | {"dirty": not m["dirty"]}, [{"id": "d", "judge": {"ok": True}}])
    calls = count_stream(monkeypatch)
    run.run("v1", "haiku", resume=True)
    assert calls == ["b"]


def test_meta_tracks_judge_items_and_assembly():
    m = run.run_meta("haiku", [], None)
    assert len(m["judge"]["code"]) == 8 and len(m["gen"]["assembly"]) == 8  # CATEGORY_ITEMS, build_messages


def test_credit_keeps_rows_already_running(monkeypatch, tmp_path):
    # 크레딧 소진 때 이미 돌던 시나리오도 끝나면 씀(크레딧 쓴 결과 버리지 않음)
    import time as t
    ok_judge(monkeypatch)
    scen(monkeypatch, tmp_path, TWO + [{"id": "f", "category": "daily", "turns": ["c"], "note": ""}])

    def f(messages, model, max_tokens=None, **k):
        c = messages[-1]["content"]
        text = c if isinstance(c, str) else c[0]["text"]
        if text == "b":
            t.sleep(0.05)
            raise llm.CreditExhausted()
        if text == "c":
            t.sleep(0.3)
        yield "delta", "*끄덕* 응."
        yield "done", {"usage": Usage(1, 0, 0, 1, 0.1), "trace_id": "t"}
    monkeypatch.setattr(llm, "stream_chat", f)
    with pytest.raises(llm.CreditExhausted):
        run.run("v1", "haiku")
    assert sorted(r["id"] for r in read(tmp_path / "res" / "v1-haiku.jsonl")) == ["d", "f"]


def test_rejudge_skips_gen_error_rows(monkeypatch, tmp_path):
    scen(monkeypatch, tmp_path, [{"id": "d", "category": "daily", "turns": ["a", "b"], "note": ""}])
    monkeypatch.setattr(judge, "checklist", lambda *a, **k: pytest.fail("생성 오류 줄은 채점 안 함"))
    p = tmp_path / "r.jsonl"
    row = {"id": "d", "turns": ["a"], "responses": ["x"], "judge": {"error": "StreamError: x"}, "error": "StreamError: x"}
    write_rows(p, {}, [row])
    (r,) = read(run.rejudge(p))
    assert r["judge"] == {"error": "StreamError: x"}


def test_eval_tags_ci_manual(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert run.eval_tags("v1") == ("eval", "v1", "manual")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert run.eval_tags("v1") == ("eval", "v1", "ci")


def test_tags_inside_threads(monkeypatch, tmp_path):
    # 평가는 스레드 병렬. 각 호출 태그에 eval·라벨·단계가 붙어야 함
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    seen = []

    def f(messages, model, max_tokens=None, tags=()):
        seen.append(llm.current_tags() + tuple(tags))
        yield "delta", "*끄덕* 응."
        yield "done", {"usage": Usage(1, 0, 0, 1, 0.1), "trace_id": "t"}
    monkeypatch.setattr(llm, "stream_chat", f)
    ok_judge(monkeypatch), scen(monkeypatch, tmp_path, TWO + [{"id": "f", "category": "daily", "turns": ["c"], "note": ""}])
    run.run("v1", "haiku")
    assert len(seen) == 3 and all(t == ("eval", "v1", "manual", "eval:chat") for t in seen)


def test_judge_tag(prompts, monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "complete", lambda m, model, mt=None, tags=(): seen.append(tags) or (json.dumps({i: True for i in judge.ITEMS}), Usage(0, 0, 0, 0, 0)))
    judge.checklist(S, "a")
    assert seen == [("eval:judge",)]


def test_run_exclude_category(monkeypatch, tmp_path):
    ok_judge(monkeypatch), count_stream(monkeypatch)
    scen(monkeypatch, tmp_path, TWO + [{"id": "l", "category": "long", "length": 2, "note": ""}])
    p = run.run("v1", "haiku", exclude=["long"])
    assert sorted(r["id"] for r in read(p)) == ["d", "e"]
    m = meta_of(p)
    assert m["scenarios"]["exclude"] == ["long"] and m["scenarios"]["count"] == 2
    with pytest.raises(SystemExit, match="scenarios"):  # 다른 세트로 이어 돌리기 거부
        run.run("v1", "haiku", resume=True)


def test_agree_table_directions():
    from eval.agree import table
    h = {("g1", "canon_safe"): True, ("g2", "canon_safe"): False, ("g3", "canon_safe"): True}
    m = {("g1", "canon_safe"): False, ("g2", "canon_safe"): True, ("g3", "canon_safe"): True}
    assert "| canon_safe | 1/3 | 1 | 1 |" in table(h, m)


def test_rejudge_keeps_responses(monkeypatch, tmp_path):
    scen(monkeypatch, tmp_path, [{"id": "d", "category": "daily", "turns": ["a", "b"], "note": ""}])
    seen = []

    def j(s, resp, convo, with_reason, usage):
        usage["cost"] += 0.2
        return seen.append(convo) or {"ok": True}
    monkeypatch.setattr(judge, "checklist", j)
    p = tmp_path / "r.jsonl"
    orig = json.dumps({"id": "d", "turns": ["a", "b"], "responses": ["x", "y"], "judge": {"error": "old"}}) + "\n"
    p.write_text(orig)  # 옛 파일(실행 정보 없음)
    out = run.rejudge(p)
    assert p.read_text() == orig  # 원본 그대로
    assert out.name.startswith("r.rejudge-") and out.suffix == ".jsonl"
    (r,) = read(out)
    assert r["judge"] == {"ok": True} and r["responses"] == ["x", "y"] and r["usage_parts"]["judge"]["cost"] == 0.2
    assert seen == ["사용자: a\n하치와레: x\n사용자: b"]  # 마지막 응답 앞까지가 맥락
    m = meta_of(out)
    assert m["source"] == "r.jsonl" and m["judge"]["model"] == judge.JUDGE_MODEL


def test_rejudge_twice_same_day(monkeypatch, tmp_path):
    scen(monkeypatch, tmp_path, [{"id": "d", "category": "daily", "turns": ["a"], "note": ""}])
    ok_judge(monkeypatch)
    p = tmp_path / "r.jsonl"
    write_rows(p, {"prompts": {"character": "c"}}, [{"id": "d", "turns": ["a"], "responses": ["x"], "judge": {}}])
    a, b = run.rejudge(p), run.rejudge(p)
    assert a != b and a.exists() and b.exists()
    assert meta_of(b)["prompts"] == {"character": "c"}  # 원본 실행 정보 이어받음


def test_messages_split_fixed_part():
    assert judge._messages("고정\n===\n변함") == [{"role": "system", "content": "고정"}, {"role": "user", "content": "변함"}]
    assert judge._messages("하나") == [{"role": "user", "content": "하나"}]
