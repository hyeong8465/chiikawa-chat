"""CI 흐름(GitHub Actions에서 부름): PR 결과 + 기준선 → 댓글 본문. 워크플로 YAML은 얇게 두고 판단은 여기서"""
import argparse
from pathlib import Path

from eval import run
from eval.report import MARK, cache_table, compare, load, summarize


def judge_changed(base_meta: dict | None, pr_meta: dict) -> bool:
    # 채점자(모델·프롬프트·참고 자료·채점 항목)가 다르면 같은 자로 다시 채점해야 비교가 맞음
    return (base_meta or {}).get("judge") != pr_meta.get("judge")


def pr_body(base: Path | None, pr: Path, main_commit: str | None) -> str:
    if base is None or not base.exists():
        pm, rows = load(pr)
        return "\n".join([MARK, "### 🧪 평가 결과 (참고용, 머지 막지 않음)", "", "> 기준선 없음: 비교 없이 이 PR 결과만",
                          "", summarize([pr]), "", "<details><summary>단계별 비용·캐시</summary>", "",
                          cache_table(pm, rows), "", "</details>"])
    if judge_changed(load(base)[0], load(pr)[0]):
        base = run.rejudge(base)  # 기준선 답은 그대로, 채점만 PR 채점자로
    return compare(base, pr, main_commit)


def failure_body(msg: str) -> str:
    return "\n".join([MARK, "### 🧪 평가 실패 (머지 막지 않음)", "", f"```\n{msg}\n```",
                      "", "크레딧 잔액·Secrets 확인 후 Actions에서 다시 실행"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pr")
    p.add_argument("--baseline", type=Path)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--main-commit")
    p.add_argument("--out", type=Path, required=True)
    f = sub.add_parser("fail")
    f.add_argument("--msg", required=True)
    f.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    body = pr_body(a.baseline, a.result, a.main_commit) if a.cmd == "pr" else failure_body(a.msg)
    a.out.write_text(body, encoding="utf-8")
