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


STEPS = (("chat", "생성", "gen"), ("sim", "사용자 흉내", "sim"), ("judge", "채점", "judge"))


def cache_table(meta: dict | None, rows: list[dict]) -> str:
    # 단계별 비용·캐시 적중률·캐시 없었을 때 비용. 단가는 실행 정보(prices)에서
    from eval.pricing import no_cache_cost
    meta = meta or {}
    prices = meta.get("prices") or {}
    rows = [r for r in rows if "usage_parts" in r]
    keys = ("cost", "input_tokens", "cache_read_tokens", "cache_write_tokens")
    lines = ["| 단계 | 비용 | 입력 토큰 | 캐시 읽기 | 캐시 쓰기 | 적중률 | 캐시 없었으면 | 절감률 |", "|---|---|---|---|---|---|---|---|"]
    total = {k: 0 for k in keys}
    total_nc: float | None = 0.0
    for part, name, mkey in STEPS:
        u = {k: sum(r["usage_parts"].get(part, {}).get(k, 0) for r in rows) for k in keys}
        if not u["input_tokens"] and not u["cost"]:
            continue  # 안 쓴 단계(긴 대화 없으면 사용자 흉내)
        nc = no_cache_cost(u, prices.get((meta.get(mkey) or {}).get("model")))
        total = {k: total[k] + u[k] for k in keys}
        total_nc = None if nc is None or total_nc is None else total_nc + nc
        lines.append(_cache_row(name, u, nc))
    lines.append(_cache_row("합계", total, total_nc))
    return "\n".join(lines)


def _cache_row(name: str, u: dict, nc: float | None) -> str:
    hit = f"{u['cache_read_tokens'] / u['input_tokens']:.0%}" if u["input_tokens"] else "-"
    save = f"{1 - u['cost'] / nc:.0%}" if nc else "-"
    return (f"| {name} | ${u['cost']:.4f} | {u['input_tokens']:,} | {u['cache_read_tokens']:,} | "
            f"{u['cache_write_tokens']:,} | {hit} | {f'${nc:.4f}' if nc is not None else '-'} | {save} |")


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


MARK = "<!-- eval-report -->"  # PR 댓글을 찾아 고쳐 쓸 때


def outcomes(row: dict) -> dict[str, bool] | None:
    # 시나리오 하나의 항목별 통과. 오류면 None(비교 못 함). 규칙은 모든 턴 통과여야 통과
    if "error" in row or "error" in row.get("judge", {}):
        return None
    out = {f"채점:{k}": v for k, v in row["judge"].items() if isinstance(v, bool)}
    for k in {k for c in row.get("checks", []) for k in c}:
        out[f"규칙:{k}"] = all(c[k] for c in row["checks"] if k in c)
    return out


def _flat(d: dict, pre: str = "") -> dict:
    out = {}
    for k, v in d.items():
        out |= _flat(v, f"{pre}{k}.") if isinstance(v, dict) else {pre + k: v}
    return out


def compare(base: Path, pr: Path, main_commit: str | None = None) -> str:
    # 기준선 vs PR 결과 → PR 댓글 마크다운. 나빠진 것 먼저, 나머지는 접음
    bm, brows = load(base)
    pm, prows = load(pr)
    bm, pm = bm or {}, pm or {}
    b = {r["id"]: (outcomes(r), r) for r in brows}
    p = {r["id"]: (outcomes(r), r) for r in prows}
    ids = sorted(b.keys() & p.keys())
    ok = [i for i in ids if b[i][0] is not None and p[i][0] is not None]
    skipped = len(b.keys() | p.keys()) - len(ok)
    worse, better, count = [], [], {}
    for i in ok:
        bo, po = b[i][0], p[i][0]
        for k in sorted(bo.keys() & po.keys()):
            c = count.setdefault(k, [0, 0, 0])
            c[0] += bo[k]
            c[1] += po[k]
            c[2] += 1
            if bo[k] and not po[k]:
                worse.append((i, k, p[i][1]["judge"].get("reason", "") if k.startswith("채점:") else ""))
            elif po[k] and not bo[k]:
                better.append((i, k))

    def total(prefix: str, at: int) -> str:
        cs = [c for k, c in count.items() if k.startswith(prefix)]
        return f"{sum(c[at] for c in cs)}/{sum(c[2] for c in cs)}"

    out = [MARK, "### 🧪 평가 결과 (참고용, 머지 막지 않음)", ""]
    if main_commit and bm.get("commit") and not main_commit.startswith(bm["commit"]):
        out += [f"> ⚠ 기준선이 main 최신이 아님(기준선 `{bm['commit']}`, main `{main_commit[:7]}`). 다시 돌리면 정확해짐", ""]
    out.append(f"**채점** {total('채점:', 0)} → {total('채점:', 1)} · **규칙** {total('규칙:', 0)} → {total('규칙:', 1)}"
               f" · 나빠짐 {len(worse)} · 나아짐 {len(better)}" + (f" · 비교 못 함 {skipped}" if skipped else ""))
    if worse:
        out += ["", "| 나빠진 시나리오 | 항목 | 채점자 이유 |", "|---|---|---|"]
        out += [f"| {i} | {k} | {why} |" for i, k, why in worse]
    rates = ["| 항목 | 기준선 | 이 PR | 차이 |", "|---|---|---|---|"]
    rates += [f"| {k} | {c[0]}/{c[2]} | {c[1]}/{c[2]} | {c[1] - c[0]:+d} |" for k, c in sorted(count.items())]
    diff = sorted(k for k in _flat(bm).keys() | _flat(pm).keys()
                  if k.split(".")[0] not in ("time", "prices", "source") and _flat(bm).get(k) != _flat(pm).get(k))
    info = [f"- 평가 커밋 `{pm.get('commit', '-')}`, 기준선 커밋 `{bm.get('commit', '-')}`",
            f"- 기준선 다시 채점: {'함(' + bm['source'] + ')' if 'source' in bm else '안 함'}",
            f"- 기준선과 다른 칸: {', '.join(diff) or '없음'}"]
    out += ["", "<details><summary>항목별 통과율</summary>", "", *rates, "", "</details>",
            "<details><summary>나아진 시나리오</summary>", "", *([f"- {i} {k}" for i, k in better] or ["- 없음"]), "", "</details>",
            "<details><summary>단계별 비용·캐시</summary>", "", cache_table(pm, prows), "", "</details>",
            "<details><summary>실행 정보</summary>", "", *info, "", "</details>"]
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--exclude-category")
    ap.add_argument("--cache", action="store_true", help="파일별 단계 비용·캐시 적중률·절감")
    ap.add_argument("--compare", action="store_true", help="paths = 기준선 PR결과 → 비교 마크다운")
    a = ap.parse_args()
    if a.compare:
        print(compare(*a.paths))
    elif a.cache:
        for p in a.paths:
            print(f"## {p.name}\n\n{cache_table(*load(p))}\n")
    else:
        print(summarize(a.paths, a.exclude_category))
