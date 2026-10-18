"""결과 jsonl 여러 개 → 마크다운 표(행 = label x model)"""
import argparse
import json
from pathlib import Path


def _pct(v: list[bool]) -> str:
    return f"{sum(v) / len(v):.0%}" if v else "-"


def summarize(paths: list[Path], exclude_category: str | None = None) -> str:
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if exclude_category and r["id"].rsplit("-", 1)[0] == exclude_category:  # id = <카테고리>-NN
                continue
            groups.setdefault((r["label"], r["model"]), []).append(r)

    def keys(rows, get):
        return sorted({k for r in rows for k in get(r)})

    allrows = [r for rows in groups.values() for r in rows]
    ck = keys(allrows, lambda r: {k for c in r["checks"] for k in c})
    jk = keys(allrows, lambda r: {k for k, v in r["judge"].items() if isinstance(v, bool)})
    head = ["label", "model", "시나리오"] + [f"규칙:{k}" for k in ck] + [f"채점:{k}" for k in jk] + ["평균 비용", "평균 초"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for (label, model), rows in sorted(groups.items()):
        cells = [label, model, str(len(rows))]
        cells += [_pct([c[k] for r in rows for c in r["checks"] if k in c]) for k in ck]
        cells += [_pct([r["judge"][k] for r in rows if "error" not in r["judge"] and k in r["judge"]]) for k in jk]
        cells.append(f"${sum(r['usage']['cost'] for r in rows) / len(rows):.4f}")
        secs = [r["seconds"] for r in rows if "seconds" in r]
        cells.append(f"{sum(secs) / len(secs):.1f}" if secs else "-")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--exclude-category")
    a = ap.parse_args()
    print(summarize(a.paths, a.exclude_category))
