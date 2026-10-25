"""
CI workflow shape (approved 2026-10-23). The workflow lives in `.github/workflows/pr-ci.yml`;
until the user moves it there it is parked in `setup/github-workflows/pr-ci.yml`.
"""

from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).parents[1]
CANDIDATES = (
    ROOT / ".github" / "workflows" / "pr-ci.yml",
    ROOT / "setup" / "github-workflows" / "pr-ci.yml",
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    path = next((p for p in CANDIDATES if p.is_file()), None)
    if path is None:  # pragma: no cover - repository layout broken
        pytest.fail("pr-ci.yml not found in .github/workflows or setup/github-workflows")
    return yaml.safe_load(path.read_text("utf-8"))


def _run_text(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _commands(job: dict) -> list[str]:
    lines = [line.strip() for line in _run_text(job).splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def test_unit_job_runs_only_unit_tests(workflow):
    commands = _commands(workflow["jobs"]["lint-test"])
    assert 'uv run pytest -m "not integration"' in commands
    assert not any(re.search(r"pytest\s+-m\s+integration\b", c) for c in commands)


def test_db_migrations_job_never_runs_integration_tests(workflow):
    commands = _commands(workflow["jobs"]["db-migrations"])
    assert not any("pytest" in c for c in commands)


def test_db_migrations_keeps_upgrade_check_downgrade_upgrade(workflow):
    alembic = [
        c for c in _commands(workflow["jobs"]["db-migrations"]) if c.startswith("uv run alembic")
    ]
    assert alembic == [
        "uv run alembic upgrade head",
        "uv run alembic check",
        "uv run alembic downgrade base",
        "uv run alembic upgrade head",
    ]


def test_ci_uses_its_own_throwaway_database(workflow):
    commands = "\n".join(_commands(workflow["jobs"]["db-migrations"]))
    assert "CREATE DATABASE sav_ci" in commands
    assert "@localhost:1433/sav_ci?" in commands
    assert "sav_uat" not in commands  # never the real UAT database name
    assert workflow["jobs"]["db-migrations"]["env"]["IAM_MIGRATIONS_ENABLED"] == "true"
