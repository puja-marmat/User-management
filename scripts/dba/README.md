# DBA scripts (review copies)

Phase 1 uses **one login** (DEC-32): the `migrate` job (`alembic upgrade head`) creates
the `iam` schema itself. These scripts are the same SQL for review, for a DBA who prefers
to run it by hand, and for the later split into three logins.

| Script | Purpose | When |
|---|---|---|
| `001_create_iam_schema.sql` | Create schema `iam` (idempotent) | Optional; the migrate job does the same |
| `010_check_login_rights.sql` | Read-only check: can the configured login create a schema, enable Change Tracking, read `dbo`? | Before the first `migrate` run |
| `900_drop_iam_schema.sql` | Drop `iam` **only if it is empty** | Manual rollback of M0 only |

Change Tracking scripts arrive with M1. Nothing here touches `dbo` data.
