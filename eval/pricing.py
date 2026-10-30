"""OpenRouter 단가 → 캐시 없었을 때 비용(절감 계산). 단가는 실행 정보에 남겨 나중에 같은 계산 재현"""
import httpx

URL = "https://openrouter.ai/api/v1/models"
_FIELDS = {"prompt": "prompt", "completion": "completion", "cache_read": "input_cache_read", "cache_write": "input_cache_write"}


def fetch(models: list[str]) -> dict[str, dict] | None:
    # 토큰당 달러. 못 가져오면 None(절감 칸만 "-", 실행은 계속). 토큰 수에 따른 할증(overrides)은 무시: 우리 입력은 그 문턱 아래
    try:
        data = httpx.get(URL, timeout=10).raise_for_status().json()["data"]
        out = {m["id"]: {k: float(m["pricing"].get(f, 0) or 0) for k, f in _FIELDS.items()}
               for m in data if m["id"] in models}
    except Exception:
        return None
    return out or None


def no_cache_cost(u: dict, p: dict | None) -> float | None:
    # 같은 입력을 전부 일반 값으로 냈다면. 실제 비용(청구액) + 읽기 할인분 − 쓰기 할증분
    if not p:
        return None
    return (u["cost"] + u.get("cache_read_tokens", 0) * (p["prompt"] - p["cache_read"])
            + u.get("cache_write_tokens", 0) * (p["prompt"] - p["cache_write"]))
