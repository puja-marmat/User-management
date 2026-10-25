"""
Read-only checks against `sav_uat` (marker: integration). Needs DB_WRITER_URL in .env.

    uv run pytest -m integration --no-cov

Only SELECTs on INFORMATION_SCHEMA / sys views and the parity snapshot (rolled back).
"""

import pytest
from sqlalchemy import Integer, SmallInteger, text
from sqlalchemy.dialects import mssql

from app.core.config import get_settings
from app.models.legacy import U01_LEGACY_MODELS
from app.parity.snapshot import Selection, take_snapshot


pytestmark = pytest.mark.integration


def sql_server_type(column) -> str:
    """INFORMATION_SCHEMA.DATA_TYPE expected for a model column."""
    t = column.type
    if isinstance(t, mssql.TINYINT):
        return "tinyint"
    if isinstance(t, SmallInteger):
        return "smallint"
    if isinstance(t, Integer):
        return "int"
    if isinstance(t, mssql.BIT):
        return "bit"
    if isinstance(t, mssql.DATETIME):
        return "datetime"
    if isinstance(t, mssql.UNIQUEIDENTIFIER):
        return "uniqueidentifier"
    if isinstance(t, mssql.NVARCHAR):
        return "nvarchar"
    if isinstance(t, mssql.DECIMAL):
        return "decimal"
    return f"<unmapped {type(t).__name__}>"


@pytest.fixture
def require_db():
    if get_settings().DB_WRITER_URL is None:
        pytest.skip("DB_WRITER_URL not configured")


async def _rows(sql: str, **params):
    from app.core.database import get_db_session

    async with get_db_session(use_reader=True) as session:
        try:
            return (await session.execute(text(sql), params)).mappings().all()
        finally:
            await session.rollback()


async def test_models_match_live_sav_uat_columns(require_db):
    from app.core.database import dispose_engines

    try:
        live = await _rows(
            """
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH,
                   NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo'
            """
        )
    finally:
        await dispose_engines()
    by_table: dict[str, dict[str, dict]] = {}
    for r in live:
        by_table.setdefault(r["TABLE_NAME"], {})[r["COLUMN_NAME"]] = dict(r)
    problems = []
    for model in U01_LEGACY_MODELS:
        name = model.__table__.name
        cols = by_table.get(name)
        if cols is None:
            problems.append(f"{name}: table missing")
            continue
        model_cols = {c.name for c in model.__table__.columns}
        if model_cols != set(cols):
            problems.append(f"{name}: columns differ {sorted(model_cols ^ set(cols))}")
            continue
        for c in model.__table__.columns:
            db = cols[c.name]
            expected = sql_server_type(c)
            if expected != db["DATA_TYPE"]:
                problems.append(f"{name}.{c.name}: model {expected}, db {db['DATA_TYPE']}")
            if expected == "decimal" and (c.type.precision, c.type.scale) != (
                db["NUMERIC_PRECISION"],
                db["NUMERIC_SCALE"],
            ):
                problems.append(f"{name}.{c.name}: decimal precision/scale")
            if c.nullable != (db["IS_NULLABLE"] == "YES"):
                problems.append(f"{name}.{c.name}: nullability")
            length = getattr(c.type, "length", None)
            if db["DATA_TYPE"] == "nvarchar" and (length or -1) != db["CHARACTER_MAXIMUM_LENGTH"]:
                problems.append(f"{name}.{c.name}: length {db['CHARACTER_MAXIMUM_LENGTH']}")
    assert not problems, problems


async def test_no_schema_was_added_by_phase_1(require_db):
    from app.core.database import dispose_engines

    try:
        rows = await _rows("SELECT SCHEMA_ID('iam') AS iam_id")
    finally:
        await dispose_engines()
    assert rows[0]["iam_id"] is None, "schema iam exists: Phase 1 must not create it"


async def test_parity_snapshot_is_read_only_and_works(require_db, monkeypatch):
    from app.core.database import dispose_engines, get_db_session

    try:
        async with get_db_session(use_reader=True) as session:
            snap = await take_snapshot(
                session, Selection(user_ids=(-1,), site_ids=(-1,)), b"it-key"
            )
    finally:
        await dispose_engines()
    assert snap["tables"]["ApplicationUsers"]["rows"] == {}
    assert snap["tables"]["AlertQueues"]["maxId"] >= 0
