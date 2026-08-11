from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Each request gets a fresh context so values cannot leak between
        # requests handled by the same worker.
        clear_contextvars()

        incoming_id = request.headers.get("x-request-id", "").strip()
        correlation_id = incoming_id or f"req-{uuid.uuid4().hex[:8]}"
        bind_contextvars(correlation_id=correlation_id)
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = correlation_id
            response.headers["x-response-time-ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
            return response
        finally:
            clear_contextvars()
