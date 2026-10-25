# U01 parity harness (P1-M1)

Compares what **legacy cp-web (UAT)** and the **new app** write to `sav_uat` for the same
action (U01 plan P1.8, test PT1). It only reads: every query is a `SELECT`, run in a
transaction that is rolled back. Personal fields (names, e-mails, phones, password hashes,
IPs, message text) are replaced by an HMAC, so output files hold no contact data.

> Status: the tool exists and is unit-tested. **No end-to-end parity has been run yet** —
> that needs the write actions of P1-M2 onwards. Use synthetic test users only (P1-D4).

## Setup
`.env`: `DB_WRITER_URL` (sav_uat) and `PARITY_HASH_KEY` (any long random value; use the
same value for every file you want to compare). Output goes where `--out` points; keep it
in `parity-out/` (git-ignored).

## Tables and selection
| Selected by | Tables (current rows) | Tables (new rows since the baseline) |
|---|---|---|
| `--user-ids` | `ApplicationUsers`, `ApplicationUsersInGroups`, `UserSites` | `ApplicationUserChangeLogs`, `LogUserLogins` |
| `--role-group-ids` | `ApplicationRoleGroups`, `ApplicationRolesInGroups` | — |
| `--site-ids` | `GrantApiAccesses` | `HistoricalGrantApiAccesses`, `AlertQueues`*, `BroadcastMessages`* |

\* without `--site-ids`, every new row since the baseline (no services run on `sav_uat`, P1-D2).
A "before" snapshot records only the highest `Id` of the append-only tables; the "after"
snapshot (`--baseline before.json`) reads rows above it. Max 500 rows per table.

## Example: "Add User" (later milestone P1-M4)
```powershell
# Legacy side (UAT cp-web, current site 5)
uv run python -m app.parity snapshot --site-ids 5 --out parity-out/legacy.before.json
#   ... in UAT cp-web: add user pt_legacy_01 (site 5, group 12) and note its Id, e.g. 90001
uv run python -m app.parity snapshot --user-ids 90001 --subject-names pt_legacy_01 --site-ids 5 `
    --role-group-ids 12 --baseline parity-out/legacy.before.json --out parity-out/legacy.after.json
uv run python -m app.parity delta parity-out/legacy.before.json parity-out/legacy.after.json `
    --out parity-out/legacy.delta.json

# New app side: same steps with pt_new_01 → parity-out/new.delta.json

uv run python -m app.parity compare parity-out/legacy.delta.json parity-out/new.delta.json `
    --out parity-out/report.json      # exit code 0 = equal, 1 = differences
```
`compare` ignores volatile columns (Id, Guid, CreatedDate/UpdatedDate, PasswordHash,
SecurityStamp, OTP message text, IP, request id), maps each side's `--user-ids` to
`<USER1..n>` and `--subject-names` to `<SUBJECT1..n>` (before hashing), then reports rows
that exist on only one side.
