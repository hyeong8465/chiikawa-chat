import pytest

import eval.run as run
from app.llm import StreamError


def test_stream_error_stops_only_that_scenario(monkeypatch):
    # 잘린 답 하나로 평가 전체(결과 파일)가 날아가지 않게: 그 시나리오만 오류로 기록
    def boom(*a, **k):
        raise StreamError("finish_reason=length")
        yield
    monkeypatch.setattr(run.llm, "stream_chat", boom)
    monkeypatch.setattr(run.judge, "checklist", lambda *a, **k: pytest.fail("채점하면 안 됨"))
    row = run.run_one({"id": "x", "category": "daily", "turns": ["안녕", "뭐해"]}, "m")
    assert row["judge"] == {"error": "StreamError: finish_reason=length"}
    assert row["responses"] == []
