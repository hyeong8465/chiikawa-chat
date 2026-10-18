import json
import logging
import os
import uuid
from dataclasses import dataclass
from functools import cache
from typing import Iterator

import openai

from app.config import CHAT_MODEL, MAX_TOKENS_CHAT, MAX_TOKENS_OTHER, PROMPT_VERSION, PROVIDER, REASONING

log = logging.getLogger(__name__)


@dataclass
class Usage:
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    cost: float


class CreditExhausted(Exception):
    pass


class StreamError(Exception):
    pass


@cache
def _client():
    # Langfuse 래퍼. 키가 없으면 기록만 꺼지고 호출은 그대로 동작
    from langfuse.openai import OpenAI

    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        log.warning("OPENROUTER_API_KEY 없음: 호출은 401로 실패함")
    # 재시도는 _create에서 1회만(SDK 재시도 끔)
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=key or "unset",  # 빈 값이면 생성자가 거부
        max_retries=0,
        timeout=60,
    )


def _usage(u) -> Usage:
    d = getattr(u, "prompt_tokens_details", None)
    return Usage(
        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
        cache_read_tokens=getattr(d, "cached_tokens", 0) or 0,
        cache_write_tokens=getattr(d, "cache_write_tokens", 0) or 0,
        output_tokens=getattr(u, "completion_tokens", 0) or 0,
        cost=getattr(u, "cost", 0.0) or 0.0,
    )


def _kwargs(messages, model, chat: bool, trace_id: str) -> dict:
    extra = {"usage": {"include": True}}
    if model.startswith("anthropic/"):
        extra = {"provider": PROVIDER, **extra}
    if chat:
        extra["reasoning"] = REASONING
    return {
        "model": model,
        "messages": messages,
        "max_tokens": MAX_TOKENS_CHAT if chat else MAX_TOKENS_OTHER,
        "extra_body": extra,
        "trace_id": trace_id,
        "metadata": {"prompt_version": PROMPT_VERSION},
    }


def _is_credit(e: openai.APIError) -> bool:
    body = e.body if isinstance(e.body, dict) else {}
    if isinstance(body.get("error"), dict):
        body = body["error"]
    status = getattr(e, "status_code", None) or body.get("code")
    meta = body.get("metadata")
    return status == 402 or (status == 403 and isinstance(meta, dict) and "limit_source" in meta)


def _create(kwargs: dict):
    # 429·5xx·연결 오류는 첫 토큰 전 1회 재시도
    for attempt in (0, 1):
        try:
            return _client().chat.completions.create(**kwargs)
        except openai.APIError as e:
            if _is_credit(e):
                raise CreditExhausted from e
            status = getattr(e, "status_code", None)
            retry = isinstance(e, openai.APIConnectionError) or (
                status is not None and (status == 429 or status >= 500)
            )
            if attempt == 0 and retry:
                continue
            raise


def _check_error(obj):
    err = getattr(obj, "error", None)
    if err:
        raise StreamError(str(err))


def stream_chat(messages: list[dict], model: str = CHAT_MODEL) -> Iterator[tuple[str, object]]:
    trace_id = uuid.uuid4().hex
    stream = _create(
        {
            **_kwargs(messages, model, True, trace_id),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    )
    usage = None
    finished = False
    try:
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for ch in getattr(chunk, "choices", None) or []:
                fr = getattr(ch, "finish_reason", None)
                if fr == "error":
                    raise StreamError("finish_reason=error")
                finished = finished or fr is not None
                text = getattr(getattr(ch, "delta", None), "content", None)
                if text:
                    yield "delta", text
    except openai.APIError as e:  # 스트림 중 SSE error는 SDK가 예외로 던짐
        if _is_credit(e):
            raise CreditExhausted from e
        raise StreamError(str(e)) from e
    if not finished:
        raise StreamError("finish_reason 없이 종료")
    yield "done", {"usage": _usage(usage), "trace_id": trace_id}


def complete(messages: list[dict], model: str) -> tuple[str, Usage]:
    res = _create(_kwargs(messages, model, False, uuid.uuid4().hex))
    _check_error(res)
    ch = (getattr(res, "choices", None) or [None])[0]
    if ch is None or getattr(ch, "finish_reason", None) == "error":
        raise StreamError("no choices")
    return ch.message.content or "", _usage(res.usage)


def extract_json(text: str) -> dict | list:
    try:
        out = json.loads(text)
        if isinstance(out, (dict, list)):
            return out
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for i, c in enumerate(text):
        if c in "{[":
            try:
                return dec.raw_decode(text, i)[0]
            except ValueError:
                continue
    raise ValueError("JSON 없음")


def score(trace_id: str, value: int) -> None:
    # 사용자 피드백(1 / -1). 키 없음·전송 실패는 로그만
    try:
        from langfuse import get_client

        get_client().create_score(name="feedback", value=value, trace_id=trace_id)
    except Exception as e:
        log.warning("feedback 기록 실패: %s", type(e).__name__)
