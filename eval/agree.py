"""골든셋 채점자–사람 일치율: 골든셋 40개를 채점자로 채점 → eval/results/golden-<별칭>.jsonl
실행: uv run --env-file .env python -m eval.agree --model judge (judge_strong). 크레딧 사용"""
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from app.config import MODELS
from eval import judge

GOLDEN = Path(__file__).parent / "golden"
RESULTS = Path(__file__).parent / "results"
WORKERS = 8  # 동시 호출 수


def human_labels(path: Path) -> dict[tuple[str, str], bool]:
    with path.open(encoding="utf-8", newline="") as f:
        return {(r["id"], r["item"]): r["pass"] == "1" for r in csv.DictReader(f) if r["pass"]}


def table(human: dict, machine: dict) -> str:
    # 항목별 일치율 + 어긋난 방향(사람 통과·채점자 실패 / 사람 실패·채점자 통과)
    rows = ["| 항목 | 일치 | 사람O·채점자X | 사람X·채점자O |", "|---|---|---|---|"]
    for item in judge.ITEMS:
        keys = [k for k in human.keys() & machine.keys() if k[1] == item]
        if keys:
            hit = sum(human[k] == machine[k] for k in keys)
            strict = sum(human[k] and not machine[k] for k in keys)
            loose = sum(machine[k] and not human[k] for k in keys)
            rows.append(f"| {item} | {hit}/{len(keys)} | {strict} | {loose} |")
    return "\n".join(rows)


def main(alias: str) -> None:
    golden = yaml.safe_load((GOLDEN / "responses.yaml").read_text(encoding="utf-8"))
    path = RESULTS / f"golden-{alias}.jsonl"

    def one(g: dict) -> dict:
        try:
            return judge.checklist(g, g["response"], g.get("conversation", ""), with_reason=True, model=MODELS[alias])
        except Exception as e:  # 한 개 실패가 전체를 멈추지 않게
            return {"error": f"{type(e).__name__}: {e}"}

    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(one, golden))
    machine = {}
    with path.open("w", encoding="utf-8") as f:
        for g, res in zip(golden, results):
            f.write(json.dumps({"id": g["id"], "judge": res}, ensure_ascii=False) + "\n")
            machine |= {(g["id"], i): v for i, v in res.items() if i in g["items"]}
            if "error" in res:
                print(g["id"], "오류", res["error"])
    u = judge.USAGE
    print(table(human_labels(GOLDEN / "labels.csv"), machine))
    print(f"채점자 {MODELS[alias]} 비용 ${u['cost']:.4f}, 캐시 읽기 {u['cache_read_tokens']}/{u['input_tokens']}토큰 -> {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=[k for k in MODELS if k.startswith("judge")])
    main(ap.parse_args().model)
