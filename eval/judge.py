"""LLM 채점: 체크리스트(통과/실패)와 쌍대 비교. 프롬프트는 eval/prompts/."""
from pathlib import Path
from typing import Literal

from app import llm
from app.config import JUDGE_MODEL

PROMPTS_DIR = Path(__file__).parent / "prompts"

ITEMS = ["hachiware_like", "world_translation", "no_counselor", "canon_safe", "boundary_ok", "persona_kept", "safety_ok"]

_D = ["hachiware_like", "no_counselor", "canon_safe"]
CATEGORY_ITEMS = {
    "daily": _D,
    "comfort": _D + ["world_translation"],
    "attack": ["hachiware_like", "persona_kept"],
    "canon": ["hachiware_like", "canon_safe"],
    "boundary": ["hachiware_like", "canon_safe", "boundary_ok"],
    "safety": ["safety_ok", "persona_kept"],
    "long": ["hachiware_like", "no_counselor", "persona_kept"],
}


def fill(template: str, **values: str) -> str:
    # 프롬프트에 JSON 예시의 중괄호가 있어 str.format 대신 자리표시만 치환
    for k, v in values.items():
        template = template.replace("{" + k + "}", v)
    return template


def prompt(name: str, **values: str) -> str:
    return fill((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"), **values)


def format_conversation(history: list[dict]) -> str:
    who = {"user": "사용자", "assistant": "하치와레"}
    return "\n".join(f"{who[m['role']]}: {m['content']}" for m in history)


def _ask(text: str) -> dict:
    out, _ = llm.complete([{"role": "user", "content": text}], JUDGE_MODEL)
    res = llm.extract_json(out)
    if not isinstance(res, dict):
        raise ValueError("채점 결과가 객체가 아님")
    return res


def checklist(scenario: dict, response: str, conversation: str = "", with_reason: bool = False) -> dict:
    items = CATEGORY_ITEMS[scenario["category"]]
    res = _ask(prompt(
        "judge_checklist", category=scenario["category"], note=scenario.get("note", ""),
        conversation=conversation, response=response, items="\n".join(items),
    ))
    out = {i: bool(res[i]) for i in items}
    if with_reason:
        out["reason"] = str(res.get("reason", ""))
    return out


def _winner(scenario: dict, a: str, b: str, conversation: str) -> str:
    w = _ask(prompt("judge_pair", note=scenario.get("note", ""), conversation=conversation, a=a, b=b)).get("winner")
    return w if w in ("A", "B") else "tie"


def pair(scenario: dict, a: str, b: str, conversation: str = "") -> Literal["A", "B", "tie"]:
    first = _winner(scenario, a, b, conversation)
    second = {"A": "B", "B": "A", "tie": "tie"}[_winner(scenario, b, a, conversation)]  # 순서 바꿔 되돌림
    return first if first == second else "tie"


def agreement(human: dict[tuple[str, str], bool], machine: dict[tuple[str, str], bool]) -> dict[str, float]:
    hit: dict[str, list[bool]] = {}
    for k in human.keys() & machine.keys():
        hit.setdefault(k[1], []).append(human[k] == machine[k])
    return {i: sum(v) / len(v) for i, v in hit.items()}
