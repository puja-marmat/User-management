"""
Uvicorn entrypoint for ECS Fargate and local Docker (DEC-27).
This is the only module that imports uvicorn.
"""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),  # noqa: S104 - container listens on all interfaces
        port=int(os.getenv("PORT", "8000")),
        workers=1,  # async handles concurrency; scale with tasks, not workers
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=False,  # RequestContextMiddleware writes the access log
    )


if __name__ == "__main__":
    main()
