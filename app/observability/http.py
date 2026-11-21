import logging
import time
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("gomate.http")


async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    route = request.scope.get("route")
    logger.info(
        "request id=%s method=%s route=%s status=%s duration_ms=%.1f",
        request.state.request_id,
        request.method,
        getattr(route, "path", "unmatched"),
        response.status_code,
        (time.monotonic() - started) * 1000,
    )
    return response
