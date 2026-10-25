# UAT procedure: P1-M2 login and own-account APIs (A1-A10)

| | |
|---|---|
| Scope | `POST /auth/login`, `/auth/refresh-token`, `/auth/logout`, `GET/PUT /auth/me`, `/auth/change-password`, `/auth/forgot-password`, `/auth/verify-otp`, `/auth/reset-password`, `GET /auth/password-policy` (01d §2.1) |
| Database | `sav_uat` only. Writes: `ApplicationUsers`, `LogUserLogins`, `AlertQueues`. No DDL. |
| Test data | **One synthetic user created by you in UAT cp-web.** Never a real customer or staff account. |
| Secrets | The synthetic password is typed by you into PowerShell (hidden input) or Swagger. It is never written in this repo, in chat, in a ticket or in a log. Tokens and OTPs: same rule. |
| Status | Code done. Unit tests pass in the Claude sandbox **and on the Windows PC (2026-10-23, see §8)**. **P1-M2 is not complete until §2 (integration on `sav_uat`) and steps 1-10 pass.** |

## Known limitations (approved 2026-10-23, review before go-live)

1. **One API instance.** Refresh-token sessions live in the API's memory (no new tables in
   Phase 1). Run a single instance; a restart signs everyone out.
2. **"Remember me" off = browser-session login**, enforced by the client: the React app must
   keep the refresh token in `sessionStorage` when `rememberMe` is `false` (it then dies with
   the tab). The server gives both kinds the legacy 14-day sliding lifetime.
3. **Every login attempt renews the SecurityStamp** (legacy, even with a wrong password). A
   login in the new API signs the same user out of UAT cp-web within 30 minutes, and a cp-web
   login ends the new API session at its next refresh. Expected during the parallel run.
4. No OTP attempt limit and no lockout counting (legacy; parked as IMP-01 in 01c).
5. Two-factor users (`TwoFactorEnabled` with a confirmed phone/e-mail) get
   `TWO_FACTOR_NOT_SUPPORTED`.

## 0. Prerequisites

1. In **UAT cp-web**, create the synthetic user: enabled, member of a normal admin role group
   (not end user, not site admin), assigned to at least one site, with a test mobile number
   and e-mail. For the forgot-password steps the account's e-mail must be confirmed
   (`EmailConfirmed = 1`; cp-web shows "Account Email is not verified." otherwise).
2. Note the user name. Keep the password to yourself.
3. `.env` (you edit it; never paste it): `ENVIRONMENT=local`, `DB_WRITER_URL` for `sav_uat`,
   `ALERT_FROM_ADDRESS` = the UAT value of `CustomerSupportEmail`. With `ENVIRONMENT=local`
   the signing keys may stay empty (generated at start-up). For any other environment set
   `JWT_PRIVATE_KEY_PEM` and `OTP_SIGNING_KEY`; this appends new random keys to `.env`
   without showing them: `uv run python scripts/generate_auth_keys.py`.

## 1. Unit tests and checks

Since 2026-10-23 (approved change) the default `uv run pytest` is **unit tests only**: the `integration` marker is deselected in `pyproject.toml`, so no database connection is opened even when `.env` has a URL. Integration tests run only with `-m integration` (§2) and stop the whole run unless the database is `sav_uat`.

```powershell
cd "D:\Kimbal Urja\Development\MDM Workspace\EMS 1.0\backend\prime-mdm-backend"
uv sync --dev
uv run pytest                      # expect on Windows: 240 passed, 6 skipped, 9 deselected, coverage >= 70 %
uv run ruff check . ; uv run ruff format --check .
```

## 2. Integration tests on `sav_uat` (synthetic user)

**Do §2a and §2b first** (approve the server, confirm the database name, confirm the synthetic account and the OTP delivery risk) and run §2 only after the review approval, in the small steps of §2c. The `INTEGRATION_APPROVED_SERVER_SHA256` variable from §2a must be set in the same PowerShell window.

```powershell
$env:UAT_TEST_USERNAME = Read-Host "Synthetic user name"
$env:UAT_SYNTHETIC_ACCOUNT_CONFIRM = Read-Host "Type the synthetic user name again"   # must match exactly
$env:UAT_TEST_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR((Read-Host "Password" -AsSecureString)))
$env:UAT_ALLOW_PASSWORD_WRITE = "1"     # re-sets the SAME password via reset and change
uv run pytest -m integration --no-cov -v tests/integration
Remove-Item Env:UAT_TEST_PASSWORD, Env:UAT_ALLOW_PASSWORD_WRITE
```

