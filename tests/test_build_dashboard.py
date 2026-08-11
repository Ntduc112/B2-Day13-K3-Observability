from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_dashboard  # noqa: E402

NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def write_logs(path: Path, records: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return path


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def test_load_records_drops_entries_older_than_the_window(tmp_path: Path) -> None:
    log_path = write_logs(
        tmp_path / "logs.jsonl",
        [
            {"ts": at(10), "event": "request_received"},
            {"ts": at(90), "event": "request_received"},
        ],
    )

    records = build_dashboard.load_records(log_path, now=NOW, window_minutes=60)

    assert [record["ts"] for record in records] == [at(10)]


def test_load_records_skips_malformed_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        json.dumps({"ts": at(1), "event": "request_received"}) + "\n"
        "{ this is not json\n"
        "\n",
        encoding="utf-8",
    )

    records = build_dashboard.load_records(log_path, now=NOW, window_minutes=60)

    assert len(records) == 1


CONTRACT = yaml.safe_load(
    (REPO_ROOT / "config" / "dashboard.yaml").read_text(encoding="utf-8")
)["dashboard"]


def received(minutes_ago: float = 1, feature: str = "qa") -> dict:
    return {"ts": at(minutes_ago), "event": "request_received", "feature": feature}


def response(
    latency_ms: int,
    *,
    minutes_ago: float = 1,
    feature: str = "qa",
    cost_usd: float = 0.001,
    tokens_in: int = 10,
    tokens_out: int = 20,
    quality_score: float = 0.9,
) -> dict:
    return {
        "ts": at(minutes_ago),
        "event": "response_sent",
        "feature": feature,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "quality_score": quality_score,
    }


def failed(error_type: str = "RuntimeError", *, minutes_ago: float = 1) -> dict:
    return {"ts": at(minutes_ago), "event": "request_failed", "error_type": error_type}


def panels_for(records: list[dict]) -> dict:
    return build_dashboard.compute_panels(records, CONTRACT, now=NOW)


def test_compute_panels_covers_every_contract_panel_plus_the_feature_panel() -> None:
    panels = panels_for([received(), response(100)])

    assert set(panels) == {
        "latency",
        "traffic",
        "errors",
        "cost",
        "tokens",
        "quality",
        "by_feature",
    }


def test_latency_panel_reports_nearest_rank_percentiles() -> None:
    panels = panels_for([response(latency) for latency in range(1, 11)])

    assert panels["latency"]["values"]["p50"] == 5.0


def test_latency_panel_is_breached_when_p95_exceeds_the_contract_threshold() -> None:
    healthy = panels_for([response(1000)])
    slow = panels_for([response(4400)])

    assert healthy["latency"]["breached"] is False
    assert slow["latency"]["breached"] is True


def test_quality_panel_is_breached_when_mean_falls_below_the_floor() -> None:
    # Ngưỡng quality dùng operator gte, ngược hướng với latency.
    panels = panels_for([response(100, quality_score=0.5)])

    assert panels["quality"]["values"]["mean"] == 0.5
    assert panels["quality"]["breached"] is True


def test_errors_panel_divides_failures_by_received_requests() -> None:
    records = [received(), received(), received(), received(), failed()]

    panels = panels_for(records)

    assert panels["errors"]["values"]["error_rate_pct"] == 25.0
    assert panels["errors"]["values"]["count_by_value"] == {"RuntimeError": 1}


def test_errors_panel_is_zero_when_no_request_was_received() -> None:
    panels = panels_for([])

    assert panels["errors"]["values"]["error_rate_pct"] == 0.0


def test_by_feature_panel_reports_p95_for_each_feature() -> None:
    records = [
        response(4400, feature="refund"),
        response(1200, feature="qa"),
        response(1100, feature="summary"),
    ]

    panels = panels_for(records)

    assert panels["by_feature"]["values"] == {
        "refund": 4400.0,
        "qa": 1200.0,
        "summary": 1100.0,
    }


def test_by_feature_panel_borrows_the_latency_threshold() -> None:
    panels = panels_for([response(4400, feature="refund")])

    assert panels["by_feature"]["threshold"]["value"] == 3000
    assert panels["by_feature"]["breached"] is True


def test_cost_and_token_panels_sum_over_the_window() -> None:
    records = [response(100, cost_usd=0.5, tokens_in=3, tokens_out=7) for _ in range(2)]

    panels = panels_for(records)

    assert panels["cost"]["values"]["total"] == 1.0
    assert panels["tokens"]["values"]["tokens_in"] == 6
    assert panels["tokens"]["values"]["tokens_out"] == 14


def test_traffic_panel_counts_received_requests_per_minute() -> None:
    records = [received(minutes_ago=5) for _ in range(3)] + [received(minutes_ago=4)]

    panels = panels_for(records)

    assert panels["traffic"]["values"]["count"] == 4
    assert panels["traffic"]["values"]["rate_per_minute"] == round(4 / 60, 2)


def meta(refresh_seconds: int | None = None) -> dict:
    return {
        "title": CONTRACT["title"],
        "generated_at": NOW,
        "window_minutes": CONTRACT["time_range_minutes"],
        "record_count": 42,
        "refresh_seconds": refresh_seconds,
    }


def test_rendered_page_shows_every_panel_title_and_unit() -> None:
    panels = panels_for([received(), response(1000)])

    html = build_dashboard.render_html(panels, meta())

    for panel in panels.values():
        assert panel["title"] in html
        assert panel["unit"] in html


def test_rendered_page_states_the_time_range_and_record_count() -> None:
    html = build_dashboard.render_html(panels_for([received()]), meta())

    assert "60" in html
    assert "42" in html


def card_for(page: str, title: str) -> str:
    start = page.index(title)
    return page[start : page.index("</section>", start)]


def test_rendered_page_flags_a_breached_panel() -> None:
    healthy = build_dashboard.render_html(panels_for([response(1000)]), meta())
    breached = build_dashboard.render_html(panels_for([response(4400)]), meta())

    assert "BREACH" not in card_for(healthy, "Latency percentiles")
    assert "BREACH" in card_for(breached, "Latency percentiles")


def test_rendered_page_only_auto_refreshes_when_asked() -> None:
    panels = panels_for([received()])

    assert "http-equiv" not in build_dashboard.render_html(panels, meta())
    assert "http-equiv" in build_dashboard.render_html(panels, meta(refresh_seconds=30))


def test_write_html_replaces_the_file_without_leaving_a_temp_behind(tmp_path: Path) -> None:
    target = tmp_path / "dashboard.html"
    target.write_text("stale", encoding="utf-8")

    build_dashboard.write_html(target, "<p>fresh</p>")

    assert target.read_text(encoding="utf-8") == "<p>fresh</p>"
    assert [item.name for item in tmp_path.iterdir()] == ["dashboard.html"]
