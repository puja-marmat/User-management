"""Database readiness probe (owns the SQL; router stays thin)."""

import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.base import IAM_SCHEMA


_READY_SQL = text(
    """
    SELECT
        DB_NAME()                                                    AS database_name,
        CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128))      AS product_version,
        CAST(SERVERPROPERTY('ProductMajorVersion') AS nvarchar(16))  AS major_version,
        CAST(SERVERPROPERTY('Edition') AS nvarchar(128))             AS edition,
        (SELECT compatibility_level FROM sys.databases WHERE name = DB_NAME())
                                                                     AS compatibility_level,
        CASE WHEN SCHEMA_ID(:iam_schema) IS NULL THEN 0 ELSE 1 END   AS iam_schema_exists,
        CASE WHEN EXISTS (SELECT 1 FROM sys.change_tracking_databases
                          WHERE database_id = DB_ID()) THEN 1 ELSE 0 END
                                                                     AS change_tracking_enabled
    """
)


@dataclass(frozen=True)
class DatabaseStatus:
    database_name: str
    product_version: str
    major_version: str
    edition: str
    compatibility_level: int | None
    iam_schema_exists: bool
    change_tracking_enabled: bool


async def probe_database(session: AsyncSession) -> DatabaseStatus:
    settings = get_settings()
    result = await asyncio.wait_for(
        session.execute(_READY_SQL, {"iam_schema": IAM_SCHEMA}),
        timeout=settings.DB_HEALTH_TIMEOUT_SECONDS,
    )
    row = result.mappings().one()
    return DatabaseStatus(
        database_name=row["database_name"],
        product_version=row["product_version"],
        major_version=row["major_version"],
        edition=row["edition"],
        compatibility_level=row["compatibility_level"],
        iam_schema_exists=bool(row["iam_schema_exists"]),
        change_tracking_enabled=bool(row["change_tracking_enabled"]),
    )