Expected: `test_auth_uat.py` 5 passed (the reset test skips only if the "Forgot Password OTP"
alert is disabled in UAT, which is itself legacy behaviour), and the P1-M1 schema tests pass.
What they prove: login with the password set in cp-web (PT2, hash compatibility), stamp
renewed, `AccessFailedCount` unchanged on a wrong password, one `LogUserLogins` row per
successful login, the OTP queued but never returned, reset/change producing new v2 hashes
that log in again, and **all other U01 tables unchanged** (checksums before/after).

## 2a. Approve the server and confirm the database target (before §2)

Integration tests read `DB_WRITER_URL` (and `DB_READER_URL`, if set) from `.env`. Before any test
runs, `tests/integration/conftest.py` stops the whole run (exit code 3) unless:

1. **Server:** host and port of **both** URLs match an approved SHA-256 fingerprint in the
   environment variable `INTEGRATION_APPROVED_SERVER_SHA256`. This value is checked **without a
   connection**, is read only from the PowerShell / Windows environment (**never from `.env`**, so the
   file that holds the URL cannot approve itself), and is never stored in the repository. Missing or
   malformed → refused. Host names are not resolved: a DNS alias, an IP address, another port or a
   named instance is a different server and needs its own approval.
2. **Database:** then `SELECT DB_NAME()` on both connections must return `sav_uat`.

Messages never show host names, addresses, ports, users, passwords or URLs (driver errors are
reduced to their type).

**Approve the server once per PowerShell window.** Type the UAT host **you were given for UAT**
(the helper does not read `.env`; `host,port` and `host\instance` are accepted; port defaults to 1433):

```powershell
uv run python -m tests.integration.target_guard          # prints a 64-character fingerprint
$env:INTEGRATION_APPROVED_SERVER_SHA256 = Read-Host "Paste the approved fingerprint"
```

To keep it for later windows (current user only): `[Environment]::SetEnvironmentVariable('INTEGRATION_APPROVED_SERVER_SHA256', $env:INTEGRATION_APPROVED_SERVER_SHA256, 'User')`.
If you ever connect through another name or address, approve it too (comma-separated values).

You can also check the database name yourself **by name only** (prints the database name, nothing
from `.env`; one `SELECT DB_NAME()`):

```powershell
@'
import asyncio
from sqlalchemy import text
from app.core.database import get_db_session, dispose_engines
async def main():
    async with get_db_session(use_reader=True) as s:
        print('Database:', (await s.execute(text('SELECT DB_NAME()'))).scalar())
    await dispose_engines()
asyncio.run(main())
'@ | uv run python -
```

Expected: `Database: sav_uat`. Anything else: stop, do not run §2.

## 2b. Synthetic-account guard and OTP delivery risk (before §2)

**Account guard** (`tests/integration/account_guard.py`). Every test in `test_auth_uat.py`
writes account data (SecurityStamp, `LogUserLogins`, `AlertQueues`, and with
`UAT_ALLOW_PASSWORD_WRITE=1` the password hash). Before the first of them, after the `sav_uat`
guard, the run stops with **exit code 4** unless:

1. `UAT_SYNTHETIC_ACCOUNT_CONFIRM` equals `UAT_TEST_USERNAME` exactly (checked without a connection);
2. exactly **one** account matches the name (case-insensitive, as the login matches it);
3. the account is in **no Super Admin and no System Admin** group;
4. identity and group membership could be read (any error refuses; driver text is suppressed).

Messages never show the user name, ids, e-mail, phone or hashes, and assertions compare hashes
and stamps as booleans. The guard cannot prove the account is synthetic: you confirm that below.

**OTP and alert delivery risk.**

| What can create a message row | When | Recipient |
|---|---|---|
| `POST /auth/forgot-password` | `test_forgot_password_…`, `test_pt2_reset_…`, Swagger step 9 | `ToAddress` = the synthetic user's own phone (SMS alert) or e-mail; never another user [Code `app/services/alert_queue_service.py`] |
| Login with `meterNo` | Swagger step 4 only (the integration tests send no `meterNo`) | same |

The API only **writes** `AlertQueues` rows. Whether a row becomes a real SMS or e-mail depends on
a sender reading `sav_uat`. "No services run against `sav_uat`" is your decision P1-D2 [Req],
not verified evidence, and the Gap Register (G-22) records that UAT service copies may point at
production integrations ("AlertService: unknown").

Establish before §2c steps U5–U7 (each item is evidence you provide; none of it needs this repo):

