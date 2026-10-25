"""Baseline: iam schema and iam.alembic_version only.

The `iam` schema itself is ensured by alembic/env.py before the version table is
created (idempotent). This revision intentionally creates no tables; the iam model
tables arrive in M1 (0002+), Change Tracking in M1 as well.

Downgrade does not drop the schema: removing `iam` is a manual, reviewed DBA action
(scripts/dba/900_drop_iam_schema.sql), never an automatic one.

Revision ID: 0001
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence


revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
