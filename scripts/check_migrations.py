"""
Pre-commit / CI guard for Alembic (plan §4.2, §9).

1. Always (no database needed): the revision graph has exactly one head.
2. Only if IAM_MIGRATIONS_ENABLED=true **and** a database URL is configured:
   `alembic check` — fails when the iam models and the latest revision differ.
   Phase 1 (00a §0.1): skipped, because an online Alembic command must never touch
   `sav_uat`; CI runs it against a throw-away SQL Server container.
"""

import os
from pathlib import Path
import subprocess
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parent.parent


def _env_value(key: str) -> str:
    value = os.environ.get(key)
    if value is not None:
        return value.strip()
    env_file = ROOT / ".env"
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


def _migrations_enabled() -> bool:
    return _env_value("IAM_MIGRATIONS_ENABLED").lower() in {"true", "1", "yes", "on"}


def _has_db_url() -> bool:
    keys = ("DB_MIGRATION_URL", "DB_WRITER_URL")
    if any(os.environ.get(k, "").strip() for k in keys):
        return True
    env_file = ROOT / ".env"
    if not env_file.exists():
        return False
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        for k in keys:
            if line.startswith(f"{k}=") and line.split("=", 1)[1].strip():
                return True
    return False


def main() -> int:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    if len(heads) != 1:
        print(f"alembic: expected exactly one head, found {len(heads)}: {heads}")
        return 1
    print(f"alembic: single head {heads[0]}")

    if not _migrations_enabled():
        print("alembic check skipped: Phase 1 guard (IAM_MIGRATIONS_ENABLED is not true)")
        return 0

    if not _has_db_url():
        print("alembic check skipped: no DB URL configured (CI runs it against SQL Server)")
        return 0

    return subprocess.call(["alembic", "check"], cwd=ROOT)  # noqa: S607


if __name__ == "__main__":
    sys.exit(main())
