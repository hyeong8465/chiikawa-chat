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
