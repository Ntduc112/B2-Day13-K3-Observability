from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio  # noqa: E402
from app.metrics import percentile  # noqa: E402


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_records(path: Path, *, now: datetime, window_minutes: int) -> list[dict]:
    """Đọc log JSONL và giữ lại các record nằm trong cửa sổ thời gian."""
    cutoff = now - timedelta(minutes=window_minutes)
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        ts = _parse_ts(record.get("ts"))
        if ts is None or ts < cutoff:
            continue
        records.append(record)
    return records


def _numbers(records: list[dict], event: str, field: str) -> list[float]:
    """Lấy các giá trị số của một field.

    Bỏ qua giá trị không phải số: PII scrubber có thể biến một số thành chuỗi
    đã che, và panel không được vì thế mà hỏng.
    """
    values: list[float] = []
    for record in records:
        if record.get("event") != event:
            continue
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(value)
    return values


def _count(records: list[dict], event: str) -> int:
    return sum(1 for record in records if record.get("event") == event)


def _per_minute(records: list[dict], event: str, field: str | None, *, now: datetime, window_minutes: int) -> list[float]:
    """Gom theo từng phút, cũ nhất trước, dùng cho sparkline."""
    buckets = [0.0] * window_minutes
    for record in records:
        if record.get("event") != event:
            continue
        ts = _parse_ts(record.get("ts"))
        if ts is None:
            continue
        index = window_minutes - 1 - int((now - ts).total_seconds() // 60)
        if not 0 <= index < window_minutes:
            continue
        if field is None:
            buckets[index] += 1
            continue
        value = record.get(field)
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            buckets[index] += value
    return buckets


def _breached(value: float, threshold: dict) -> bool:
    if threshold.get("operator") == "lte":
        return value > threshold["value"]
    return value < threshold["value"]


def compute_panels(records: list[dict], config: dict, *, now: datetime) -> dict[str, dict]:
    """Tính giá trị từng panel từ log, theo đúng contract trong dashboard.yaml."""
    window = config["time_range_minutes"]
    by_id = {panel["id"]: panel for panel in config["panels"]}

    latencies = [int(value) for value in _numbers(records, "response_sent", "latency_ms")]
    received = _count(records, "request_received")
    failures = [record for record in records if record.get("event") == "request_failed"]
    costs = _numbers(records, "response_sent", "cost_usd")
    tokens_in = _numbers(records, "response_sent", "tokens_in")
    tokens_out = _numbers(records, "response_sent", "tokens_out")
    quality = _numbers(records, "response_sent", "quality_score")

    values: dict[str, dict] = {
        "latency": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "p99": percentile(latencies, 99),
        },
        "traffic": {
            "count": received,
            "rate_per_minute": round(received / window, 2),
        },
        "errors": {
            "error_rate_pct": round(len(failures) / received * 100, 2) if received else 0.0,
            "count_by_value": dict(
                Counter(record.get("error_type", "unknown") for record in failures)
            ),
        },
        "cost": {"total": round(sum(costs), 6)},
        "tokens": {
            "tokens_in": int(sum(tokens_in)),
            "tokens_out": int(sum(tokens_out)),
        },
        "quality": {"mean": round(mean(quality), 4) if quality else 0.0},
    }

    scalars = {
        "latency": values["latency"]["p95"],
        "traffic": values["traffic"]["rate_per_minute"],
        "errors": values["errors"]["error_rate_pct"],
        "cost": values["cost"]["total"],
        "tokens": max(values["tokens"]["tokens_in"], values["tokens"]["tokens_out"]),
        "quality": values["quality"]["mean"],
    }

    series = {
        "traffic": _per_minute(records, "request_received", None, now=now, window_minutes=window),
        "cost": _per_minute(records, "response_sent", "cost_usd", now=now, window_minutes=window),
    }

    panels = {
        panel_id: {
            "title": by_id[panel_id]["title"],
            "unit": by_id[panel_id]["unit"],
            "values": values[panel_id],
            "threshold": by_id[panel_id]["threshold"],
            "breached": _breached(scalars[panel_id], by_id[panel_id]["threshold"]),
            "series": series.get(panel_id),
        }
        for panel_id in values
    }
    panels["by_feature"] = _feature_panel(records, by_id["latency"]["threshold"])
    return panels


