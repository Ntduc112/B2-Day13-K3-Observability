from __future__ import annotations

import hashlib
import re
from typing import Any

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(
        r"(?<![\w.+-])[\w.%+-]+@(?:[\w-]+\.)+[A-Za-z]{2,63}(?![\w.-])"
    ),
    "credit_card": re.compile(
        r"(?<!\d)\d{4}(?:[ -]?\d{4}){3}(?![ -]?\d)"
    ),
    "cccd": re.compile(r"(?<!\d)\d{3}(?:[ .-]?\d{3}){3}(?![ .-]?\d)"),
    "phone_vn": re.compile(
        r"(?<![\d+])(?:\+?84|0)(?:[ .-]?\d){9,10}(?![ .-]?\d)"
    ),
    "passport": re.compile(r"(?<![A-Za-z0-9])[A-Z]{1,2}\d{7}(?![A-Za-z0-9])"),
    "address": re.compile(
        r"(?i:\b(?:địa\s*chỉ|dia\s*chi|address)\s*[:=]\s*)[^\n;]+"
    ),
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in PII_PATTERNS.items():
        safe = pattern.sub(f"[REDACTED_{name.upper()}]", safe)
    return safe


def scrub_value(value: Any) -> Any:
    """Return a copy of a JSON-like value with PII removed from keys and values."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, int) and not isinstance(value, bool):
        text = str(value)
        safe = scrub_text(text)
        return safe if safe != text else value
    if isinstance(value, dict):
        return {
            scrub_text(key) if isinstance(key, str) else key: scrub_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_value(item) for item in value)
    return value


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
