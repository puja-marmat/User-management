"""Phase 1 (U01 DEC-43): only `sav_uat` is connected; nothing can reach MasterDb."""

from pathlib import Path
import re

from app.core.config import Settings


APP = Path(__file__).resolve().parent.parent / "app"


def test_no_masterdb_or_audit_connection_setting_exists():
    fields = set(Settings.model_fields)
    assert "DB_MASTERDB_URL" not in fields
    assert not [f for f in fields if "AUDIT" in f]
    assert {f for f in fields if f.endswith("_URL") and f.startswith("DB_")} == {
        "DB_WRITER_URL",
        "DB_READER_URL",
        "DB_MIGRATION_URL",
    }


def test_engines_are_created_in_one_place_only():
    hits = [
        p.relative_to(APP).as_posix()
        for p in APP.rglob("*.py")
        if re.search(r"\b(create_async_engine|create_engine)\(", p.read_text(encoding="utf-8"))
    ]
    assert hits == ["core/database.py"]


def test_app_code_never_names_the_masterdb_database_in_a_connection():
    for p in APP.rglob("*.py"):
        code = "\n".join(
            line
            for line in p.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "Initial Catalog=CystalPowerMasterdb" not in code
        assert "/CystalPowerMasterdb" not in code
