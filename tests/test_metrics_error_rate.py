from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import incidents, logging_config, metrics
from app.main import app


@pytest.fixture(autouse=True)
def reset_metrics():
    """Bộ đếm trong app.metrics là biến module nên phải reset giữa các test."""
    metrics.TRAFFIC = 0
    metrics.ERRORS.clear()
    for series in (
        metrics.REQUEST_LATENCIES,
        metrics.REQUEST_COSTS,
        metrics.REQUEST_TOKENS_IN,
        metrics.REQUEST_TOKENS_OUT,
        metrics.QUALITY_SCORES,
    ):
        series.clear()
    yield


def test_error_rate_pct_is_zero_when_nothing_has_been_recorded() -> None:
    assert metrics.snapshot()["error_rate_pct"] == 0.0


def test_error_rate_pct_is_zero_when_every_request_succeeds() -> None:
    for _ in range(4):
        metrics.record_request(latency_ms=100, cost_usd=0.1, tokens_in=1, tokens_out=1, quality_score=0.9)

    assert metrics.snapshot()["error_rate_pct"] == 0.0


def test_error_rate_pct_divides_by_attempts_not_by_successes() -> None:
    # 3 thành công + 1 lỗi = 4 lần thử -> 25%. Nếu mẫu số là TRAFFIC (chỉ đếm
    # thành công) thì kết quả sẽ là 33.33%.
    for _ in range(3):
        metrics.record_request(latency_ms=100, cost_usd=0.1, tokens_in=1, tokens_out=1, quality_score=0.9)
    metrics.record_error("RuntimeError")

    assert metrics.snapshot()["error_rate_pct"] == 25.0


def test_error_rate_pct_is_100_when_every_attempt_fails() -> None:
    # Kịch bản tool_fail hỏng toàn bộ request: TRAFFIC = 0. Mẫu số là TRAFFIC
    # thì chia cho 0.
    for _ in range(3):
        metrics.record_error("RuntimeError")

    assert metrics.snapshot()["error_rate_pct"] == 100.0


def test_failed_chat_request_is_counted_once(monkeypatch, tmp_path: Path) -> None:
    # app/main.py bắt lỗi trong /chat và cũng có global exception handler;
    # cả hai đều gọi record_error. Test này chốt là chỉ một cái chạy.
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
    monkeypatch.setitem(incidents.STATE, "tool_fail", True)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "student-01",
                "session_id": "session-01",
                "feature": "qa",
                "message": "Explain observability",
            },
        )

    assert response.status_code == 500
    snapshot = metrics.snapshot()
    assert snapshot["error_breakdown"] == {"RuntimeError": 1}
    assert snapshot["error_rate_pct"] == 100.0
