"""캐싱 비용 검증: 같은 10턴 발화를 3조건(none/system/full)으로 재생 → eval/results/cost.json"""
import argparse
import json
from pathlib import Path

from app import llm
from app.config import CHAT_MODEL
from app.prompt import build_messages

RESULTS = Path(__file__).parent / "results"
CONDITIONS = ("none", "system", "full")
USER_TURNS = [
    "안녕! 오늘 뭐 했어?",
    "나는 아침에 늦잠 잤어",
    "점심은 뭐 먹을까 고민 중이야",
    "너는 좋아하는 음식 뭐야?",
    "요즘 날씨가 꽤 쌀쌀하다",
    "주말에 뭐 하고 싶어?",
    "사진 찍는 거 재밌어?",
    "오늘 본 것 중에 제일 예뻤던 거 있어?",
    "슬슬 졸리다",
    "오늘 얘기해서 즐거웠어, 잘 자!",
]


def savings(costs: dict[str, float]) -> dict[str, float]:
    return {k: 1 - costs[k] / costs["none"] for k in ("system", "full")}


def _replay(cache: str, turns: list[str], model: str) -> list[dict]:
    history, rows = [], []
    for user in turns:
        history.append({"role": "user", "content": user})
        text, usage = "", None
        for kind, data in llm.stream_chat(build_messages(history, cache=cache), model):
            if kind == "delta":
                text += data
            else:
                usage = data["usage"]
        history.append({"role": "assistant", "content": text})
        rows.append({"input": usage.input_tokens, "cache_read": usage.cache_read_tokens,
                     "cache_write": usage.cache_write_tokens, "cost": usage.cost})
    return rows


def run(n: int = 10, model: str = CHAT_MODEL) -> dict:
    turns = {c: _replay(c, USER_TURNS[:n], model) for c in CONDITIONS}
    totals = {c: {k: sum(r[k] for r in rows) for k in ("input", "cache_read", "cache_write", "cost")}
              for c, rows in turns.items()}
    out = {
        "model": model,
        "totals": totals,
        "turns": turns,
        "savings": savings({c: totals[c]["cost"] for c in CONDITIONS}),
        "ok": all(r["cache_read"] > 0 for r in turns["full"][1:]),  # 2턴째부터 캐시 읽기
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "cost.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in CONDITIONS:
        t = totals[c]
        print(f"{c}: ${t['cost']:.4f} 캐시읽기 {t['cache_read']}")
    print(f"절감률 {out['savings']} ok={out['ok']}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=10, choices=range(1, len(USER_TURNS) + 1))
    run(ap.parse_args().turns)
