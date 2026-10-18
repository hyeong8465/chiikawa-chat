import json
import os
import uuid
from dataclasses import dataclass
from typing import Iterator

import openai

from app.config import CHAT_MODEL, PROMPT_VERSION, PROVIDER, REASONING


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


def _client():
    # Langfuse 래퍼. 키가 없으면 기록만 꺼지고 호출은 그대로 동작
    from langfuse.openai import OpenAI

    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY") or "unset",  # 빈 값이면 생성자가 거부
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
        "extra_body": extra,
        "trace_id": trace_id,
        "metadata": {"prompt_version": PROMPT_VERSION},
    }


def _is_credit(e: openai.APIStatusError) -> bool:
    if e.status_code == 402:
        return True
    body = e.body if isinstance(e.body, dict) else {}
    body = body.get("error", body) if isinstance(body.get("error"), dict) else body
    meta = body.get("metadata") or {}
    return e.status_code == 403 and isinstance(meta, dict) and "limit_source" in meta


def _create(kwargs: dict):
    # 429·5xx는 첫 토큰 전 1회 재시도
    for attempt in (0, 1):
        try:
            return _client().chat.completions.create(**kwargs)
        except openai.APIStatusError as e:
            if _is_credit(e):
                raise CreditExhausted from e
            if attempt == 0 and (e.status_code == 429 or e.status_code >= 500):
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
    for chunk in stream:
        _check_error(chunk)
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        for ch in getattr(chunk, "choices", None) or []:
            if getattr(ch, "finish_reason", None) == "error":
                raise StreamError("finish_reason=error")
            text = getattr(getattr(ch, "delta", None), "content", None)
            if text:
                yield "delta", text
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
        return json.loads(text)
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
