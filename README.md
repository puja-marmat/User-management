# prime-mdm-backend

> Renamed from `ems-mdm-backend` on 2026-10-23 (U01 DEC-42). Frontend: `EMS 1.0\frontend\prime-mdm-frontend`.

FastAPI backend for the SAV MDM migration (CrystalPower → EMS 1.0). First feature: **U01 User
Management**, **Phase 1 = lift and shift**: the cp-web User Management re-built in Python + React
with the **same behaviour on the existing tables** of SQL Server `sav_uat` (no new tables, no schema
changes). The `iam` schema design is **Phase 2** (deferred).

Plan: `Migration/02-Migration-Plan/2-MDM-UI-and-Backend/00a-MDM-Backend-API-Project-Plan.md`
(v2.0: §0 = Phase 1). Conventions follow `EMS 1.0/backend/ems-mdp-backend`.

**Status: P1-M2 implemented (2026-10-23), UAT run pending.** P1-M1 (migration guard, legacy
models, MasterDb routing in CSV mode, parity harness) plus the login and own-account APIs
A1-A10 (`/auth/*`, Swagger at `/docs`). P1-M2 is complete only after
[docs/UAT-P1-M2.md](docs/UAT-P1-M2.md) passes on `sav_uat`. Next: P1-M3 after review.

New to Python or this stack? Start with **[docs/LEARNING-GUIDE.md](docs/LEARNING-GUIDE.md)**.

## Stack

Python 3.12 · uv · FastAPI · async SQLAlchemy 2 + `mssql+aioodbc` (ODBC Driver 18) · Pydantic v2 ·
structlog · Alembic · Docker · ruff · pre-commit · pytest.

## Run with Docker (recommended)

```powershell
copy .env.example .env        # then edit DB_WRITER_URL (never commit .env)
docker compose up --build     # API on http://localhost:8000
```

Check:

| URL | Expect |
|---|---|
| http://localhost:8000/health | `{"status":"ok",...}` (no database) |
| http://localhost:8000/health/ready | `status: ready` + SQL Server version, compatibility level, `iamSchemaExists`, `changeTrackingEnabled` |
| http://localhost:8000/docs | OpenAPI UI (disabled when `ENVIRONMENT=prod`) |

`DB_WRITER_URL` format (see `.env.example`):

```
mssql+aioodbc://USER:URL-ENCODED-PASSWORD@HOST:1433/sav_uat?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes
```

