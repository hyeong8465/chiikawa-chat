"""실험 실행: 시나리오별 응답 생성 + 규칙 검사 → eval/results/<label>-<별칭>.jsonl"""
import argparse
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from itertools import chain
import time
from dataclasses import asdict, fields
from pathlib import Path

import openai
import yaml

from app import llm
from app.config import CHARACTER_DIR, MAX_TOKENS_CHAT, MODELS, PROMPT_VERSION, PROVIDER, REASONING, ROOT as REPO
from app.llm import Usage
from app.prompt import build_messages
from eval import judge, pricing
from eval.checks import check
from eval.report import _flat, load

ROOT = Path(__file__).parent
SCENARIOS = ROOT / "scenarios.yaml"
RESULTS = ROOT / "results"
NO_FORMAT = ("format", "length")  # safety: 위기 대응은 지문 없이 길게 말해도 됨
SIM_MODEL = MODELS["haiku"]
CHAR_FILES = ("platform.md", "character.md", "chat_guide.md", "examples.md", "intro.md", "episodes.yaml")
META_IGNORE = ("time", "commit", "dirty", "prices")  # 이어 돌릴 때 비교에서 뺌(커밋만 해도 바뀜. 내용 변경은 해시가 잡음)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _file_hash(p: Path) -> str:
    return _hash(p.read_text(encoding="utf-8"))


def _dirty() -> bool | None:
    # 추적 중인 파일에 커밋 안 한 변경이 있나. git 없으면 None
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                             cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception:
        return None
    return bool(out.strip())


def judge_meta() -> dict:
    # code: 범주별 채점 항목(CATEGORY_ITEMS)이 judge.py에 있음
    return {"model": judge.JUDGE_MODEL, "prompt": _file_hash(judge.PROMPTS_DIR / "judge_checklist.md"),
            "reference": _hash(judge.reference()), "code": _file_hash(Path(judge.__file__))}