| # | Check | How (read-only) | Pass when |
|---|---|---|---|
| R1 | The synthetic account's phone is a test number you control | Compare the phone shown in UAT cp-web (user edit screen) with the number of a company test SIM or an agreed dummy number | It is a test number; no customer or staff personal number |
| R2 | The synthetic account's e-mail is a test mailbox you control | Same screen | Company test mailbox or a non-deliverable test domain |
| R3 | No alert sender runs against `sav_uat` | On the UAT application server(s): `Get-Service *Alert*, *BroadcastMessage*, *SendEmail*, *MeterBillEmail* \| Select Name, Status, StartType` (Ops) | Every alert/e-mail service is Stopped (or Disabled), or its configuration targets a database other than `sav_uat` |
| R4 | No production sender reads `sav_uat` | Ops confirms the prod `CrystalPower.AlertService` / broadcast / e-mail services' connection strings target the prod database only (values not shared) | Confirmed |
| R5 | Queue rows in `sav_uat` are not being consumed | After approval, one read-only query: newest `AlertQueues` rows' `IsSent`, `SentOn`, `DeliveryStatusId` (counts only) | Recent rows stay `IsSent = 0`, `SentOn` NULL, `DeliveryStatusId = 101` (Pending) |

If R1–R2 are not met, do not run U5–U7. If R3–R5 cannot be confirmed, run U5–U7 only if a real SMS
or e-mail to the confirmed test recipient is acceptable.

## 2c. Execution order (each step needs separate approval)

| Step | Command (add `--no-cov -v`) | Writes |
|---|---|---|
| U3 | `uv run pytest -m integration tests/integration/test_sqlserver.py tests/integration/test_legacy_schema.py` | none (guard `SELECT DB_NAME()`, schema reads, rolled-back snapshot) |
| U4 | `uv run pytest -m integration tests/integration/test_auth_uat.py -k "pt2_login or wrong_password or me_refresh"` | synthetic account: SecurityStamp ×4, `LogUserLogins` +2 |
| U5 | `… -k forgot_password_queues` | `AlertQueues` +0/1 (OTP to the synthetic account) |
| U6 | `… -k pt2_reset` with `UAT_ALLOW_PASSWORD_WRITE=1` | password hash ×2 (same password), SecurityStamp, `AlertQueues` +1, `LogUserLogins` +2 |
| U7 | Swagger steps 1–10 and the cp-web password check | as §4; steps 8–9 change the password |

## 3. Start the API and open Swagger

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs. `/auth/*` endpoints are listed under **Authentication**.

## 4. Manual checks in Swagger (steps 1-10)

Use `POST /auth/login` → copy `accessToken` → **Authorize** (top right) → paste it.

| # | Step | Expected |
|---|---|---|
| 1 | `GET /auth/password-policy` | 6 chars, symbol, digit, lower, upper |
| 2 | `POST /auth/login` with a wrong password | 401 `INVALID_LOGIN` "Invalid login attempt." |
| 3 | `POST /auth/login` with the right password, `rememberMe: false` | 200; `permissions`, `flags`, `sites`, `currentSiteId`; `rememberMe: false` |
| 4 | Same with `meterNo` = a meter of the user's current site | 200; one new `AlertQueues` row (Login alert) unless the user is an end user/site admin or the site alert is disabled. With an unknown meter: no row. Login works in both cases. |
| 5 | **Authorize**, then `GET /auth/me` | 200, same context. Without the token: 401. |
| 6 | `PUT /auth/me` `{"email": "...", "phoneNumber": "9xxxxxxxxx"}` (test values) | 200; only Email and PhoneNumber change. `"6123456789"` → 422 "Not a valid Phone number". |
| 7 | `POST /auth/refresh-token` with the `refreshToken` | 200 with a **new** refresh token. Send the **old** one again → 401 `REFRESH_TOKEN_REUSED`, and the new one now fails too. Log in again afterwards. |
| 8 | `POST /auth/change-password` (old = current, new = a new synthetic password) | 204. Then log in to **UAT cp-web** with the new password → works (PT2). Your API session ends at its next refresh (cp-web login renewed the stamp). |
| 9 | Forgot password: `POST /auth/forgot-password` `{"userName": ...}` → `challengeId`; read the OTP (section 5); `POST /auth/verify-otp` → `resetTicket`; `POST /auth/reset-password` with ticket + new password | 200 / 200 / 204; log in with the new password. Response bodies never contain the OTP. |
| 10 | F1 negatives: `reset-password` with no ticket, a made-up ticket, the `challengeId` instead of the ticket, the same ticket a second time, or the ticket with another user name; `verify-otp` with a wrong OTP | All 400: "Invalid token." / "Invalid/Expired OTP. Please try again." Password unchanged. |

Finish with `POST /auth/logout` (204; the token stops working) and reset the synthetic
password to the one you keep.

## 5. Reading the OTP (D4, controlled, test only)

No SMS service runs on `sav_uat`, so the OTP sits in `AlertQueues`. Only for the synthetic
user, in SSMS on `sav_uat`, read-only:

