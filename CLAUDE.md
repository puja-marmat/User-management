# CLAUDE.md — prime-mdm-backend

Working rules for AI-assisted changes in this repo.

## Source of truth
- Project plan: `MDM Workspace/Migration/02-Migration-Plan/2-MDM-UI-and-Backend/00a-MDM-Backend-API-Project-Plan.md` (v2.9; §0 = Phase 1 overrides).
- U01 requirement and data model: `01-User-Management-Migration-Plan.md`, `01a-User-Management-Data-Model.md`, `01b-User-Management-Data-Migration-Plan.md`; API contract `01d-User-Management-API-Contract.md`.
- Reference conventions: `EMS 1.0/backend/ems-mdp-backend` (do not copy Cognito code; DEC-23).
- Work milestone by milestone (Phase 1: P1-M1..M7, plan §0.4); each ends with the user's review. No code beyond the current milestone.

## Hard rules
- Never read, print or commit `.env`, connection strings, passwords, keys or tokens.
- **Phase 1 (lift and shift, plan §0):** same behaviour as cp-web on the existing tables; no new tables, columns, indexes or schemas. Write only the U01 tables in 01a §P1, exactly as legacy does; close only the security exceptions in U01 plan P1.5.
- Never create or alter `dbo` objects (no DDL). Alembic manages `iam` only and is **dormant in Phase 1** (never run `migrate`).
- The API never runs migrations at start-up; `migrate` is a separate job.
- Keep all existing data: same user ids; write ASP.NET Identity **v2** password hashes in Phase 1 so cp-web and cp-api keep working.
- Personal data: aggregates only in reports, logs and test output. No real data in fixtures.

## Code conventions
- Python 3.12, uv, ruff (config in `pyproject.toml`), pre-commit must pass.
- Routers thin; services own SQL and transactions; writer vs reader session.
- Errors: subclasses of `AppBaseError` only.
- Schemas: inherit `CamelModel`; lists use `Page[T]`.
- New iam models: subclass `IamBase`, import them in `app/models/__init__.py`, then `alembic revision --autogenerate -m "<slug>"`, review, and give every revision a working `downgrade()`.
- Legacy models (`app/models/legacy/`): subclass `LegacyBase` (never in Alembic); keep them equal to `tests/fixtures/legacy_schema_u01.json` and the live `sav_uat` (integration test). Legacy timestamps = `india_now()`; Guids app-generated.
- Only `sav_uat` is connected (U01 DEC-43). MasterDb goes through `MasterDbRoutingService` (CSV, DEC-44); never add a MasterDb/Audit connection without approval.
- Auth (P1-M2): never log or return passwords, hashes, tokens, OTPs or SecurityStamps; never add a bypass. Sessions are in memory (one instance in Phase 1).
- Tests: unit tests without a DB (API tests use a synthetic SQLite copy of the legacy tables, `tests/auth_support.py`); `@pytest.mark.integration` for SQL Server, deselected by default (`addopts -m "not integration"`), run with `uv run pytest -m integration --no-cov`, and stopped by `tests/integration/conftest.py` unless both URLs match the server fingerprint in the process variable `INTEGRATION_APPROVED_SERVER_SHA256` (never in `.env` or the repo) and `DB_NAME()` is `sav_uat`; `test_auth_uat.py` (writes account data) also needs `UAT_SYNTHETIC_ACCOUNT_CONFIRM` = `UAT_TEST_USERNAME`, exactly one matching account and no Super/System Admin group (`tests/integration/account_guard.py`, fails closed); never assert on hashes/stamps directly; coverage gate 70%.

## Commands
```
uv sync --dev
uv run pre-commit run --all-files
uv run pytest
uv run alembic upgrade head --sql
docker compose up --build
```
