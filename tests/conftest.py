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
