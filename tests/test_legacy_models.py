"""
Legacy U01 models vs the schema contract taken from the `sav_uat` schema script
(`tests/fixtures/legacy_schema_u01.json`). The live database is checked by
`tests/integration/test_legacy_schema.py`.
"""

import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import Integer, SmallInteger, select
from sqlalchemy.dialects import mssql
from sqlalchemy.dialects.mssql import BIT, DATETIME, DECIMAL, NVARCHAR, TINYINT, UNIQUEIDENTIFIER

from app.models import target_metadata
from app.models.base import LegacyBase
from app.models.legacy import U01_LEGACY_MODELS


CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_schema_u01.json").read_text(encoding="utf-8")
)
MODELS = {m.__table__.name: m for m in U01_LEGACY_MODELS}
TYPE_MAP = {
    "int": Integer,
    "smallint": SmallInteger,
    "tinyint": TINYINT,
    "bit": BIT,
    "datetime": DATETIME,
    "uniqueidentifier": UNIQUEIDENTIFIER,
    "nvarchar": NVARCHAR,
    "decimal": DECIMAL,
}


def test_every_contract_table_has_a_model_and_nothing_else():
    assert set(MODELS) == set(CONTRACT["tables"])
    assert len(CONTRACT["tables"]) == 17


@pytest.mark.parametrize("table_name", sorted(CONTRACT["tables"]))
def test_columns_match_contract(table_name):
    table = MODELS[table_name].__table__
    expected = CONTRACT["tables"][table_name]
    assert [c.name for c in table.columns] == [c["name"] for c in expected]
    for spec in expected:
        col = table.c[spec["name"]]
        assert isinstance(col.type, TYPE_MAP[spec["type"]]), spec["name"]
        if spec["type"] == "nvarchar":
            assert col.type.length == (None if spec["length"] == "max" else int(spec["length"]))
        if spec["type"] == "decimal":
            assert (col.type.precision, col.type.scale) == (int(spec["length"]), int(spec["scale"]))
        assert col.nullable == spec["nullable"], spec["name"]
        assert col.server_default is None, "legacy tables have no DB defaults"
        if spec["identity"]:
            assert col.primary_key


def test_legacy_tables_live_in_dbo_and_never_in_alembic_metadata():
    for model in U01_LEGACY_MODELS:
        assert model.__table__.schema == "dbo"
        assert model.__table__.metadata is LegacyBase.metadata
    assert not set(target_metadata.tables) & {
        t.fullname for t in LegacyBase.metadata.tables.values()
    }
    assert target_metadata is not LegacyBase.metadata


def test_guid_is_generated_by_the_application():
    for model in U01_LEGACY_MODELS:
        if "Guid" in model.__table__.c:
            default = model.__table__.c["Guid"].default
            assert default is not None and default.is_callable
            assert isinstance(default.arg(None), uuid.UUID)


def test_models_compile_to_plain_selects_for_sql_server():
    for model in U01_LEGACY_MODELS:
        sql = str(select(model).limit(1).compile(dialect=mssql.dialect()))
        assert sql.startswith("SELECT")
        assert f"dbo.[{model.__table__.name}]" in sql or f"dbo.{model.__table__.name}" in sql


def test_integration_type_mapper_covers_every_model_column():
    # Guards the live-schema test against a mapping gap like the SmallInteger KeyError.
    from tests.integration.test_legacy_schema import sql_server_type

    for model in U01_LEGACY_MODELS:
        expected = {c["name"]: c["type"] for c in CONTRACT["tables"][model.__table__.name]}
        for col in model.__table__.columns:
            assert sql_server_type(col) == expected[col.name], (model.__name__, col.name)
