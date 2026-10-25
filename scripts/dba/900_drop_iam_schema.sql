-- MANUAL ROLLBACK ONLY. Drops schema iam if, and only if, it holds nothing except
-- iam.alembic_version. Refuses otherwise. Never run against production without sign-off.
SET XACT_ABORT ON;
BEGIN TRAN;
IF SCHEMA_ID(N'iam') IS NULL
BEGIN
    PRINT 'iam schema does not exist - nothing to do';
    ROLLBACK; RETURN;
END;
IF EXISTS (SELECT 1 FROM sys.objects WHERE schema_id = SCHEMA_ID(N'iam') AND name <> N'alembic_version' AND parent_object_id = 0)
BEGIN
    RAISERROR('iam contains objects other than alembic_version - refusing to drop', 16, 1);
    ROLLBACK; RETURN;
END;
IF OBJECT_ID(N'iam.alembic_version', N'U') IS NOT NULL DROP TABLE iam.alembic_version;
DROP SCHEMA iam;
COMMIT;
