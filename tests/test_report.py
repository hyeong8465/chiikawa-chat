import json

from eval.report import summarize


def write(p, rows, meta=None):
    lines = ([{"meta": meta}] if meta is not None else []) + rows
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8")
    return p


def row(id="daily-01", label="v2", judge=None, judge_cost=None, **extra):
    r = {"id": id, "label": label, "model": "m", "checks": [{"format": True}],
         "judge": judge or {"hachiware_like": True}, "usage": {"cost": 1.0}, "seconds": 1.0} | extra
    if judge_cost is not None:
        r["usage_parts"] = {"judge": {"cost": judge_cost}}
    return r


def cells(table, label):
    head = table.splitlines()[0].strip("|").split("|")
    line = next(l for l in table.splitlines() if l.startswith(f"| {label} "))
    return dict(zip([h.strip() for h in head], [c.strip() for c in line.strip("|").split("|")]))


def test_report_skips_meta(tmp_path):
    t = summarize([write(tmp_path / "a.jsonl", [row(judge_cost=0.5)], meta={"commit": "x"})])
    c = cells(t, "v2")
    assert c["시나리오"] == "1" and c["채점 비용"] == "$0.5000" and c["총 비용"] == "$1.5000"


def test_report_mixed_old_new(tmp_path):
    old = write(tmp_path / "old.jsonl", [row(label="v1")])
    new = write(tmp_path / "new.jsonl", [row(judge_cost=0.5)], meta={})
    t = summarize([old, new])
    assert cells(t, "v1")["채점 비용"] == "-" and cells(t, "v1")["총 비용"] == "$1.0000"
    assert cells(t, "v2")["채점 비용"] == "$0.5000"


def test_report_error_counts(tmp_path):
    rows = [row(judge_cost=0), row(id="daily-02", error="StreamError: x", judge={"error": "StreamError: x"}, judge_cost=0),
            row(id="daily-03", judge={"error": "ValueError: y"}, judge_cost=0)]
    c = cells(summarize([write(tmp_path / "a.jsonl", rows, meta={})]), "v2")
    assert c["생성 오류"] == "1" and c["채점 오류"] == "1"


def test_report_rejudge_separate_row(tmp_path):
    # 다시 채점한 파일은 원본과 같은 label이어도 따로 집계(두 번 세지 않음)
    a = write(tmp_path / "a.jsonl", [row()], meta={})
    b = write(tmp_path / "a.rejudge-1030.jsonl", [row()], meta={"source": "a.jsonl"})
    t = summarize([a, b])
    assert cells(t, "v2")["시나리오"] == "1" and cells(t, "v2 (다시 채점: a.rejudge-1030)")["시나리오"] == "1"


def test_report_rejudge_total_is_judge_only(tmp_path):
    b = write(tmp_path / "a.rejudge-1030.jsonl", [row(judge_cost=0.5)], meta={"source": "a.jsonl"})
    assert cells(summarize([b]), "v2 (다시 채점: a.rejudge-1030)")["총 비용"] == "$0.5000"


def test_report_old_rows_unknown(tmp_path):
    # 옛 형식 줄이 섞이면 채점 비용·오류 구분을 알 수 없음 → "-"
    old = row(judge={"error": "StreamError: x"})
    c = cells(summarize([write(tmp_path / "a.jsonl", [old, row(id="daily-02", judge_cost=0.5)])]), "v2")
    assert c["채점 비용"] == "-" and c["생성 오류"] == "-" and c["채점 오류"] == "-" and c["총 비용"] == "$2.0000"


from eval.report import compare


def sc(id, judge=None, checks=None, **extra):
    return {"id": id, "label": "x", "model": "m", "checks": checks or [{"format": True}],
            "judge": judge or {"hachiware_like": True}, "usage": {"cost": 0.1}, **extra}


def test_compare_flips(tmp_path):
    base = write(tmp_path / "b.jsonl", [sc("a", {"canon_safe": True}), sc("b", {"canon_safe": False})], meta={"commit": "c1"})
    pr = write(tmp_path / "p.jsonl", [sc("a", {"canon_safe": False, "reason": "랏코 2위"}), sc("b", {"canon_safe": True})],
               meta={"commit": "c2"})
    t = compare(base, pr)
    assert t.startswith("<!-- eval-report -->") and "머지 막지 않음" in t
    assert "나빠짐 1" in t and "나아짐 1" in t
    assert "| a | 채점:canon_safe | 랏코 2위 |" in t  # 나빠진 표에 채점자 이유
    assert "<details>" in t and "c1" in t and "c2" in t


def test_compare_uncomparable(tmp_path):
    base = write(tmp_path / "b.jsonl", [sc("a"), sc("b")], meta={})
    pr = write(tmp_path / "p.jsonl", [sc("a", {"error": "x"}), sc("c")], meta={})
    assert "비교 못 함 3" in compare(base, pr)  # a(PR 오류), b(PR에 없음), c(기준선에 없음)


def test_compare_stale_warning(tmp_path):
    base = write(tmp_path / "b.jsonl", [sc("a")], meta={"commit": "aaaaaaa"})
    pr = write(tmp_path / "p.jsonl", [sc("a")], meta={"commit": "bbbbbbb"})
    assert "최신이 아님" in compare(base, pr, main_commit="ccccccc1234")
    assert "최신이 아님" not in compare(base, pr, main_commit="aaaaaaa1234")


def test_compare_rule_all_turns(tmp_path):
    # 규칙은 시나리오 안 모든 턴 통과여야 통과
    base = write(tmp_path / "b.jsonl", [sc("a", checks=[{"length": True}, {"length": True}])], meta={})
    pr = write(tmp_path / "p.jsonl", [sc("a", checks=[{"length": True}, {"length": False}])], meta={})
    assert "| a | 규칙:length |  |" in compare(base, pr)
