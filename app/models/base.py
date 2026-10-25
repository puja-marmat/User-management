"""
SQLAlchemy declarative bases.

- `IamBase`: tables owned by this service in schema `iam` (Alembic-managed).
- `LegacyBase`: models over existing CrystalPower `dbo` tables (`app/models/legacy`). Excluded from Alembic;
  never create or alter these tables (plan §4.1, 01a §4).

A fixed naming convention keeps constraint names stable across autogenerate runs.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


IAM_SCHEMA = "iam"
LEGACY_SCHEMA = "dbo"

NAMING_CONVENTION = {
    "ix": "IX_%(table_name)s_%(column_0_N_name)s",
    "uq": "UQ_%(table_name)s_%(column_0_N_name)s",
    "ck": "CK_%(table_name)s_%(constraint_name)s",
    "fk": "FK_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "PK_%(table_name)s",
}


class IamBase(DeclarativeBase):
    metadata = MetaData(schema=IAM_SCHEMA, naming_convention=NAMING_CONVENTION)


class LegacyBase(DeclarativeBase):
    metadata = MetaData(schema=LEGACY_SCHEMA)


class AuditColumnsMixin:
    """UTC timestamps (datetime2) set by SQL Server. **Phase 2 `iam` tables only** —
    legacy tables use India local time (`app.core.legacy_time`)."""

    created_at_utc: Mapped[datetime] = mapped_column(
        "CreatedAtUtc", DateTime(), server_default=func.sysutcdatetime(), nullable=False
    )
    updated_at_utc: Mapped[datetime] = mapped_column(
        "UpdatedAtUtc",
        DateTime(),
        server_default=func.sysutcdatetime(),
        onupdate=func.sysutcdatetime(),
        nullable=False,
    )