def run_meta(model: str, scenarios: list[dict], only: list[str] | None, exclude: list[str] | None = None) -> dict:
    # 결과 파일 첫 줄: 이 실행을 다시 만들거나 다른 실행과 비교하는 데 필요한 것. 해시는 파일 내용 기준
    return {
        "prompts": {f.split(".")[0]: _file_hash(CHARACTER_DIR / f) for f in CHAR_FILES},
        "judge": judge_meta(),
        "sim": {"model": SIM_MODEL, "prompt": _file_hash(judge.PROMPTS_DIR / "user_sim.md")},
        "scenarios": {"hash": _file_hash(SCENARIOS), "only": sorted(only or []),
                      "exclude": sorted(exclude or []), "count": len(scenarios)},
        "checks": _file_hash(ROOT / "checks.py"),
        "gen": {"model": MODELS[model], "max_tokens": MAX_TOKENS_CHAT, "reasoning": REASONING, "provider": PROVIDER,
                "assembly": _file_hash(REPO / "app" / "prompt.py")},  # 시스템 프롬프트 조립(build_messages)
        "commit": PROMPT_VERSION,
        "dirty": _dirty(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "prices": pricing.fetch([MODELS[model], SIM_MODEL, judge.JUDGE_MODEL]),  # 절감 계산용(단가 바뀌어도 재현)
    }


def eval_tags(label: str) -> tuple[str, ...]:
    # Langfuse에서 운영 기록과 가르기. GitHub Actions면 ci, 손으로 돌리면 manual
    return ("eval", label, "ci" if os.getenv("GITHUB_ACTIONS") else "manual")


def _zero() -> dict:
    return {f.name: 0 for f in fields(Usage)}


def _add(total: dict, u: Usage) -> None:
    for f in fields(Usage):
        total[f.name] += getattr(u, f.name)


def _reply(history: list[dict], model: str, total: dict) -> str:
    text = ""
    for kind, data in llm.stream_chat(build_messages(history), model, tags=("eval:chat",)):
        if kind == "delta":
            text += data
        else:
            _add(total, data["usage"])
    return text


def _sim(s: dict, history: list[dict], total: dict) -> str:
    p = judge.prompt("user_sim", note=s.get("note", ""), conversation=judge.format_conversation(history))
    out, u = llm.complete([{"role": "user", "content": p}], SIM_MODEL, tags=("eval:sim",))
    _add(total, u)
    return out.strip()


def run_one(s: dict, model: str) -> dict:
    parts = {"chat": _zero(), "sim": _zero(), "judge": _zero()}
    history, turns, responses, checks = [], [], [], []
    fixed = s.get("turns")
    seconds = 0.0
    error = None
    for i in range(len(fixed) if fixed else s["length"]):
        try:
            user = fixed[i] if fixed else _sim(s, history, parts["sim"])
            history.append({"role": "user", "content": user})
            t0 = time.perf_counter()
            resp = _reply(history, model, parts["chat"])
        except (llm.StreamError, openai.APIError) as e:
            # 잘림·빈 답·시간 초과·5xx 연속: 이 시나리오만 멈춤(전체가 죽으면 결과 파일이 비고 크레딧만 씀). 크레딧 소진은 전체 중단
            error = f"{type(e).__name__}: {e}"
            break
        seconds += time.perf_counter() - t0  # 채팅 응답만(시뮬레이터·채점 제외)
        history.append({"role": "assistant", "content": resp})
        c = check(resp)
        if s["category"] == "safety":
            c = {k: v for k, v in c.items() if k not in NO_FORMAT}
        turns.append(user), responses.append(resp), checks.append(c)
    if error:
        graded = {"error": error}
    else:
        try:  # 채점은 마지막 응답 기준, 이전 대화는 맥락
            graded = judge.checklist(s, responses[-1], judge.format_conversation(history[:-1]), with_reason=True,
                                     usage=parts["judge"])
        except Exception as e:  # 채점 실패가 실행 전체를 멈추지 않게
            graded = {"error": f"{type(e).__name__}: {e}"}
    total = {k: parts["chat"][k] + parts["sim"][k] for k in parts["chat"]}  # usage는 예전 뜻 그대로(채점 제외)
    row = {"id": s["id"], "turns": turns, "responses": responses, "checks": checks, "judge": graded,
           "usage": total, "usage_parts": parts, "seconds": seconds}
    if error:
        row["error"] = error  # 생성 오류(채점 오류와 구분)
    return row


def _diff(a: dict, b: dict) -> list[str]:
    fa, fb = _flat({k: v for k, v in a.items() if k not in META_IGNORE}), _flat({k: v for k, v in b.items() if k not in META_IGNORE})
    return sorted(k for k in fa.keys() | fb.keys() if fa.get(k) != fb.get(k))


def _ok(row: dict) -> bool:
    return "error" not in row and "error" not in row.get("judge", {})


def _write(f, row: dict) -> None:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    f.flush()


def run(label: str, model: str, scenario_ids: list[str] | None = None, resume: bool = False,
        exclude: list[str] | None = None) -> Path:
    scenarios = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    if scenario_ids:
        scenarios = [s for s in scenarios if s["id"] in scenario_ids]
    if exclude:  # 범주 빼기(CI: 긴 대화는 R1 고정 대화 전까지 뺌)
        scenarios = [s for s in scenarios if s["category"] not in exclude]
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{label}-{model}.jsonl"
    meta = run_meta(model, scenarios, scenario_ids, exclude)
    done: list[dict] = []
    if resume and path.exists():
        old, rows = load(path)
        if old is None:
            raise SystemExit(f"{path.name}: 실행 정보 줄이 없는 옛 파일이라 이어 돌릴 수 없음. 새 라벨로 실행")
        if diff := _diff(old, meta):
            raise SystemExit(f"{path.name}: 실행 정보가 달라 이어 돌릴 수 없음(섞임 방지): {', '.join(diff)}")
        meta, done = old, [r for r in rows if _ok(r)]  # 오류 줄은 버리고 다시 돌림
    elif path.exists():
        raise SystemExit(f"{path.name} 이미 있음(덮어쓰지 않음). 새 라벨을 쓰거나 --resume")
    skip = {r["id"] for r in done}
    todo = [s for s in scenarios if s["id"] not in skip]
    print("실행 전 OpenRouter 잔액 확인(서비스와 같은 키라 소진되면 서비스도 멈춤)")
    if skip:
        print(f"이어 돌리기: 끝난 {len(skip)}개 건너뜀, {len(todo)}개 실행")
    cost = 0.0

    def one(s: dict) -> dict:
        with llm.tagging(*eval_tags(label)):  # 스레드마다 따로
            row = run_one(s, MODELS[model])
        return {"id": row.pop("id"), "model": MODELS[model], "label": label, "prompt_version": PROMPT_VERSION, **row}

    # 끝난 시나리오부터 바로 한 줄씩(중간에 멈춰도 끝난 건 남음). 줄 순서 = 끝난 순서
    with path.open("w", encoding="utf-8") as f, ThreadPoolExecutor(8) as ex:
        for r in [{"meta": meta}, *done]:
            _write(f, r)
        if todo:
            first = one(todo[0])  # 채팅·채점 캐시를 먼저 만든 뒤 병렬
            futures = [ex.submit(one, s) for s in todo[1:]]
            try:
                for row in chain([first], (fu.result() for fu in as_completed(futures))):
                    _write(f, row)
                    cost += row["usage"]["cost"] + row["usage_parts"]["judge"]["cost"]
                    print(f"{row['id']} 비용 {row['usage']['cost']:.4f}")
            except BaseException:  # 크레딧 소진 등: 안 시작한 건 취소, 이미 돌던 건 끝나는 대로 씀(크레딧 쓴 결과)
                for fu in futures:
                    fu.cancel()
                for fu in as_completed(fu for fu in futures if not fu.cancelled()):
                    if not fu.exception():
                        _write(f, fu.result())
                raise
    j = judge.USAGE
    print(f"총 비용 ${cost:.4f}(채점자 ${j['cost']:.4f}, 캐시 읽기 {j['cache_read_tokens']}/{j['input_tokens']}토큰) -> {path}")
    return path


def _rejudge_path(path: Path) -> Path:
    base = f"{path.stem}.rejudge-{datetime.now():%m%d}"
    out, n = path.with_name(base + ".jsonl"), 2
    while out.exists():  # 같은 날 두 번이면 -2, -3
        out, n = path.with_name(f"{base}-{n}.jsonl"), n + 1
    return out


def rejudge(path: Path) -> Path:
    # 응답은 그대로, 채점만 다시(채점 기준·채점자를 바꾼 뒤). 원본은 두고 새 파일
    scen = {s["id"]: s for s in yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))}
    meta, rows = load(path)
    meta = (meta or {}) | {"judge": judge_meta(), "time": datetime.now().isoformat(timespec="seconds"),
                           "source": path.name}

    def one(r: dict) -> dict:
        with llm.tagging(*eval_tags(r.get("label", path.stem))):
            return _one(r)

    def _one(r: dict) -> dict:
        if "error" in r:  # 생성 오류로 끊긴 대화는 채점 안 함(run_one과 같게)
            return r
        history = []
        for u, a in zip(r["turns"], r["responses"]):
            history += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
        u = _zero()
        try:
            j = judge.checklist(scen[r["id"]], r["responses"][-1], judge.format_conversation(history[:-1]),
                                with_reason=True, usage=u)
        except Exception as e:
            j = {"error": f"{type(e).__name__}: {e}"}
        return r | {"judge": j, "usage_parts": r.get("usage_parts", {}) | {"judge": u}}

    first = one(rows[0])  # 캐시 먼저
    with ThreadPoolExecutor(8) as ex:
        rows = [first, *ex.map(one, rows[1:])]
    out = _rejudge_path(path)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [{"meta": meta}, *rows]), encoding="utf-8")
    u = judge.USAGE
    print(f"채점 오류 {sum('error' in r['judge'] for r in rows)}/{len(rows)}, 채점자 ${u['cost']:.4f}, 캐시 읽기 {u['cache_read_tokens']}/{u['input_tokens']}토큰 -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--model", choices=[k for k in MODELS if not k.startswith("judge")])
    ap.add_argument("--only", help="시나리오 id 쉼표 구분")
    ap.add_argument("--exclude-category", help="뺄 범주 쉼표 구분(예: long)")
    ap.add_argument("--resume", action="store_true", help="같은 실행 정보면 끝난 시나리오 건너뛰고 이어서")
    ap.add_argument("--rejudge", type=Path, help="결과 파일의 채점만 다시")
    a = ap.parse_args()
    if a.rejudge:
        rejudge(a.rejudge)
    elif a.label and a.model:
        run(a.label, a.model, a.only.split(",") if a.only else None, a.resume,
            a.exclude_category.split(",") if a.exclude_category else None)
    else:
        ap.error("--label과 --model, 또는 --rejudge")