def _feature_panel(records: list[dict], latency_threshold: dict) -> dict:
    """Panel thứ 7: P95 theo feature.

    Nằm ngoài dashboard.yaml vì validator yêu cầu contract có đúng 6 panel,
    nên nó mượn ngưỡng của panel latency — cùng đại lượng, cùng ngưỡng.
    """
    grouped: dict[str, list[int]] = {}
    for record in records:
        if record.get("event") != "response_sent":
            continue
        latency = record.get("latency_ms")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            continue
        grouped.setdefault(str(record.get("feature", "unknown")), []).append(int(latency))

    values = {feature: percentile(items, 95) for feature, items in sorted(grouped.items())}
    return {
        "title": "Latency P95 by feature",
        "unit": "ms",
        "values": values,
        "threshold": latency_threshold,
        "breached": any(_breached(value, latency_threshold) for value in values.values()),
        "series": None,
    }


CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: #f5f6f8; color: #16191d;
       font: 14px/1.5 "Segoe UI", system-ui, sans-serif; }
header { margin-bottom: 20px; }
h1 { margin: 0 0 6px; font-size: 22px; }
.sub { color: #5c6470; font-size: 13px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.card { background: #fff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 16px; }
.card h2 { margin: 0; font-size: 14px; font-weight: 600; }
.unit { color: #5c6470; font-size: 12px; font-weight: 400; }
.row { display: flex; gap: 20px; margin: 12px 0 8px; }
.stat .k { color: #5c6470; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
.stat .v { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }
.slo { border-top: 1px dashed #dfe3e8; padding-top: 8px; margin-top: 8px;
       display: flex; justify-content: space-between; align-items: center;
       color: #5c6470; font-size: 12px; }
.badge { border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 700; letter-spacing: .04em; }
.ok { background: #e3f4e8; color: #1c6b34; }
.breach { background: #fde7e7; color: #a01b1b; }
.bar { display: grid; grid-template-columns: 90px 1fr 90px; gap: 8px; align-items: center; margin: 4px 0; }
.bar .track { background: #eef0f3; border-radius: 3px; height: 14px; position: relative; }
.bar .fill { background: #4a7fd4; height: 100%; border-radius: 3px; }
.bar .fill.over { background: #d05252; }
.bar .n { text-align: right; font-variant-numeric: tabular-nums; }
.kv { color: #16191d; font-variant-numeric: tabular-nums; }
svg { display: block; margin-top: 8px; }
"""


def sparkline(values: list[float], *, width: int = 288, height: int = 40) -> str:
    """Một polyline SVG duy nhất, dùng chung cho hai panel time-series."""
    if not values:
        return ""
    peak = max(values) or 1.0
    step = width / max(1, len(values) - 1)
    points = " ".join(
        f"{index * step:.1f},{height - (value / peak) * (height - 4):.1f}"
        for index, value in enumerate(values)
    )
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="time series">'
        f'<polyline points="{points}" fill="none" stroke="#4a7fd4" stroke-width="2"/>'
        f"</svg>"
    )


def _stat(label: str, value: object) -> str:
    return f'<div class="stat"><div class="k">{html.escape(label)}</div><div class="v">{html.escape(str(value))}</div></div>'


def _bars(values: dict[str, float], limit: float) -> str:
    if not values:
        return '<div class="sub">Chưa có dữ liệu</div>'
    peak = max(max(values.values()), limit) or 1.0
    rows = []
    for name, value in values.items():
        over = " over" if value > limit else ""
        width = value / peak * 100
        rows.append(
            f'<div class="bar"><span>{html.escape(name)}</span>'
            f'<span class="track"><span class="fill{over}" style="width:{width:.1f}%"></span></span>'
            f'<span class="n">{value:,.0f}</span></div>'
        )
    return "".join(rows)


def _body(panel_id: str, panel: dict) -> str:
    values = panel["values"]
    if panel_id == "latency":
        stats = "".join(_stat(key.upper(), f"{values[key]:,.0f}") for key in ("p50", "p95", "p99"))
        return f'<div class="row">{stats}</div>'
    if panel_id == "traffic":
        stats = _stat("count", f"{values['count']:,}") + _stat("req/min", values["rate_per_minute"])
        return f'<div class="row">{stats}</div>{sparkline(panel["series"] or [])}'
    if panel_id == "errors":
        breakdown = values["count_by_value"]
        detail = ", ".join(f"{name}: {count}" for name, count in breakdown.items()) or "không có lỗi"
        rate = _stat("error rate", "{}%".format(values["error_rate_pct"]))
        return f'<div class="row">{rate}</div><div class="sub kv">{html.escape(detail)}</div>'
    if panel_id == "cost":
        total = _stat("total", "${:.4f}".format(values["total"]))
        return f'<div class="row">{total}</div>{sparkline(panel["series"] or [])}'
    if panel_id == "tokens":
        stats = _stat("in", f"{values['tokens_in']:,}") + _stat("out", f"{values['tokens_out']:,}")
        return f'<div class="row">{stats}</div>'
    if panel_id == "quality":
        return f'<div class="row">{_stat("mean", values["mean"])}</div>'
    return _bars(values, panel["threshold"]["value"])


def render_html(panels: dict[str, dict], meta: dict) -> str:
    """Sinh một trang HTML self-contained, không phụ thuộc tài nguyên bên ngoài."""
    refresh = meta.get("refresh_seconds")
    refresh_tag = (
        f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    )
    cards = []
    for panel_id, panel in panels.items():
        threshold = panel["threshold"]
        operator = "≤" if threshold.get("operator") == "lte" else "≥"
        state = "breach" if panel["breached"] else "ok"
        label = "BREACH" if panel["breached"] else "OK"
        cards.append(
            f'<section class="card">'
            f'<h2>{html.escape(panel["title"])} <span class="unit">({html.escape(panel["unit"])})</span></h2>'
            f'{_body(panel_id, panel)}'
            f'<div class="slo"><span>SLO: {html.escape(str(threshold["aggregation"]))} '
            f'{operator} {threshold["value"]}</span>'
            f'<span class="badge {state}">{label}</span></div>'
            f"</section>"
        )
    generated = meta["generated_at"].strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        "<!doctype html><html lang=\"vi\"><head><meta charset=\"utf-8\">"
        f'<meta name="viewport" content="width=device-width, initial-scale=1">{refresh_tag}'
        f"<title>{html.escape(meta['title'])}</title><style>{CSS}</style></head><body>"
        f"<header><h1>{html.escape(meta['title'])}</h1>"
        f'<div class="sub">Time range: {meta["window_minutes"]} phút gần nhất '
        f"&middot; {meta['record_count']} log record &middot; sinh lúc {generated}"
        f"{f' &middot; tự refresh {refresh}s' if refresh else ''}</div></header>"
        f'<div class="grid">{"".join(cards)}</div></body></html>'
    )


def write_html(path: Path, content: str) -> None:
    """Ghi qua file tạm rồi thay thế, để browser không đọc trúng file viết dở."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def build_once(*, config_path: Path, log_path: Path, out_path: Path, refresh_seconds: int | None) -> dict:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))["dashboard"]
    now = datetime.now(timezone.utc)
    window = config["time_range_minutes"]
    records = load_records(log_path, now=now, window_minutes=window)
    panels = compute_panels(records, config, now=now)
    write_html(
        out_path,
        render_html(
            panels,
            {
                "title": config["title"],
                "generated_at": now,
                "window_minutes": window,
                "record_count": len(records),
                "refresh_seconds": refresh_seconds,
            },
        ),
    )
    return panels


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ data/logs.jsonl")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=REPO_ROOT / "data" / "logs.jsonl")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "build" / "dashboard.html")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Sinh lại theo chu kỳ refresh_seconds của contract và bật auto-refresh trong trang.",
    )
    args = parser.parse_args()

    if not args.logs.exists():
        print(f"Không tìm thấy log: {args.logs}. Chạy API và load_test trước.")
        return 1

    refresh = yaml.safe_load(args.config.read_text(encoding="utf-8"))["dashboard"]["refresh_seconds"]
    while True:
        panels = build_once(
            config_path=args.config,
            log_path=args.logs,
            out_path=args.out,
            refresh_seconds=refresh if args.watch else None,
        )
        breached = [panel["title"] for panel in panels.values() if panel["breached"]]
        status = f"BREACH: {', '.join(breached)}" if breached else "tất cả panel trong ngưỡng"
        print(f"{args.out} | {status}")
        if not args.watch:
            return 0
        time.sleep(refresh)


if __name__ == "__main__":
    raise SystemExit(main())
