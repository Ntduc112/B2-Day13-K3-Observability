from __future__ import annotations

import json
from pathlib import Path

from scripts import validate_logs


def test_validator_detects_raw_vietnamese_phone(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    log_path = tmp_path / "logs.jsonl"
    record = {
        "ts": "2026-08-10T00:00:00Z",
        "level": "info",
        "service": "api",
        "event": "request_received",
        "correlation_id": "req-12345678",
        "user_id_hash": "abc123",
        "session_id": "session-01",
        "feature": "monitoring",
        "model": "fake-llm",
        "payload": {"message_preview": "Contact 090 123 4567"},
    }
    log_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(validate_logs, "LOG_PATH", log_path)

    validate_logs.main()

    output = capsys.readouterr().out
    assert "Potential PII leaks detected: 1" in output
    assert "phone_vn" in output
    assert "[FAILED] PII scrubbing" in output


def test_validator_reports_each_supported_raw_pii_type(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    log_path = tmp_path / "logs.jsonl"
    record = {
        "ts": "2026-08-10T00:00:00Z",
        "level": "error",
        "service": "api",
        "event": "request_failed",
        "correlation_id": "req-12345678",
        "user_id_hash": "abc123",
        "session_id": "session-01",
        "feature": "monitoring",
        "model": "fake-llm",
        "payload": {
            "email": "student+observability@example.com",
            "phone_numeric": 84901234567,
            "cccd": "001203004567",
            "card": "4111 1111 1111 1111",
            "passport": "B1234567",
            "address": "Dia chi: 123 Duong Vi Du, Phuong Mau, Ha Noi",
        },
    }
    log_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(validate_logs, "LOG_PATH", log_path)

    validate_logs.main()

    output = capsys.readouterr().out
    assert "email" in output
    assert "phone_vn" in output
    assert "cccd" in output
    assert "credit_card" in output
    assert "passport" in output
    assert "address" in output
    assert "Potential PII leaks detected: 1" in output
    assert "[FAILED] PII scrubbing" in output


def test_validator_accepts_logs_containing_only_redaction_markers(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    log_path = tmp_path / "logs.jsonl"
    records = [
        {
            "ts": "2026-08-10T00:00:00Z",
            "level": "info",
            "service": "api",
            "event": "request_received",
            "correlation_id": f"req-0000000{index}",
            "user_id_hash": "abc123",
            "session_id": "session-01",
            "feature": "monitoring",
            "model": "fake-llm",
            "payload": {"message_preview": "Contact [REDACTED_EMAIL]"},
        }
        for index in (1, 2)
    ]
    log_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_logs, "LOG_PATH", log_path)

    validate_logs.main()

    output = capsys.readouterr().out
    assert "Potential PII leaks detected: 0" in output
    assert "+ [PASSED] PII scrubbing" in output
