import json
import re
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import messages
from app.config import CHAT_MODEL, MAX_TOKENS_CONVERT, MAX_TOTAL_CHARS, MAX_ASSISTANT_CHARS, MAX_INPUT_CHARS, MAX_MESSAGES, SUGGEST_MODEL
from app.llm import CreditExhausted, complete, extract_json, score, stream_chat
from app.prompt import build_messages, fill, load_character, speech_rules

log = logging.getLogger(__name__)
app = FastAPI()
STATIC = Path(__file__).parent / "static"


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/intro")
def intro():
    return {"text": load_character().intro}


def _bad(code: str, message: str = messages.ERROR_RETRY):
    return JSONResponse({"code": code, "message": message}, status_code=400)


def _validate(body, last: str = "user") -> JSONResponse | None:
    msgs = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(msgs, list) or not msgs:
        return _bad("invalid")
    if len(msgs) > MAX_MESSAGES:
        return _bad("too_many")
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            return _bad("invalid")
        c = m.get("content")
        if not isinstance(c, str) or not c.strip():
            return _bad("invalid")
        if len(c) > (MAX_INPUT_CHARS if m["role"] == "user" else MAX_ASSISTANT_CHARS):
            return _bad("too_long", messages.TOO_LONG)
    if sum(len(m["content"]) for m in msgs) > MAX_TOTAL_CHARS:
        return _bad("too_long", messages.TOO_LONG)
    if msgs[-1]["role"] != last:
        return _bad("invalid")
    return None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _bad("invalid")
    if (err := _validate(body)) is not None:
        return err
    history = [{"role": m["role"], "content": m["content"]} for m in body["messages"]]

    def events():
        try:
            for kind, val in stream_chat(build_messages(history)):
                if kind == "delta":
                    yield _sse("delta", {"text": val})
                else:
                    yield _sse("done", {"trace_id": val["trace_id"]})
        except CreditExhausted:
            yield _sse("error", {"code": "credit", "message": messages.CREDIT_EXHAUSTED})
        except Exception as e:
            # 키·본문 노출 방지: 종류와 상태 코드만
            log.error("chat 실패: %s status=%s", type(e).__name__, getattr(e, "status_code", None))
            yield _sse("error", {"code": "retry", "message": messages.ERROR_RETRY})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


SUGGEST_RECENT = 6
SUGGEST_MAX_CHARS = 30


def _parse_suggestions(text: str) -> list[str]:
    out = extract_json(text)
    if not isinstance(out, list) or not all(isinstance(x, str) for x in out):
        return []
    out = [x.strip() for x in out if x.strip()]
    out = [x for x in out if len(x) <= SUGGEST_MAX_CHARS]
    return out if len(out) == 3 else []


@app.post("/api/suggest")
async def suggest(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _bad("invalid")
    if (err := _validate(body, last="assistant")) is not None:
        return err
    names = {"user": "사용자", "assistant": "하치와레"}
    # 줄바꿈·꺾쇠 치환: 사용자 글로 "하치와레: …" 화자 위조나 태그 탈출 방지
    clean = lambda c: c.replace("\n", " ").replace("<", "＜").replace(">", "＞")
    convo = "\n".join(f"{names[m['role']]}: {clean(m['content'])}" for m in body["messages"][-SUGGEST_RECENT:])
    tpl = (Path(__file__).parent / "prompts" / "suggest.md").read_text(encoding="utf-8")
    try:
        # 동기 호출을 스레드로: async 안에서 직접 부르면 기다리는 동안 다른 요청 전부 멈춤
        text, _ = await run_in_threadpool(complete, [{"role": "user", "content": fill(tpl, conversation=convo)}], SUGGEST_MODEL)
        return {"suggestions": _parse_suggestions(text)}
    except Exception as e:
        # 본 대화에 영향 없게 숨김. 크레딧 소진 포함 모든 실패
        log.warning("suggest 실패: %s", type(e).__name__)
        return {"suggestions": []}


CONVERT_MAX_CHARS = 200
CONVERT_OUT_MAX = 300


def _parse_convert(text: str) -> dict:
    out = extract_json(text)
    if not isinstance(out, dict):
        raise ValueError("dict 아님")
    keys = ("intent",) if "refused" not in out else ("refused",)
    res = {}
    for k in keys:
        v = out.get(k)
        if not isinstance(v, str) or not v.strip() or len(v) > CONVERT_OUT_MAX:
            raise ValueError(f"{k} 불량")
        res[k] = v.strip()
    return res


@app.post("/api/convert")
async def convert(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _bad("invalid")
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        return _bad("invalid")
    text = text.strip()
    if len(text) > CONVERT_MAX_CHARS:
        return _bad("too_long", messages.TOO_LONG)
    tpl = (Path(__file__).parent / "prompts" / "convert.md").read_text(encoding="utf-8")
    rules = speech_rules(load_character())
    safe = text.replace("<", "＜").replace(">", "＞")  # </text>로 태그를 닫고 지시를 끼워 넣는 것 방지
    prompt = fill(fill(tpl, speech_rules=rules), text=safe)  # 규칙 먼저: 사용자 입력 속 자리표시 재치환 방지
    try:
        out, _ = await run_in_threadpool(complete, [{"role": "user", "content": prompt}], CHAT_MODEL, MAX_TOKENS_CONVERT, reasoning=True)
        return _parse_convert(out)
    except CreditExhausted:
        return JSONResponse({"code": "credit", "message": messages.CREDIT_EXHAUSTED}, status_code=502)
    except Exception as e:
        log.warning("convert 실패: %s", type(e).__name__)
        return JSONResponse({"code": "retry", "message": messages.ERROR_RETRY}, status_code=502)


@app.post("/api/feedback")
async def feedback(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _bad("invalid")
    tid = body.get("trace_id") if isinstance(body, dict) else None
    val = body.get("value") if isinstance(body, dict) else None
    if not isinstance(tid, str) or not re.fullmatch(r"[0-9a-f]{32}", tid):  # 서버가 만든 uuid4().hex 형식만
        return _bad("invalid")
    if type(val) is not int or val not in (1, -1, 0):  # 0 = 취소
        return _bad("invalid")
    await run_in_threadpool(score, tid, val)
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
