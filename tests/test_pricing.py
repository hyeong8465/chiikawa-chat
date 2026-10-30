import httpx
import pytest

from eval import pricing
from eval.report import cache_table

P = {"prompt": 2e-6, "completion": 1e-5, "cache_read": 1e-7, "cache_write": 2.5e-6}


def test_no_cache_cost():
    # 읽기 1000토큰은 일반 값이었으면 1000*(2e-6-1e-7) 더 냄, 쓰기 100토큰은 1.25배라 100*(2.5e-6-2e-6) 덜 냄
    u = {"input_tokens": 1200, "cache_read_tokens": 1000, "cache_write_tokens": 100, "output_tokens": 10, "cost": 0.01}
    assert pricing.no_cache_cost(u, P) == pytest.approx(0.01 + 1000 * 1.9e-6 - 100 * 0.5e-6)


def test_prices_missing(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("x")
    monkeypatch.setattr(pricing.httpx, "get", boom)
    assert pricing.fetch(["m"]) is None
    assert pricing.no_cache_cost({"cost": 1.0}, None) is None


def test_fetch_parses(monkeypatch):
    data = {"data": [{"id": "m", "pricing": {"prompt": "0.000002", "completion": "0.00001",
                                             "input_cache_read": "0.0000001", "input_cache_write": "0.0000025"}},
                     {"id": "other", "pricing": {"prompt": "1"}}]}
    monkeypatch.setattr(pricing.httpx, "get", lambda *a, **k: httpx.Response(200, json=data, request=httpx.Request("GET", "http://x")))
    assert pricing.fetch(["m"]) == {"m": P}


def test_cache_table():
    meta = {"gen": {"model": "g"}, "judge": {"model": "j"}, "sim": {"model": "s"}, "prices": {"g": P, "j": P}}
    u = {"input_tokens": 1000, "cache_read_tokens": 900, "cache_write_tokens": 0, "output_tokens": 0, "cost": 0.001}
    z = {k: 0 for k in u}
    rows = [{"usage_parts": {"chat": u, "sim": z, "judge": u}}] * 2
    t = cache_table(meta, rows)
    assert "| 생성 | $0.0020 |" in t and "90%" in t and "| 사용자 흉내 |" not in t  # 안 쓴 단계는 빼기
    assert "| 합계 |" in t
    assert "| 생성 | $0.0020 | 2,000 | 1,800 | 0 | 90% | $0.0054 | 63% |" in t


def test_cache_table_no_prices():
    u = {"input_tokens": 10, "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0, "cost": 0.5}
    t = cache_table({"gen": {"model": "g"}, "judge": {"model": "j"}}, [{"usage_parts": {"chat": u, "judge": u}}])
    assert "| 생성 | $0.5000 | 10 | 0 | 0 | 0% | - | - |" in t
