import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import messages
from app.config import MAX_ASSISTANT_CHARS, MAX_INPUT_CHARS, MAX_MESSAGES
from app.llm import CreditExhausted, stream_chat
from app.prompt import build_messages, load_character

log = logging.getLogger(__name__)
app = FastAPI()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/intro")
def intro():
    return {"text": load_character().intro}


def _bad(code: str, message: str = messages.ERROR_RETRY):
    return JSONResponse({"code": code, "message": message}, status_code=400)


def _validate(body) -> JSONResponse | None:
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
    if msgs[-1]["role"] != "user":
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
