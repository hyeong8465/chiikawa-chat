"""결과 jsonl 여러 개 → 마크다운 표(행 = label x model)"""
import argparse
import json
from pathlib import Path


def _pct(v: list[bool]) -> str:
    return f"{sum(v) / len(v):.0%}" if v else "-"


def load(path: Path) -> tuple[dict | None, list[dict]]:
    # 결과 파일 → (실행 정보, 시나리오 줄). 옛 파일은 실행 정보 없음. eval.run도 이걸 씀
    meta, rows = None, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if "meta" in r:
                meta = r["meta"]
            else:
                rows.append(r)
    return meta, rows


def summarize(paths: list[Path], exclude_category: str | None = None) -> str:
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in paths:
        meta, rows = load(p)
        tag = f" (다시 채점: {Path(p).stem})" if "source" in (meta or {}) else ""  # 원본과 따로 집계
        for r in rows:
            if exclude_category and r["id"].rsplit("-", 1)[0] == exclude_category:  # id = <카테고리>-NN
                continue
            groups.setdefault((r["label"] + tag, r["model"]), []).append(r)

    def keys(rows, get):
        return sorted({k for r in rows for k in get(r)})

    allrows = [r for rows in groups.values() for r in rows]
    ck = keys(allrows, lambda r: {k for c in r["checks"] for k in c})
    jk = keys(allrows, lambda r: {k for k, v in r["judge"].items() if isinstance(v, bool)})
    head = ["label", "model", "시나리오"] + [f"규칙:{k}" for k in ck] + [f"채점:{k}" for k in jk] + ["평균 비용", "평균 초", "생성 오류", "채점 오류", "채점 비용", "총 비용"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for (label, model), rows in sorted(groups.items()):
        cells = [label, model, str(len(rows))]
        cells += [_pct([c[k] for r in rows for c in r["checks"] if k in c]) for k in ck]
        cells += [_pct([r["judge"][k] for r in rows if "error" not in r["judge"] and k in r["judge"]]) for k in jk]
        cells.append(f"${sum(r['usage']['cost'] for r in rows) / len(rows):.4f}")
        secs = [r["seconds"] for r in rows if "seconds" in r]
        cells.append(f"{sum(secs) / len(secs):.1f}" if secs else "-")
        # 옛 형식 줄(usage_parts 없음)이 섞이면 생성·채점 오류 구분과 채점 비용을 알 수 없음 → "-"
        new = all("usage_parts" in r for r in rows)
        cells.append(str(sum("error" in r for r in rows)) if new else "-")
        cells.append(str(sum("error" not in r and "error" in r["judge"] for r in rows)) if new else "-")
        jc = sum(r["usage_parts"]["judge"]["cost"] for r in rows) if new else 0.0
        cells.append(f"${jc:.4f}" if new else "-")
        gen = 0.0 if "다시 채점" in label else sum(r["usage"]["cost"] for r in rows)  # 다시 채점은 채점만 씀
        cells.append(f"${gen + jc:.4f}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--exclude-category")
    a = ap.parse_args()
    print(summarize(a.paths, a.exclude_category))
