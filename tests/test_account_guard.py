"""Synthetic-account guard for the account-writing UAT tests (no database needed)."""

import ast
from pathlib import Path

import pytest

from tests.integration import account_guard
from tests.integration.account_guard import (
    CONFIRM_ENV,
    EXIT_CODE,
    USERNAME_ENV,
    AccountFacts,
    UnsafeAccountError,
    check_account_facts,
    check_confirmation,
    enforce_synthetic_account,
)


NAME = "synthetic.uat.user"
SAFE = AccountFacts(matching_users=1, super_admin_groups=0, system_admin_groups=0)


# ── confirmation (no connection) ────────────────────────────────────────────


def test_matching_confirmation_returns_the_name():
    assert check_confirmation({USERNAME_ENV: NAME, CONFIRM_ENV: NAME}) == NAME


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({}, f"{USERNAME_ENV} is not set"),
        ({USERNAME_ENV: "  "}, f"{USERNAME_ENV} is not set"),
        ({USERNAME_ENV: NAME}, f"{CONFIRM_ENV} is not set"),
        ({USERNAME_ENV: NAME, CONFIRM_ENV: ""}, f"{CONFIRM_ENV} is not set"),
        ({USERNAME_ENV: NAME, CONFIRM_ENV: NAME + "x"}, "does not match"),
        ({USERNAME_ENV: NAME, CONFIRM_ENV: NAME.upper()}, "does not match"),  # exact match
        ({USERNAME_ENV: NAME, CONFIRM_ENV: f" {NAME}"}, "does not match"),
    ],
)
def test_missing_or_different_confirmation_is_refused(env, reason):
    with pytest.raises(UnsafeAccountError, match=reason) as exc:
        check_confirmation(env)
    assert NAME not in str(exc.value)


# ── identity and privilege ──────────────────────────────────────────────────


def test_one_normal_account_passes():
    check_account_facts(SAFE)


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (AccountFacts(0, 0, 0), "no account matches"),
        (AccountFacts(2, 0, 0), "more than one account"),
        (AccountFacts(1, 1, 0), "Super Admin or System Admin"),
        (AccountFacts(1, 0, 1), "Super Admin or System Admin"),
        (AccountFacts(1, 2, 3), "Super Admin or System Admin"),
    ],
)
def test_missing_ambiguous_or_privileged_accounts_are_refused(facts, reason):
    with pytest.raises(UnsafeAccountError, match=reason):
        check_account_facts(facts)


# ── enforce (stops the whole run) ───────────────────────────────────────────


def _env():
    return {USERNAME_ENV: NAME, CONFIRM_ENV: NAME}


def _facts(value):
    async def fake(user_name):
        assert user_name == NAME
        return value

    return fake


def test_enforce_passes_for_a_safe_account(monkeypatch):
    monkeypatch.setattr(account_guard, "read_account_facts", _facts(SAFE))
    enforce_synthetic_account(_env())


@pytest.mark.parametrize(
    "facts",
    [AccountFacts(1, 1, 0), AccountFacts(1, 0, 1), AccountFacts(0, 0, 0), AccountFacts(3, 0, 0)],
)
def test_enforce_stops_the_run_for_unsafe_accounts(monkeypatch, facts):
    monkeypatch.setattr(account_guard, "read_account_facts", _facts(facts))
    with pytest.raises(pytest.exit.Exception) as exc:
        enforce_synthetic_account(_env())
    assert exc.value.returncode == EXIT_CODE
    assert NAME not in str(exc.value)


def test_enforce_refuses_before_any_query_when_confirmation_is_wrong(monkeypatch):
    async def must_not_query(user_name):  # pragma: no cover - would fail the test
        raise AssertionError("queried without a matching confirmation")

    monkeypatch.setattr(account_guard, "read_account_facts", must_not_query)
    with pytest.raises(pytest.exit.Exception, match="does not match") as exc:
        enforce_synthetic_account({USERNAME_ENV: NAME, CONFIRM_ENV: "someone.else"})
    assert exc.value.returncode == EXIT_CODE


def test_enforce_fails_closed_and_hides_driver_details(monkeypatch):
    async def failing(user_name):
        raise RuntimeError(f"Login failed for user '{NAME}' at db.example.test")

    monkeypatch.setattr(account_guard, "read_account_facts", failing)
    with pytest.raises(pytest.exit.Exception) as exc:
        enforce_synthetic_account(_env())
    message = str(exc.value)
    assert exc.value.returncode == EXIT_CODE
    assert "could not be verified" in message and "RuntimeError" in message
    assert NAME not in message and "example.test" not in message


# ── wiring: every account-writing UAT test is covered ───────────────────────


UAT_MODULE = Path(__file__).parent / "integration" / "test_auth_uat.py"


def test_guard_is_a_module_autouse_fixture_in_the_uat_tests():
    source = UAT_MODULE.read_text("utf-8")
    assert '@pytest.fixture(scope="module", autouse=True)' in source
    assert "enforce_synthetic_account(os.environ)" in source


def test_every_uat_test_function_lives_in_the_guarded_module():
    tree = ast.parse(UAT_MODULE.read_text("utf-8"))
    tests = [
        n.name
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name.startswith("test_")
    ]
    assert len(tests) == 5  # all of them write account data; all are module-level
    # no other integration module writes account data
    for other in (Path(__file__).parent / "integration").glob("test_*.py"):
        if other.name == UAT_MODULE.name:
            continue
        text = other.read_text("utf-8").lower()
        assert "/auth/" not in text and "insert " not in text and "update " not in text


def test_failure_messages_never_compare_hashes_or_stamps_directly():
    """An `assert a["PasswordHash"] == b[...]` would print both hashes when it fails."""
    tree = ast.parse(UAT_MODULE.read_text("utf-8"))
    secret_keys = {"PasswordHash", "SecurityStamp"}
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
        and any(
            isinstance(sub, ast.Subscript)
            and isinstance(sub.slice, ast.Constant)
            and sub.slice.value in secret_keys
            for sub in ast.walk(node.test)
        )
    ]
    assert offenders == []
