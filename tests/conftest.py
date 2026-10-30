import importlib

import pytest
from fastapi.testclient import TestClient

import app.config as c
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def env():
    # 환경 변수를 되돌린 뒤 config를 다시 리로드해 오염 방지
    with pytest.MonkeyPatch.context() as mp:
        yield mp
    importlib.reload(c)


@pytest.fixture(autouse=True)
def no_price_fetch(monkeypatch):
    # 실행 정보의 단가 조회가 테스트에서 네트워크로 나가지 않게
    import eval.pricing

    def offline(*a, **k):
        raise RuntimeError("테스트에서 네트워크 안 씀")
    monkeypatch.setattr(eval.pricing.httpx, "get", offline)