```sql
DECLARE @user nvarchar(256) = N'<synthetic user name>';
SELECT TOP 1 q.Id, q.CreatedDate, q.Message
FROM dbo.AlertQueues q
JOIN dbo.Alerts a ON a.Id = q.AlertId
JOIN dbo.ApplicationUsers u ON u.Id = q.CreatedByUserId
WHERE a.Name = N'Forgot Password OTP' AND u.UserName = @user
ORDER BY q.Id DESC;
```

Rules: never for a real user; never copy the OTP into chat, tickets or screenshots; it
expires after 10 minutes and dies on any login or password change of that user.
If no row appears: the "Forgot Password OTP" alert (or its site alert) is disabled, or
`ALERT_FROM_ADDRESS` is empty (the API log shows `alert_not_queued` with the reason).

## 6. Optional: parity against UAT cp-web (PT1)

Run the same login in UAT cp-web and in the new API, each between two snapshots, then compare
(see `docs/PARITY.md`; personal fields and message texts are HMAC-hashed):

```powershell
uv run python -m app.parity snapshot --user-ids <id> --out parity-out/legacy.before.json
#   … log in once in UAT cp-web …
uv run python -m app.parity snapshot --user-ids <id> --baseline parity-out/legacy.before.json --out parity-out/legacy.after.json
uv run python -m app.parity delta parity-out/legacy.before.json parity-out/legacy.after.json --out parity-out/legacy.delta.json
#   … repeat with the new API into new.*.json …
uv run python -m app.parity compare parity-out/legacy.delta.json parity-out/new.delta.json --out parity-out/report.json
```

Expected differences: `WebRequestIdentification` (machine/browser detection) and `IP`
are volatile and ignored.

## 8. Test evidence

| Date / where | Command | Result | Notes |
|---|---|---|---|
| 2026-10-23, Claude sandbox (Linux, no database) | `uv run pytest` | 231 passed, 9 skipped, 0 failed, 0 errors; coverage 97.31 % | Integration tests skipped: no `DB_WRITER_URL` |
| 2026-10-23 16:18 IST, Windows PC | `uv run pytest` | 126 passed, 11 skipped, 0 failed, **103 setup errors** | Environment issue, not code: `WinError 5` on `%TEMP%\pytest-of-<user>` (and `.pytest_cache`) — every error was a `tmp_path` setup; folder ACL not readable by the normal shell. Resolved on the PC before the next run |
| 2026-10-23 16:47 IST, Windows PC (`pytest.xml`, `coverage.xml`) | `uv run pytest` | **240 collected: 229 passed, 11 skipped, 0 failed, 0 errors; coverage 97.83 % (2,074 of 2,120 lines; gate 70 %)** | Skips: 6 POSIX-shell entrypoint tests (no `sh` on Windows), 5 `test_auth_uat` (UAT variables not set). **4 read-only integration tests ran and passed** because `.env` has a database URL and the default command does not exclude the `integration` marker: `test_sqlserver` (probe), `test_legacy_schema` ×3 (17 models match the live columns incl. `Alerts`/`SiteAlerts`, no `iam` schema, parity snapshot rolled back). Database name not yet confirmed in the report (see §2a). Run time 569 s (`test_auth_api` ≈ 3-6 s per test on Windows vs 0.2 s in the sandbox) |
| 2026-10-23, Claude sandbox, after the approved synthetic-account guard | `uv run pytest` / `uv run pytest -m integration --no-cov` | **332 collected, 9 deselected, 323 passed**, 0 failed, coverage 97.31 % / 9 integration tests selected, all skipped (no database here) | 24 new account-guard unit tests; UAT assertions no longer print hashes or stamps. Not yet run on Windows (expected: 317 passed, 6 skipped, 9 deselected). No UAT connection. |
| 2026-10-23, Claude sandbox, after the approved server-fingerprint guard + CI correction | `uv run pytest` / `uv run pytest -m integration --no-cov` | **308 collected, 9 deselected, 299 passed**, 0 failed, coverage 97.31 % / 9 integration tests selected, all skipped (no database here) | 53 new unit tests (server guard, CI shape). Integration tests not run. Windows re-run pending: expect 293 passed, 6 skipped, 9 deselected |
| 2026-10-23, Claude sandbox, after the approved unit-only default + `sav_uat` guard | `uv run pytest` / `uv run pytest -m integration --no-cov` | 255 collected / 9 deselected / **246 passed**, 0 failed, coverage 97.31 % / explicit run: 9 integration tests selected (all skipped here: no database) | 15 new guard tests. Windows re-run pending: expect 240 passed, 6 skipped, 9 deselected |

## 7. Report back

Send: the pytest summary lines of sections 1 and 2 (counts only), and pass/fail per step 1-10.
Do not send tokens, OTPs, passwords or `.env` content.
