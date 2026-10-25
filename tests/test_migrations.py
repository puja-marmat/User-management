"""Alembic safety rules (plan §4.2) — no database needed."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, Table


ROOT = Path(__file__).resolve().parent.parent


def _load_env_hooks():
    """Import include_name/include_object from alembic/env.py without running it."""
    src = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    head = src.split("config = context.config", 1)[0]
    ns: dict = {}
    exec(compile(head, "env_head", "exec"), ns)  # noqa: S102
    tail = src.split("def include_name", 1)[1].split("def _configure", 1)[0]
    exec(compile("def include_name" + tail, "env_hooks", "exec"), ns)  # noqa: S102
    return ns


def test_single_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0001"]


def test_only_iam_schema_is_reflected_or_compared():
    ns = _load_env_hooks()
    assert ns["include_name"]("iam", "schema", {}) is True
    assert ns["include_name"]("dbo", "schema", {}) is False
    assert ns["include_name"](None, "schema", {}) is False

    md = MetaData()
    iam_t = Table("Users", md, Column("Id", Integer), schema="iam")
    dbo_t = Table("ApplicationUsers", md, Column("Id", Integer), schema="dbo")
    ver_t = Table("alembic_version", md, Column("v", Integer), schema="iam")
    inc = ns["include_object"]
    assert inc(iam_t, "Users", "table", False, None) is True
    assert inc(dbo_t, "ApplicationUsers", "table", True, None) is False
    assert inc(ver_t, "alembic_version", "table", True, None) is False


def test_offline_sql_creates_schema_and_iam_version_table(tmp_path):
    # Inherit the real environment. A stripped environment (formerly PATH only and
    # SYSTEMROOT="") breaks Python on Windows: without SystemRoot, Winsock cannot load
    # its providers (WinError 10106) when alembic/env.py imports asyncio/SQLAlchemy.
    # DB_* / IAM_* are removed so the test never depends on a local .env or flag;
    # offline mode opens no connection anyway.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "IAM_"))}
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"alembic --sql failed:\n{result.stderr[-3000:]}"
    out = result.stdout
    assert "CREATE SCHEMA [iam]" in out
    assert "CREATE TABLE iam.alembic_version" in out
    assert "dbo." not in out.replace("AUTHORIZATION dbo", "")


def test_models_metadata_is_iam_only():
    from app.models import LegacyBase, target_metadata

    assert target_metadata.schema == "iam"
    assert LegacyBase.metadata is not target_metadata
    assert importlib.util.find_spec("app.models.base") is not None
