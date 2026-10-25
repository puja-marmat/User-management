"""Security response headers (same set as ems-mdp-backend), pure ASGI."""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings


_DOCS_CSP = (
    "default-src 'none'; "
    "script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src https://fastapi.tiangolo.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)
_API_CSP = "default-src 'none'; frame-ancestors 'none'"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        path: str = scope.get("path", "")
        is_docs = path.rstrip("/") in ("/docs", "/redoc") or path.startswith("/docs/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"permissions-policy": b"geolocation=(), camera=(), microphone=(), payment=()",
                    b"cross-origin-opener-policy": b"same-origin",
                    b"cross-origin-resource-policy": b"same-origin",
                    b"content-security-policy": (_DOCS_CSP if is_docs else _API_CSP).encode(),
                    b"x-service-version": settings.APP_VERSION.encode(),
                }
                if settings.ENVIRONMENT in ("uat", "prod"):
                    extra[b"strict-transport-security"] = b"max-age=31536000; includeSubDomains"
                headers.extend(extra.items())
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
