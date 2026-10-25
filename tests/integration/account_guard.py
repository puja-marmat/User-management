"""
Synthetic-account guard for UAT tests that write account data (approved 2026-10-23).

Every test in `test_auth_uat.py` writes for the account named in `UAT_TEST_USERNAME`
(SecurityStamp, `LogUserLogins`, `AlertQueues`, and with `UAT_ALLOW_PASSWORD_WRITE=1` the
password hash). Before the first such test, `enforce_synthetic_account()` stops the whole run
(exit code 4) unless all of this holds:

1. **Confirmation (no connection):** `UAT_SYNTHETIC_ACCOUNT_CONFIRM` is set and equals
   `UAT_TEST_USERNAME` exactly. A typo in either stops the run.
2. **Identity (read-only `SELECT`):** exactly **one** `ApplicationUsers` row matches the name
   the way the login does (`UPPER(UserName)`); none or several (legacy has case-insensitive
   duplicates) → refused.
3. **Privilege (read-only `SELECT`):** none of the account's role groups has `IsSuperAdmin`
   or `IsSystemAdmin`.
4. **Fail closed:** any error while reading identity or group membership → refused.

Messages never contain the user name, ids, e-mail, phone, hashes or driver error text.
These checks cannot prove the account is synthetic; the person running the tests confirms
that (docs/UAT-P1-M2.md §2b).
"""

from collections.abc import Mapping
from dataclasses import dataclass


USERNAME_ENV = "UAT_TEST_USERNAME"
CONFIRM_ENV = "UAT_SYNTHETIC_ACCOUNT_CONFIRM"
EXIT_CODE = 4


class UnsafeAccountError(RuntimeError):
    """The account is not a confirmed, unambiguous, non-privileged synthetic account."""


@dataclass(frozen=True)
class AccountFacts:
    matching_users: int
    super_admin_groups: int
    system_admin_groups: int


def check_confirmation(environ: Mapping[str, str]) -> str:
    """Return the user name when the confirmation matches; raise otherwise. No connection."""
    user = environ.get(USERNAME_ENV) or ""
    confirm = environ.get(CONFIRM_ENV) or ""
    if not user.strip():
        raise UnsafeAccountError(f"UAT tests refused: {USERNAME_ENV} is not set.")
    if not confirm.strip():
        raise UnsafeAccountError(
            f"UAT tests refused: {CONFIRM_ENV} is not set (type the synthetic user name again)."
        )
    if confirm != user:
        raise UnsafeAccountError(
            f"UAT tests refused: {CONFIRM_ENV} does not match {USERNAME_ENV} exactly."
        )
    return user


def check_account_facts(facts: AccountFacts) -> None:
    if facts.matching_users == 0:
        raise UnsafeAccountError("UAT tests refused: no account matches the synthetic user name.")
    if facts.matching_users > 1:
        raise UnsafeAccountError(
            "UAT tests refused: more than one account matches the synthetic user name "
            "(case-insensitive duplicates); use a unique synthetic account."
        )
    if facts.super_admin_groups or facts.system_admin_groups:
        raise UnsafeAccountError(
            "UAT tests refused: the account belongs to a Super Admin or System Admin group; "
            "use a normal synthetic account."
        )


async def read_account_facts(user_name: str) -> AccountFacts:
    """Read-only counts for the account (no personal data selected)."""
    from sqlalchemy import text

    from app.core.database import dispose_engines, get_db_session

    try:
        async with get_db_session(use_reader=True) as session:
            try:
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT "
                                "(SELECT COUNT(*) FROM dbo.ApplicationUsers u "
                                " WHERE UPPER(u.UserName) = UPPER(:u)) AS matching_users, "
                                "(SELECT COUNT(*) FROM dbo.ApplicationUsers u "
                                " JOIN dbo.ApplicationUsersInGroups ug ON ug.ApplicationUserId = u.Id "
                                " JOIN dbo.ApplicationRoleGroups g ON g.Id = ug.ApplicationRoleGroupId "
                                " WHERE UPPER(u.UserName) = UPPER(:u) AND g.IsSuperAdmin = 1) "
                                " AS super_admin_groups, "
                                "(SELECT COUNT(*) FROM dbo.ApplicationUsers u "
                                " JOIN dbo.ApplicationUsersInGroups ug ON ug.ApplicationUserId = u.Id "
                                " JOIN dbo.ApplicationRoleGroups g ON g.Id = ug.ApplicationRoleGroupId "
                                " WHERE UPPER(u.UserName) = UPPER(:u) AND g.IsSystemAdmin = 1) "
                                " AS system_admin_groups"
                            ),
                            {"u": user_name},
                        )
                    )
                    .mappings()
                    .one()
                )
            finally:
                await session.rollback()
    finally:
        await dispose_engines()
    return AccountFacts(
        matching_users=int(row["matching_users"]),
        super_admin_groups=int(row["super_admin_groups"]),
        system_admin_groups=int(row["system_admin_groups"]),
    )


def enforce_synthetic_account(environ: Mapping[str, str]) -> None:
    """Stop the pytest run (exit code 4) unless the synthetic account is safe to write."""
    import asyncio

    import pytest

    try:
        user = check_confirmation(environ)
        try:
            facts = asyncio.run(read_account_facts(user))
        except Exception as exc:  # fail closed; driver text can hold names
            raise UnsafeAccountError(
                "UAT tests refused: account identity or group membership could not be "
                f"verified ({type(exc).__name__}; details suppressed)."
            ) from None
        check_account_facts(facts)
    except UnsafeAccountError as exc:
        pytest.exit(str(exc), returncode=EXIT_CODE)
