# prime-mdm-backend: Learning Guide

This guide is for someone new to Python and to this repo's tools. For each technology it gives
the **high-level points** to learn, **where the repo uses it**, a **small example** and
**official links**. It covers the concepts you need for this project, not everything about each tool.

> **Phase 1 note (2026-10-23).** Phase 1 is a lift and shift on the **existing** `dbo` tables (no `iam`
> schema, no new tables). Read the `iam`/Alembic/Change Tracking parts as Phase 2 background; in Phase 1
> Alembic is installed but not run, and passwords stay in the ASP.NET Identity v2 format (§13).

Suggested approach: follow the [learning path](#0-learning-path-about-3-weeks) in order. After
each topic, open the repo files listed under "In this repo" and read them with the guide open.

---

## Contents

0. [Learning path](#0-learning-path-about-3-weeks)
1. [The big picture: how the pieces fit](#1-the-big-picture)
2. [Python (the language)](#2-python)
3. [uv (Python, packages, virtual environment)](#3-uv)
4. [FastAPI (the web API)](#4-fastapi)
5. [Pydantic and pydantic-settings (data shapes, configuration)](#5-pydantic-and-pydantic-settings)
6. [SQL Server, ODBC, SQLAlchemy (database access)](#6-sql-server-odbc-sqlalchemy)
7. [Alembic (database migrations)](#7-alembic)
8. [pytest (tests)](#8-pytest)
9. [ruff and pre-commit (code quality)](#9-ruff-and-pre-commit)
10. [Docker and Docker Compose (containers)](#10-docker-and-docker-compose)
11. [Git, GitHub Actions, AWS ECR and ECS (delivery)](#11-git-github-actions-aws)
12. [structlog (logging)](#12-structlog)
13. [Coming in M5–M6: authentication and authorisation](#13-coming-in-m5m6-authentication-and-authorisation)
14. [Walkthrough: one request through the code](#14-walkthrough-one-request-through-the-code)
15. [Daily commands cheat sheet](#15-daily-commands-cheat-sheet)
16. [Python ↔ .NET mapping](#16-python--net-mapping)
17. [Glossary](#17-glossary)

---

## 0. Learning path (about 3 weeks)

| Week | Learn | Practise in this repo |
|---|---|---|
| 1 (days 1–3) | Python basics (§2): types, functions, classes, modules, `async`/`await`, exceptions | Read `app/core/exceptions.py`, `app/core/config.py` |
| 1 (days 4–5) | uv (§3), VS Code setup, Git basics | `uv sync --dev`, `uv run pytest` |
| 2 (days 1–2) | FastAPI (§4) + Pydantic (§5) | Read `app/main.py`, `app/routers/health.py`, `app/schemas/common.py`; add a small test endpoint locally |
| 2 (days 3–5) | SQL Server via SQLAlchemy (§6) + Alembic (§7) | Read `app/core/database.py`, `app/services/health_service.py`, `alembic/env.py`; run `alembic upgrade head --sql` |
| 3 (days 1–2) | pytest (§8), ruff + pre-commit (§9) | Read `tests/test_health.py`; write one new test; run pre-commit |
| 3 (days 3–4) | Docker + Compose (§10) | `docker compose up --build`, call `/health/ready` |
| 3 (day 5) | CI/CD (§11), logging (§12), auth concepts (§13) | Read the `.github/workflows/*.yml` files |

You don't need everything before you start. With §2–§5 and §14 you can already follow most of the code.

### Set up your PC (Windows)

1. **Python 3.12**: install from python.org or let uv install it (§3).
2. **uv**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
3. **Git for Windows**.
4. **VS Code** with extensions: *Python* (Microsoft), *Pylance*, *Ruff* (Astral), *Docker*, *SQL Server (mssql)*.
   In VS Code choose the interpreter `.venv\Scripts\python.exe` (Ctrl+Shift+P → "Python: Select Interpreter").
5. **Microsoft ODBC Driver 18 for SQL Server**: needed only if you run the API without Docker.
6. **Docker Desktop**: uses WSL 2 on Windows.

---

## 1. The big picture

```
 Browser / React frontend / Mobile app
            │  HTTPS + JSON
            ▼
 ┌─────────────────────────── Docker container ───────────────────────────┐
 │ uvicorn  (web server: receives HTTP)                                   │
 │   └─ FastAPI app  (app/main.py)                                        │
 │        ├─ middleware      request id, security headers, CORS           │
 │        ├─ routers         URL → function   (app/routers/*.py)          │
 │        ├─ schemas         JSON shapes      (Pydantic, app/schemas)     │
 │        ├─ services        business logic + SQL (app/services)          │
 │        └─ models          tables as classes (SQLAlchemy, app/models)   │
 │   SQLAlchemy ─ aioodbc ─ pyodbc ─ Microsoft ODBC Driver 18             │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    ▼
                SQL Server  sav_uat:  schema iam (new, ours)  +  dbo (legacy, read-only for us)

 Alembic  = versioned changes to the iam schema (run as a separate "migrate" job)
 pytest   = tests;  ruff = lint/format;  pre-commit = runs checks before each git commit
 GitHub Actions = CI (checks on every PR) + CD (build image → ECR → ECS Fargate)
```

The layers and their rules:

- **Router**: thin. It reads the request, calls a service and returns a schema.
- **Service**: does the real work. It owns the SQL and the transactions.
- **Schema**: the JSON contract with the frontend (camelCase).
- **Model**: a Python class that maps to a database table.

---

## 2. Python

**High-level points**

- **Indentation is syntax.** Blocks are defined by 4-space indentation, not `{}`.
- **Dynamic, but typed by hint.** `def f(x: int) -> str:` documents the types; tools check them
  (Pylance, ruff), but Python itself doesn't enforce them at runtime. Pydantic *does* enforce them (§5).
- **Core types:** `str`, `int`, `float`, `bool`, `None`, `list[int]`, `dict[str, int]`, `tuple`,
  `set`. Optional values are written `str | None`.
- **Functions, classes and dataclasses**: `@dataclass(frozen=True)` is a quick immutable record
  (used in `health_service.py`).
- **Modules and packages:** each `.py` file is a module; a folder with `__init__.py` is a
  package. `from app.core.config import get_settings` imports from `app/core/config.py`.
- **Exceptions:** `raise ConflictError("...")`, `try: ... except SomeError as exc: ...`.
  Our API turns `AppBaseError` subclasses into JSON errors (§4).
- **Decorators:** `@something` above a function wraps it. Examples: `@router.get("/health")`
  (registers a route) and `@lru_cache` (caches the result, used for settings and engines).
- **Context managers:** `with ...:` / `async with ...:` open and always close a resource (a DB session, a file).
- **async / await:** the API is asynchronous. A function defined with `async def` must be called
  with `await`. While one request waits for SQL Server, the server handles other requests.
  Rule: inside `async def`, never call slow *blocking* code (e.g. `time.sleep`, sync DB drivers).
- **f-strings:** `f"user {user_id}"`. Never build SQL with f-strings from user input; use bound parameters (§6).
- **Generators / `yield`:** used by FastAPI dependencies to hand over a DB session and clean up afterwards.
- **Generics (3.12):** `class Page[T]` means "a page of T" (see `app/schemas/common.py`).

**Small example**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    id: int
    name: str
    distributor_id: int | None = None


async def load_site(site_id: int) -> Site:
    # pretend this awaits the database
    return Site(id=site_id, name="Tower A")
```

**In this repo:** `app/core/exceptions.py` (classes, inheritance), `app/core/config.py`
(class attributes, properties, decorators), `app/services/health_service.py` (async, dataclass).

**Learn:** [Python tutorial](https://docs.python.org/3/tutorial/) (chapters 3–9),
[asyncio basics](https://docs.python.org/3/library/asyncio-task.html),
[typing cheat sheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html).

---

## 3. uv

**What it is:** one fast tool that installs Python, creates the project's **virtual environment**
(`.venv`, a private set of packages for this repo) and installs the **dependencies** listed in
`pyproject.toml`, pinned exactly in `uv.lock`.

**High-level points**

- `pyproject.toml` lists the project's dependencies, like a `.csproj`. `uv.lock` pins the exact versions, so every PC, CI run and Docker build uses the same ones. Commit both.
- `uv sync --dev` creates or updates `.venv` from the lock file. The `--dev` flag adds test and lint tools.
- `uv run <command>` runs a command inside `.venv`, so you don't need to activate it.
- `uv add <package>` adds a dependency (it updates `pyproject.toml` and `uv.lock`); `uv add --dev <pkg>` adds a tool.
- `uv lock --check` fails if the lock file doesn't match `pyproject.toml` (a pre-commit hook runs it).
- `.python-version` contains `3.12`, and uv uses that Python version.

```powershell
uv sync --dev
uv run python -c "import fastapi; print(fastapi.__version__)"
uv add httpx          # example: add a dependency
```

**In this repo:** `pyproject.toml` (dependencies, plus pytest/ruff/coverage config), `uv.lock`.

**Learn:** [uv docs: projects](https://docs.astral.sh/uv/guides/projects/).

---

## 4. FastAPI

**What it is:** the web framework. You write functions; FastAPI maps URLs to them, validates
input and output with Pydantic, and generates the OpenAPI document (`/docs`). The frontend
generates its TypeScript types from that document.

**High-level points**

- **App:** `FastAPI(...)` created in `create_app()` (`app/main.py`).
- **Routers:** group endpoints, e.g. `APIRouter(prefix="/health")`, combined in `app/api_router.py`.
  **No version prefix** (`/users`, not `/v1/users`): plan §7.
- **Path operations:** `@router.get("/ready")`, `@router.post(...)` etc.
- **Parameters:** path (`/users/{user_id}`), query (`?page=1`), body (a Pydantic model), headers.
- **Response model:** `response_model=ReadyResponse` filters and documents what is returned.
- **Dependencies (`Depends`):** FastAPI's built-in dependency injection. It gives the function a DB
  session (`Depends(get_reader_db)`), and from M5 also the current user and permission checks.
- **Middleware:** code that runs around every request (request id, security headers, CORS, gzip).
- **Exception handlers:** every error becomes `{"errorCode", "message", "errors"?}`. In services,
  raise our `AppBaseError` subclasses, never raw `HTTPException`.
- **Lifespan:** start-up/shut-down hook (we dispose DB engines on shutdown; we **never** run migrations here).
- **uvicorn** is the server process that runs the app (`app/entry_server.py`).
- **OpenAPI docs:** `/docs` (Swagger UI) is on in local/UAT and off in prod.

**Small example** (the shape of our future endpoints)

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_reader_db
from app.schemas.common import CamelModel

router = APIRouter(prefix="/sites", tags=["sites"])


class SiteOut(CamelModel):
    site_id: int  # JSON: "siteId"
    site_name: str  # JSON: "siteName"


@router.get("/{site_id}", response_model=SiteOut, response_model_by_alias=True)
async def get_site(site_id: int, db: AsyncSession = Depends(get_reader_db)) -> SiteOut:
    return await site_service.get(db, site_id)  # router stays thin
```

**In this repo:** `app/main.py`, `app/api_router.py`, `app/routers/health.py`, `app/middleware/*`.

**Learn:** [FastAPI tutorial](https://fastapi.tiangolo.com/tutorial/): read *First steps*, *Path/Query
parameters*, *Request body*, *Response model*, *Dependencies*, *Handling errors*, *Bigger applications*, *Testing*.

---

## 5. Pydantic and pydantic-settings

**What it is:** a library for data classes that validate their input. In FastAPI they describe request
and response JSON. `pydantic-settings` uses the same idea to read configuration from environment
variables / `.env`.

**High-level points**

- `class X(BaseModel): name: str; age: int`. Bad input raises a validation error, which the API turns into **422** with field details.
- **`CamelModel`** (ours): write `user_name` in Python and it appears as `userName` in JSON (plan §7).
- `model_validate(dict)` builds a model from data; `model_dump(by_alias=True)` turns it into JSON-style data.
- `Field(..., ge=1)` adds constraints; `@field_validator` adds custom checks.
- `from_attributes=True` lets you build a schema directly from a database model object.
- **`Page[T]`** (ours): the single pagination shape `{data, totalElements, totalPages, page, size}`.
- **Settings:** `class Settings(BaseSettings)` reads `DB_WRITER_URL`, `ENVIRONMENT`... from the
  environment or `.env`. `SecretStr` hides values in logs and `repr`. Settings are cached by `get_settings()`.

**In this repo:** `app/schemas/common.py`, `app/core/config.py`, `.env.example`.

**Learn:** [Pydantic concepts: models](https://docs.pydantic.dev/latest/concepts/models/),
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

---

## 6. SQL Server, ODBC, SQLAlchemy

**The chain:** SQLAlchemy (Python ORM/SQL toolkit) → `aioodbc` (async wrapper) → `pyodbc` →
**Microsoft ODBC Driver 18** → SQL Server `sav_uat`. The connection is configured with one URL:

```
mssql+aioodbc://USER:PASSWORD@HOST:1433/sav_uat?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes
```

**High-level points (SQL Server side)**

- **Schemas** group tables: `dbo` = legacy CrystalPower tables (we only read them), `iam` = our new tables (DEC-18/20).
- **Change Tracking** (M1/M7): SQL Server records *which rows changed* in tracked tables; our sync
  worker reads those changes to keep `iam` in step with legacy writes (DEC-19).
- Data types we use: `int`/`bigint` with `IDENTITY` (auto numbers), `nvarchar` (Unicode text), `datetime2` (store UTC with `SYSUTCDATETIME()`), `bit` (bool).
- `sp_getapplock` = a named lock. We use it so that two migration jobs never run at once.

**High-level points (SQLAlchemy 2.0)**

- **Engine** = the connection pool (one per URL), created once (`app/core/database.py`).
- **Session** = one unit of work: run queries, then `commit()` or `rollback()`.
  A route gets one via `Depends(get_writer_db)` (for writes) or `get_reader_db` (for reads).
- **Models (ORM):** a class per table.

  ```python
  class User(IamBase):
      __tablename__ = "Users"  # → iam.Users
      id: Mapped[int] = mapped_column("Id", primary_key=True)
      user_name: Mapped[str] = mapped_column("UserName", String(256), unique=True)
  ```

  `IamBase` = tables in `iam` (managed by Alembic). `LegacyBase` = read-only models over `dbo` (never migrated).
- **Querying (2.0 style):**

  ```python
  from sqlalchemy import select

  stmt = select(User).where(User.user_name == name)  # parameters are bound safely
  user = (await db.execute(stmt)).scalar_one_or_none()
  ```

- **Raw SQL** when needed: `text("SELECT ... WHERE x = :x")` with parameters. **Never** use f-strings with user input (SQL injection).
- **Transactions:** `async with db.begin(): ...` commits at the end or rolls back on error. Services decide the transaction boundaries.
- **Async:** always `await db.execute(...)`.

**In this repo:** `app/core/database.py`, `app/models/base.py`, `app/services/health_service.py`.

**Learn:** [SQLAlchemy 2.0 Unified Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/) (core and ORM),
[asyncio extension](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html),
[SQL Server dialect](https://docs.sqlalchemy.org/en/20/dialects/mssql.html),
[Change Tracking](https://learn.microsoft.com/sql/relational-databases/track-changes/about-change-tracking-sql-server).

---

## 7. Alembic

**What it is:** version control for the database schema, comparable to EF migrations. Each
change is a Python file in `alembic/versions/` with `upgrade()` and `downgrade()`.
The current version is stored in **`iam.alembic_version`**.

**High-level points**

- **Revision chain:** `0001` → `0002` → … Each revision names the previous one (`down_revision`). There must be exactly **one head**; a hook checks this.
- **Autogenerate:** after changing models, `alembic revision --autogenerate -m "add users"`
  compares the models with the database and writes a draft. **Always review it**; it can miss or misread things.
- **Our safety rules** (`alembic/env.py`):
  - Only the `iam` schema is ever compared or changed; `dbo` can't be touched.
  - The `iam` schema is created if it's missing.
  - A lock (`sp_getapplock`) prevents two migration jobs from running at the same time.
- **Schema and reference data only.** User data migration is a separate CLI tool (M2–M4), not Alembic.
- **Deployment:** a one-off `migrate` container runs `alembic upgrade head` *before* the new API
  version starts. The API never migrates at start-up (this avoids the legacy EF6 auto-migration problem).
- **Review SQL without a database:** `alembic upgrade head --sql` prints the T-SQL.

```powershell
uv run alembic current                       # which version is the DB on
uv run alembic upgrade head --sql            # show SQL, change nothing
uv run alembic upgrade head                  # apply
uv run alembic downgrade -1                  # undo the last revision
uv run alembic revision --autogenerate -m "add users table"
uv run alembic check                         # fails if models and migrations differ
```

**In this repo:** `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_baseline.py`, `scripts/check_migrations.py`.

**Learn:** [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html).

---

## 8. pytest

**High-level points**

- Test files are named `tests/test_*.py`, and test functions are named `test_*`. Plain `assert x == y` is all you need.
- **Fixtures** provide shared setup and are passed in as arguments. Examples: `client` (an HTTP test client) and `app` (in `tests/conftest.py`).
- **Async tests:** just write `async def test_...`; this is configured with `asyncio_mode = "auto"`.
- **Faking the DB:** unit tests replace the DB dependency with a fake
  (`app.dependency_overrides[get_reader_db] = ...`), so they run without SQL Server.
- **Markers:** `@pytest.mark.integration` marks tests that need a real SQL Server. Skip them with `-m "not integration"`.
- **monkeypatch:** temporarily changes env vars or attributes for one test.
- **Coverage:** reports which lines the tests ran. The build fails below 70% (DEC-29).
- Use only synthetic data in tests, never real users.

```powershell
uv run pytest                                  # all unit tests + coverage (no database)
uv run pytest tests/test_health.py -v          # one file
uv run pytest -k ready                         # tests whose name contains "ready"
uv run pytest -m integration --no-cov          # sav_uat only (guard: approved server + DB_NAME())
```

**In this repo:** `tests/conftest.py`, `tests/test_health.py` (fakes the DB), `tests/test_app.py` (error shapes).

**Learn:** [pytest getting started](https://docs.pytest.org/en/stable/getting-started.html),
[fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html),
[FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).

---

## 9. ruff and pre-commit

**ruff** is the linter (it finds bugs, security issues and unused imports) and the formatter (it applies one code style).
The rules are in `pyproject.toml` under `[tool.ruff]` and are the same set as ems-mdp-backend.

```powershell
uv run ruff check .          # find problems
uv run ruff check --fix .    # fix the safe ones automatically
uv run ruff format .         # format all files
```

If ruff reports a rule code you don't know (e.g. `S608`), search "ruff S608" to see what it means and how to fix it.

**pre-commit** runs checks automatically on every `git commit`. If a check fails, the commit stops and
you fix the problem (or re-stage files that ruff fixed). Our hooks:

- whitespace and line-ending fixes;
- YAML/TOML checks;
- **private-key detection**;
- ruff lint and ruff format;
- `uv lock --check`;
- the Alembic single-head check, plus `alembic check` when a DB URL is set;
- GitHub workflow validation.

```powershell
uv run pre-commit install              # once per clone
uv run pre-commit run --all-files      # run everything manually
```

**In VS Code:** with the Ruff extension, set "Format on Save" to see the same results as you type.

**Learn:** [ruff](https://docs.astral.sh/ruff/), [pre-commit](https://pre-commit.com/).

---

## 10. Docker and Docker Compose

**High-level points**

- An **image** is a packaged app: an OS layer, Python, the ODBC driver, our code and its dependencies. It's built from the `Dockerfile`.
- A **container** is a running image. It runs the same way on your PC, in CI and on AWS.
- Our `Dockerfile` is **multi-stage**: stage 1 installs dependencies with uv, and stage 2 is a small runtime with the
  ODBC driver, running as a non-root user (UID 10001). It also has a health check on `/health`.
- **One image, several modes** (`scripts/entrypoint.sh`): `api` (default), `migrate`, `migrate-sql`,
  later `migration-cli` and `sync`.
- **Docker Compose** (`docker-compose.yml`) runs containers locally with settings from `.env`:
  - `api`: the API on port 8000.
  - `migrate` and `migrate-sql`: run on demand.
  - `mssql`: an optional local SQL Server for experiments with fake data.
- Inside a container, `localhost` means the container itself. To reach SQL Server on your PC, use `host.docker.internal`.

```powershell
docker compose up --build                 # build + start API (Ctrl+C to stop)
docker compose up -d --build              # same, in background
docker compose logs -f api                # follow logs
docker compose run --rm migrate-sql       # show migration SQL
docker compose run --rm migrate           # apply migrations
docker compose down                       # stop and remove containers
```

**Learn:** [Docker get started](https://docs.docker.com/get-started/),
[Compose overview](https://docs.docker.com/compose/).

---

## 11. Git, GitHub Actions, AWS

**Git basics you'll use:** `git clone`, `git checkout -b feature/x`, `git add`, `git commit`, `git push`,
then a pull request on GitHub. Branch flow as in EMS: `UAT` → `main` → `production`.
`.env` is git-ignored: never commit it.

**GitHub Actions** (workflow files in `.github/workflows/`):

- `pr-ci.yml` runs on every pull request:
  - pre-commit, the dependency audit and the unit tests;
  - renders the migration SQL;
  - runs the migrations up and down against a throwaway SQL Server;
  - builds the Docker image and smoke-tests it.
- `deploy-ecs.yml` runs on a push to `UAT` or `production`:
  1. Logs in to AWS with **OIDC** (no stored AWS keys).
  2. Builds the image and pushes it to **ECR** (AWS's image registry).
  3. Runs `migrate` as a one-off **ECS** task and stops if it fails.
  4. Rolls the **ECS Fargate** service (AWS runs our containers without servers to manage).
- Secrets live in GitHub environment secrets or AWS Secrets Manager, never in the workflow files.

**Learn:** [Git handbook](https://docs.github.com/get-started/using-git/about-git),
[GitHub Actions quickstart](https://docs.github.com/actions/writing-workflows/quickstart),
[Amazon ECS on Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html).

---

## 12. structlog

**High-level points**

- Logs are **structured JSON**, one event per line with fields, e.g.
  `{"message":"request","method":"GET","path":"/health/ready","status":200,"duration_ms":12,"request_id":"..."}`.
- `log = structlog.get_logger(__name__)`, then `log.info("user_created", user_id=42)`. Pass data as fields; don't paste values into the message text.
- Every log line carries the `request_id` (also returned in the `X-Request-Id` header), so one request can be traced end to end.
- **Never log** passwords, hashes, tokens, connection strings or personal data. Log ids and counts only.

**In this repo:** `app/telemetry/logging.py`, `app/middleware/request_context.py`.
**Learn:** [structlog getting started](https://www.structlog.org/en/stable/getting-started.html).

---

## 13. Coming in M5–M6: authentication and authorisation

You don't need these for M0–M4. Read the concepts before M5.

| Concept | Meaning here | Library |
|---|---|---|
| Password hashing | Passwords are stored only as slow, salted hashes. New hashes use **Argon2id** | `pwdlib` |
| ASP.NET Identity hashes | The 78,828 existing users have .NET Identity v2 hashes (PBKDF2-SHA1). We verify them with a small in-house checker and upgrade to Argon2id on login, so users keep their passwords | Python `hashlib` (built in) |
| JWT access token | A signed token sent as `Authorization: Bearer <token>`; contains user id, tier, scope and permissions; expires after a short time | `PyJWT` |
| Refresh token | Long-lived, stored as a hash in `iam`; used to get a new access token; can be revoked | in-house |
| TOTP / OTP | Codes from an authenticator app (multi-factor), and one-time codes for password reset | `pyotp` |
| Lockout | Account is locked after N failed logins | in-house |
| Authorisation | Tier (SuperAdmin … End Customer) + role template + per-user permission ticks, limited to the user's distributors/sites | in-house resolver, FastAPI `Depends` guards |

**Learn:** [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[JWT introduction](https://jwt.io/introduction), [PyJWT](https://pyjwt.readthedocs.io/),
[pyotp](https://pyauth.github.io/pyotp/), [pwdlib](https://frankie567.github.io/pwdlib/).

---

## 14. Walkthrough: one request through the code

`GET http://localhost:8000/health/ready`

1. **uvicorn** (`app/entry_server.py`) receives the HTTP request and hands it to the FastAPI `app` (`app/main.py`).
2. **Middleware** runs, outermost first:
   - `RequestContextMiddleware` sets the request id and starts the timer.
   - CORS runs next.
   - `SecurityHeadersMiddleware` adds the security headers on the way out.
3. **Routing:** `app/api_router.py` includes `health.router` (prefix `/health`), and `/ready` maps to `ready()` in `app/routers/health.py`.
4. **Dependency:** `db: AsyncSession = Depends(get_reader_db)` opens a session from the pool (`app/core/database.py`). The engine is created on first use from `DB_WRITER_URL`.
5. **Service:** `probe_database(db)` (`app/services/health_service.py`) runs one read-only T-SQL query with a 5-second timeout.
6. **Response:** the router builds `ReadyResponse` (a Pydantic model). FastAPI serialises it to camelCase JSON.
7. **Errors:** if the DB is unreachable, the router raises `ServiceUnavailableError`. The handler in `main.py` returns
   `503 {"errorCode":"DB_UNAVAILABLE","message":"Database not reachable"}` and logs only the exception type, never the driver text.
8. **After the response:** the session closes (the `yield` in the dependency ends), the middleware adds `X-Request-Id` and `X-Duration-Ms`, and one JSON log line is written.

Exercise: follow these steps in the files with a debugger. In VS Code, add a breakpoint in `ready()` and run
"Python: FastAPI" with module `uvicorn`, args `app.main:app --reload`.

---

## 15. Daily commands cheat sheet

```powershell
# once
uv sync --dev
uv run pre-commit install
copy .env.example .env            # then edit; never commit

# run
uv run python -m app.entry_server                 # API without Docker (needs ODBC Driver 18)
uv run uvicorn app.main:app --reload              # API with auto-reload while coding
docker compose up --build                         # API in Docker

# check
uv run ruff check --fix . ; uv run ruff format .
uv run pytest
uv run pre-commit run --all-files

# database (iam only)
uv run alembic upgrade head --sql                 # preview
uv run alembic upgrade head                       # apply
uv run alembic revision --autogenerate -m "..."   # new migration (review it!)
```

---

## 16. Python ↔ .NET mapping

| .NET (CrystalPower) | Python (this repo) |
|---|---|
| `.csproj` + NuGet | `pyproject.toml` + `uv.lock` (uv) |
| ASP.NET MVC / Web API controller | FastAPI router (`app/routers`) |
| Model binding + DataAnnotations | Pydantic models (`app/schemas`) |
| Dependency injection (`IServiceCollection`) | FastAPI `Depends(...)` |
| Middleware / `DelegatingHandler` | ASGI middleware (`app/middleware`) |
| Entity Framework `DbContext` | SQLAlchemy `AsyncSession` |
| EF entity classes | SQLAlchemy models (`app/models`) |
| EF Migrations (`Add-Migration`, `Update-Database`) | Alembic (`revision --autogenerate`, `upgrade head`) |
| `web.config` / `appsettings.json` | `.env` + `pydantic-settings` (`app/core/config.py`) |
| `async Task<T>` / `await` | `async def ... -> T` / `await` |
| ASP.NET Identity `PasswordHasher` | `pwdlib` (Argon2id) + in-house Identity v2/v3 verifier |
| OWIN OAuth bearer tokens | PyJWT access tokens + refresh tokens in `iam` |
| `[Authorize(Roles=...)]` | `Depends(require_permission(...))` guards (M6) |
| xUnit / NUnit | pytest |
| StyleCop / Roslyn analyzers | ruff |
| IIS / Kestrel | uvicorn in Docker on ECS Fargate |

---

## 17. Glossary

| Term | Meaning |
|---|---|
| ASGI | Python's standard interface between async web servers (uvicorn) and apps (FastAPI) |
| Virtual environment (`.venv`) | Private folder of packages for one project |
| Dependency (FastAPI) | A function whose result FastAPI injects into an endpoint |
| ORM | Object-relational mapping: tables as classes |
| Session | One unit of work with the database (one transaction scope) |
| Migration / revision | One versioned schema change (Alembic file) |
| Head | The latest Alembic revision |
| Lint | Automatic code checks for bugs and style |
| Image / container | Packaged app / a running copy of it |
| CI / CD | Continuous Integration (checks on every change) / Continuous Delivery (automatic deploy) |
| OIDC | Lets GitHub Actions log in to AWS without stored keys |
| JWT | Signed JSON token proving who the caller is |
| Change Tracking | SQL Server feature that records which rows changed (used for the legacy → iam sync) |
| `iam` / `dbo` | Our new schema / the legacy CrystalPower schema |
