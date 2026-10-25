"""
Request context: X-Request-Id propagation, duration header and one access-log line per
request. Pure ASGI (no BaseHTTPMiddleware) so streaming and background tasks are safe.
"""

import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send
import structlog


_SAFE_ID = re.compile(r"^[A-Za-z0-9\-_.]{8,64}$")
log = structlog.get_logger("http")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else str(uuid.uuid4())
        start = time.perf_counter()
        status_holder = {"code": 500}

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
                duration_ms = int((time.perf_counter() - start) * 1000)
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-duration-ms", str(duration_ms).encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            code = status_holder["code"]
            path = scope.get("path", "")
            if not path.startswith("/health"):
                level = "error" if code >= 500 else "warning" if code >= 400 else "info"
                getattr(log, level)(
                    "request",
                    method=scope.get("method"),
                    path=path,  # path only; query strings may carry personal data
                    status=code,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
            structlog.contextvars.clear_contextvars()
