from __future__ import annotations

import json
from pathlib import Path

from app import logging_config


def test_jsonl_sink_scrubs_pii_from_nested_fields_and_formatted_exceptions(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    logging_config.configure_logging()
    logger = logging_config.get_logger()
    raw_values = (
        "student+observability@example.com",
        "+84 90 123 4567",
        "001203004567",
        "4111 1111 1111 1111",
        "B1234567",
        "Dia chi: 123 Duong Vi Du, Phuong Mau, Ha Noi",
    )

    try:
        raise RuntimeError(f"Could not notify {raw_values[0]}")
    except RuntimeError:
        logger.exception(
            "request_failed",
            service="api",
            correlation_id="req-deadbeef",
            contact=raw_values[0],
            payload={
                "contacts": [raw_values[1], {raw_values[0]: raw_values[2]}],
                "payment": raw_values[3],
                "identity": {"passport": raw_values[4]},
                "location": raw_values[5],
            },
        )

    serialized_log = log_path.read_text(encoding="utf-8")
    record = json.loads(serialized_log)

    for raw_value in raw_values:
        assert raw_value not in serialized_log
    assert record["contact"] == "[REDACTED_EMAIL]"
    assert "[REDACTED_EMAIL]" in record["exception"]
    assert "[REDACTED_PHONE_VN]" in serialized_log
    assert "[REDACTED_CCCD]" in serialized_log
    assert "[REDACTED_CREDIT_CARD]" in serialized_log
    assert "[REDACTED_PASSPORT]" in serialized_log
    assert "[REDACTED_ADDRESS]" in serialized_log
