"""실험 실행: 시나리오별 응답 생성 + 규칙 검사 → eval/results/<label>-<별칭>.jsonl"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
import time
from dataclasses import asdict, fields
from pathlib import Path

import yaml

from app import llm
from app.config import MODELS, PROMPT_VERSION
from app.llm import Usage
from app.prompt import build_messages
from eval import judge
from eval.checks import check

ROOT = Path(__file__).parent
SCENARIOS = ROOT / "scenarios.yaml"
RESULTS = ROOT / "results"
NO_FORMAT = ("format", "length")  # safety: 위기 대응은 지문 없이 길게 말해도 됨


def _add(total: dict, u: Usage) -> None:
    for f in fields(Usage):
        total[f.name] += getattr(u, f.name)


def _reply(history: list[dict], model: str, total: dict) -> str:
    text = ""
    for kind, data in llm.stream_chat(build_messages(history), model):
        if kind == "delta":
            text += data
        else:
            _add(total, data["usage"])
    return text


def _sim(s: dict, history: list[dict], total: dict) -> str:
    p = judge.prompt("user_sim", note=s.get("note", ""), conversation=judge.format_conversation(history))
    out, u = llm.complete([{"role": "user", "content": p}], MODELS["haiku"])
    _add(total, u)
    return out.strip()


def run_one(s: dict, model: str) -> dict:
    total = {f.name: 0 for f in fields(Usage)}
    history, turns, responses, checks = [], [], [], []
    fixed = s.get("turns")
    seconds = 0.0
    for i in range(len(fixed) if fixed else s["length"]):
        user = fixed[i] if fixed else _sim(s, history, total)
        history.append({"role": "user", "content": user})
        t0 = time.perf_counter()
        resp = _reply(history, model, total)
        seconds += time.perf_counter() - t0  # 채팅 응답만(시뮬레이터·채점 제외)
        history.append({"role": "assistant", "content": resp})
        c = check(resp)
        if s["category"] == "safety":
            c = {k: v for k, v in c.items() if k not in NO_FORMAT}
        turns.append(user), responses.append(resp), checks.append(c)
    try:  # 채점은 마지막 응답 기준, 이전 대화는 맥락
        graded = judge.checklist(s, responses[-1], judge.format_conversation(history[:-1]), with_reason=True)
    except Exception as e:  # 채점 실패가 실행 전체를 멈추지 않게
        graded = {"error": f"{type(e).__name__}: {e}"}
    return {"id": s["id"], "turns": turns, "responses": responses, "checks": checks, "judge": graded, "usage": total, "seconds": seconds}


def run(label: str, model: str, scenario_ids: list[str] | None = None) -> Path:
    scenarios = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    if scenario_ids:
        scenarios = [s for s in scenarios if s["id"] in scenario_ids]
    print("실행 전 OpenRouter 잔액 확인(서비스와 같은 키라 소진되면 서비스도 멈춤)")
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{label}-{model}.jsonl"
    cost = 0.0
    with ThreadPoolExecutor(8) as ex, path.open("w", encoding="utf-8") as f:  # 시나리오별 병렬, 기록은 순서대로
        for s, row in zip(scenarios, ex.map(lambda s: run_one(s, MODELS[model]), scenarios)):
            row = {"id": row.pop("id"), "model": MODELS[model], "label": label,
                   "prompt_version": PROMPT_VERSION, **row}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            cost += row["usage"]["cost"]
            print(f"{s['id']} 비용 {row['usage']['cost']:.4f}")
    j = judge.USAGE
    print(f"총 비용 ${cost:.4f}(채점자 ${j['cost']:.4f}, 캐시 읽기 {j['cache_read_tokens']}/{j['input_tokens']}토큰) -> {path}")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", required=True, choices=[k for k in MODELS if not k.startswith("judge")])
    ap.add_argument("--only", help="시나리오 id 쉼표 구분")
    a = ap.parse_args()
    run(a.label, a.model, a.only.split(",") if a.only else None)
