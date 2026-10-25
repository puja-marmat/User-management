"""
Alembic environment — SQL Server, schema `iam` only (plan §4.2-4.3, DEC-25).

Safety rules enforced here:
1. Only the `iam` schema is reflected or compared (`include_name`), so autogenerate can
   never emit DDL for the legacy `dbo` tables.
2. The version table is `iam.alembic_version`.
3. The `iam` schema is created if missing, before the version table (idempotent).
4. Online runs take an exclusive application lock, so two `migrate` jobs can never run
   at the same time.

URL: DB_MIGRATION_URL, else DB_WRITER_URL (environment or .env). Never logged.
Offline SQL for review:  alembic upgrade head --sql > release.sql

**Phase 1 guard (00a §0.1, U01 DEC-34):** Alembic is dormant. Every *online* command
(upgrade, downgrade, stamp, current, check, history with DB, …) stops here before any
connection is opened unless IAM_MIGRATIONS_ENABLED=true. Offline `--sql` rendering
(no connection) stays allowed for review.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import IAM_SCHEMA, target_metadata


VERSION_TABLE = "alembic_version"
APP_LOCK = "prime-mdm-backend:alembic"
APP_LOCK_TIMEOUT_MS = 60_000
OFFLINE_URL = "mssql+pyodbc://"  # dialect only; no connection in --sql mode

ENSURE_SCHEMA_SQL = (
    f"IF SCHEMA_ID(N'{IAM_SCHEMA}') IS NULL EXEC(N'CREATE SCHEMA [{IAM_SCHEMA}] AUTHORIZATION dbo')"
)


class _MigrationSettings(BaseSettings):
    """Minimal settings: only what Alembic needs (does not validate app settings)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    DB_MIGRATION_URL: SecretStr | None = None
    DB_WRITER_URL: SecretStr | None = None
    IAM_MIGRATIONS_ENABLED: bool = False

    @field_validator("DB_MIGRATION_URL", "DB_WRITER_URL", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("IAM_MIGRATIONS_ENABLED", mode="before")
    @classmethod
    def _empty_is_false(cls, v: object) -> object:
        return False if isinstance(v, str) and not v.strip() else v

    def url(self) -> str:
        chosen = self.DB_MIGRATION_URL or self.DB_WRITER_URL
        if chosen is None:
            raise RuntimeError("Set DB_MIGRATION_URL or DB_WRITER_URL (see .env.example)")
        return chosen.get_secret_value()


GUARD_MESSAGE = (
    "Refusing to run an online Alembic command: Phase 1 is a lift and shift with NO schema "
    "changes (U01 plan DEC-34, backend plan 00a §0.1). Alembic is dormant. "
    "Use `alembic upgrade head --sql` to review SQL offline. "
    "Set IAM_MIGRATIONS_ENABLED=true only for an approved Phase 2 run or a CI scratch database."
)


def assert_migrations_enabled(settings: "_MigrationSettings") -> None:
    if not settings.IAM_MIGRATIONS_ENABLED:
        raise SystemExit(GUARD_MESSAGE)


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    if type_ == "schema":
        return name == IAM_SCHEMA
    return True


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    schema = getattr(obj, "schema", None)
    if type_ == "table":
        return schema == IAM_SCHEMA and name != VERSION_TABLE
    return True


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        version_table_schema=IAM_SCHEMA,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=False,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=OFFLINE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.execute(ENSURE_SCHEMA_SQL)
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        rc = connection.execute(
            text(
                "SET NOCOUNT ON; DECLARE @rc int; "
                "EXEC @rc = sp_getapplock @Resource = :res, @LockMode = 'Exclusive', "
                "@LockOwner = 'Transaction', @LockTimeout = :timeout; SELECT @rc;"
            ),
            {"res": APP_LOCK, "timeout": APP_LOCK_TIMEOUT_MS},
        ).scalar()
        if rc is None or rc < 0:
            raise RuntimeError(f"Could not acquire migration lock (sp_getapplock rc={rc})")
        connection.execute(text(ENSURE_SCHEMA_SQL))
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_MigrationSettings().url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    assert_migrations_enabled(_MigrationSettings())
    asyncio.run(run_migrations_online())