- SQL Server on the same PC as Docker: use `host.docker.internal`, not `localhost`.
- Named instance: `HOST%5CINSTANCE` (or the instance's fixed TCP port).
- Building the image installs Microsoft ODBC Driver 18 (accepts Microsoft's EULA).

## Database migrations (Alembic, `iam` only) — **dormant in Phase 1**

> **Phase 1: do not run `migrate`.** It would create schema `iam` and `iam.alembic_version` in
> `sav_uat`, and Phase 1 allows no schema change. `migrate-sql` (prints SQL, no connection) is safe.
> **Guard (P1-M1):** `alembic/env.py` refuses every online command and the container `migrate`
> mode exits with code 78 unless `IAM_MIGRATIONS_ENABLED=true`; the deploy workflow skips the
> migrate step; the pre-commit `alembic check` is skipped. Keep `IAM_MIGRATIONS_ENABLED=false`.

The API **never** migrates at start-up. In Phase 2, migrations run as a separate one-off job:

```powershell
docker compose run --rm migrate-sql   # print the SQL only (review; no connection)
docker compose run --rm migrate       # alembic upgrade head
```

Revision `0001` creates only schema `iam` and table `iam.alembic_version`. Nothing in `dbo`
is created or changed. Before the first run, check the login's rights (read-only):
`scripts/dba/010_check_login_rights.sql`. Rollback of M0 (empty schema only):
`scripts/dba/900_drop_iam_schema.sql`.

## Run without Docker (developers)

Needs Python 3.12, [uv](https://docs.astral.sh/uv/) and Microsoft ODBC Driver 18 for SQL Server.

```powershell
uv sync --dev
uv run pre-commit install
uv run python -m app.entry_server                  # API
uv run pytest                                      # unit tests only (integration deselected, no DB)
uv run pytest -m integration --no-cov              # integration: approved server + DB_NAME() = sav_uat only (docs/UAT-P1-M2.md §2a)
uv run alembic upgrade head --sql                  # render SQL
uv run alembic upgrade head                        # apply
```

## Phase 1 data access (P1-M1)

- **Only `sav_uat`** is connected (U01 DEC-43). No MasterDb / Audit DB connection exists.
- `app/models/legacy/`: models for the 17 existing U01 tables (15 + `Alerts`, `SiteAlerts`
  read-only for P1-M2) (same names and columns as
  `sav_uat`, checked by `tests/test_legacy_models.py` and, against the live database, by
  `tests/integration/test_legacy_schema.py`). India local time (`app/core/legacy_time.py`)
  and app-generated `Guid`s, as legacy does.
- **MasterDb routing** (U01 DEC-44): `app/services/masterdb_routing.py` keeps the legacy
  create/update logic; rows go to `MASTERDB_FILE_PATH` (default `data/masterdb-routing.csv`,
  git-ignored, created on first write; Docker mounts `./data`). CSV: UTF-8 with BOM, header
  `Id,UserName,BaseUrl,PaymentUrl,CreatedAt,UpdatedAt,CreatedByUserId,StatusId`. Open it
  read-only in Excel while the API runs. `MASTERDB_MODE`: `off` | `file` | `live` (live
  stops the app in Phase 1). Fill `MASTERDB_API_BASE_URL`, `MASTERDB_PAYMENT_URL`,
  `PAYU_SITE_IDS` from the UAT cp-web settings (non-secret).
- **Parity harness:** `python -m app.parity snapshot | delta | compare`, see
  [docs/PARITY.md](docs/PARITY.md).

## Authentication (P1-M2, 01d A1-A10)

- `POST /auth/login` → `accessToken` (RS256, 30 min) + `refreshToken` (14 days sliding,
  rotated on every refresh; reuse of an old one ends the session). In Swagger: log in, then
  **Authorize** and paste the access token.
- Same rules as cp-web: Identity v2 password hashes (cp-web keeps accepting passwords set
  here), SecurityStamp renewed on every login attempt, no lockout counting, one
  `LogUserLogins` row per login, Login alert only for a valid `meterNo`.
- Forgot password (F1 fix): `forgot-password` → `challengeId` (OTP only in `AlertQueues`),
  `verify-otp` → `resetTicket`, `reset-password` with that ticket. Both expire after 10 min
  and die on any password change or login of the user.
- **Phase 1 limitation:** sessions are kept in memory → run **one** API instance; a restart
  signs everyone out. Keys: `JWT_PRIVATE_KEY_PEM`, `OTP_SIGNING_KEY` (required outside
  local/test; `uv run python scripts/generate_auth_keys.py` appends new ones to `.env`).
- Writes: `ApplicationUsers`, `LogUserLogins`, `AlertQueues` only.

## Container modes

`scripts/entrypoint.sh`: `api` (default) · `migrate` · `migrate-sql` · `migration-cli …` (M2) ·
`sync` (M7).

## Deploy

GitHub Actions, same pattern as `ems-mdp-backend` (DEC-33): `pr-ci.yml` (pre-commit, tests,
SQL render, migrations against an ephemeral SQL Server, Docker build) and `deploy-ecs.yml`
(OIDC → ECR → one-off `migrate` ECS task → roll the ECS Fargate service). Environment
secrets/vars are listed at the top of `deploy-ecs.yml`.

## Rules

- No secrets in code, docs, logs or chat. `.env` is git-ignored.
- Routers thin; services own SQL and transactions.
- Errors only via `AppBaseError` → `{errorCode, message, errors?}`.
- camelCase JSON, no version prefix, pagination `{data, totalElements, totalPages, page, size}`.
- Never create or alter `dbo` objects (no DDL). Phase 1 writes only the U01 tables listed in 01a §P1, exactly as cp-web does.
