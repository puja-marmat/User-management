# Prime MDM backend — one image for: api | migrate | migrate-sql | migration-cli | sync
# (plan §8, DEC-30). Building this image installs Microsoft ODBC Driver 18 for SQL Server,
# which requires accepting Microsoft's EULA (ACCEPT_EULA=Y below).

# --- Stage 1: dependencies -----------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

# --- Stage 2: runtime ----------------------------------------------------------------
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.description="Prime MDM Backend API"

# Microsoft ODBC Driver 18 + unixODBC (needed by pyodbc / aioodbc)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
      -o /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && apt-get purge -y --auto-remove curl gnupg \
 && rm -rf /var/lib/apt/lists/*

ARG APP_VERSION=0.1.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=$APP_VERSION \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd -g 10001 appgroup \
 && useradd -u 10001 -g appgroup -s /sbin/nologin -d /app appuser \
 && mkdir -p /app/data && chown 10001:10001 /app/data

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 alembic ./alembic
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 scripts/entrypoint.sh ./scripts/entrypoint.sh

USER 10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)" || exit 1

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["api"]
