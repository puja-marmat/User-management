"""
Phase 1 guard (00a §0.1): no path may run Alembic online / change a schema unless
IAM_MIGRATIONS_ENABLED=true. Each execution path is tested separately.
"""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.core.config import Settings, validate_phase1_config, validate_production_config


ROOT = Path(__file__).resolve().parent.parent
# Unreachable on purpose: if a guard ever failed, nothing real could be touched.
DUMMY_URL = "mssql+aioodbc://guard:guard@127.0.0.1:1/guard_db?driver=No+Such+Driver"


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "IAM_"))}
    env.update({"DB_WRITER_URL": DUMMY_URL, "DB_MIGRATION_URL": DUMMY_URL})
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _alembic(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(**env),
        timeout=120,
        check=False,
    )


# ── 1. Alembic (env.py) ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "args",
    [
        ("upgrade", "head"),
        ("downgrade", "base"),
        ("stamp", "head"),
        ("current",),
        ("check",),
    ],
)
def test_online_alembic_commands_refused_by_default(args):
    r = _alembic(*args)
    assert r.returncode != 0
    assert "Refusing to run an online Alembic command" in (r.stdout + r.stderr)


@pytest.mark.parametrize("flag", ["false", "0", "no", ""])
def test_online_alembic_refused_for_false_values(flag):
    r = _alembic("upgrade", "head", IAM_MIGRATIONS_ENABLED=flag)
    assert "Refusing to run an online Alembic command" in (r.stdout + r.stderr)


def test_offline_sql_render_still_allowed():
    r = _alembic("upgrade", "head", "--sql")
    assert r.returncode == 0, r.stderr
    assert "CREATE SCHEMA [iam]" in r.stdout


def test_guard_lifts_only_with_explicit_flag():
    # Gets past the guard and then fails on the unreachable dummy server.
    r = _alembic("current", IAM_MIGRATIONS_ENABLED="true")
    assert "Refusing to run an online Alembic command" not in (r.stdout + r.stderr)
    assert r.returncode != 0


# ── 2. Container entrypoint ──────────────────────────────────────────────────
needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")


def _entrypoint(tmp_path: Path, mode: str, **env: str) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake = fake_bin / "alembic"
    fake.write_text('#!/bin/sh\necho ALEMBIC-CALLED "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    e = _env(**env)
    e["PATH"] = f"{fake_bin}{os.pathsep}{e.get('PATH', '')}"
    return subprocess.run(  # noqa: S603
        ["sh", str(ROOT / "scripts" / "entrypoint.sh"), mode],  # noqa: S607
        capture_output=True,
        text=True,
        env=e,
        timeout=30,
        check=False,
    )


@needs_sh
def test_entrypoint_migrate_refused(tmp_path):
    r = _entrypoint(tmp_path, "migrate")
    assert r.returncode == 78
    assert "migrate refused" in r.stderr
    assert "ALEMBIC-CALLED" not in r.stdout


@needs_sh
@pytest.mark.parametrize("flag", ["true", "TRUE", "1", "yes"])
def test_entrypoint_migrate_runs_only_with_flag(tmp_path, flag):
    r = _entrypoint(tmp_path, "migrate", IAM_MIGRATIONS_ENABLED=flag)
    assert r.returncode == 0
    assert "ALEMBIC-CALLED upgrade head" in r.stdout


@needs_sh
def test_entrypoint_migrate_sql_allowed(tmp_path):
    r = _entrypoint(tmp_path, "migrate-sql")
    assert r.returncode == 0
    assert "ALEMBIC-CALLED upgrade head --sql" in r.stdout


# ── 3. Pre-commit / CI helper ────────────────────────────────────────────────
def _load_check_script():
    spec = importlib.util.spec_from_file_location(
        "check_migrations", ROOT / "scripts" / "check_migrations.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_check_script_never_goes_online_without_flag(monkeypatch, capsys):
    mod = _load_check_script()
    monkeypatch.setenv("DB_WRITER_URL", DUMMY_URL)
    monkeypatch.delenv("IAM_MIGRATIONS_ENABLED", raising=False)

    def boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("alembic check must not run in Phase 1")

    monkeypatch.setattr(mod.subprocess, "call", boom)
    monkeypatch.setattr(mod, "ROOT", ROOT)
    assert mod.main() == 0
    assert "Phase 1 guard" in capsys.readouterr().out


# ── 4. Deployment workflow ───────────────────────────────────────────────────
def _workflow(name: str) -> str:
    for folder in (ROOT / ".github" / "workflows", ROOT / "setup" / "github-workflows"):
        if (folder / name).exists():
            return (folder / name).read_text(encoding="utf-8")
    pytest.skip(f"{name} not present")
    return ""


def test_deploy_runs_migrate_only_when_enabled():
    text = _workflow("deploy-ecs.yml")
    step = text.split("- name: Run migrations", 1)[1].split("- name:", 1)[0]
    assert "if: ${{ vars.IAM_MIGRATIONS_ENABLED == 'true' }}" in step
    assert "IAM_MIGRATIONS_ENABLED" in step  # container override passes the flag


# ── 5. Application start-up ──────────────────────────────────────────────────
def test_api_startup_never_imports_alembic():
    code = (
        "import sys\n"
        "from fastapi.testclient import TestClient\n"
        "from app.main import create_app\n"
        "with TestClient(create_app()) as c:\n"
        "    c.get('/health')\n"
        "print('ALEMBIC_LOADED=' + str('alembic' in sys.modules))\n"
    )
    r = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=_env(ENVIRONMENT="test", MASTERDB_MODE="off"),
        timeout=60,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "ALEMBIC_LOADED=False" in r.stdout


def test_production_config_rejects_migrations_flag():
    s = Settings(
        _env_file=None, ENVIRONMENT="prod", DB_WRITER_URL=DUMMY_URL, IAM_MIGRATIONS_ENABLED=True
    )
    with pytest.raises(RuntimeError, match="IAM_MIGRATIONS_ENABLED"):
        validate_production_config(s)


def test_masterdb_live_mode_is_refused_at_startup():
    with pytest.raises(RuntimeError, match="MASTERDB_MODE=live"):
        validate_phase1_config(Settings(_env_file=None, MASTERDB_MODE="live"))
    validate_phase1_config(Settings(_env_file=None, MASTERDB_MODE="file"))
