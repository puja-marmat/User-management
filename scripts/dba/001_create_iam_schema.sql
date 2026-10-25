-- Create the iam schema (idempotent). Same statement the Alembic env runs.
-- Target: sav_uat. Touches no dbo object.
IF SCHEMA_ID(N'iam') IS NULL
    EXEC(N'CREATE SCHEMA [iam] AUTHORIZATION dbo');
GO
SELECT name, schema_id FROM sys.schemas WHERE name = N'iam';
