-- Read-only: what can the current login do in this database? Changes nothing.
-- Run as the login used in DB_WRITER_URL / DB_MIGRATION_URL.
SELECT
    DB_NAME()                                                     AS database_name,
    SUSER_SNAME()                                                 AS login_name,
    USER_NAME()                                                   AS database_user,
    IS_ROLEMEMBER(N'db_owner')                                    AS is_db_owner,
    IS_ROLEMEMBER(N'db_ddladmin')                                 AS is_db_ddladmin,
    HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'CREATE SCHEMA')   AS can_create_schema,
    HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'ALTER')           AS can_alter_database,      -- needed to enable Change Tracking (M1)
    HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'VIEW CHANGE TRACKING') AS can_view_change_tracking,
    HAS_PERMS_BY_NAME(N'dbo', N'SCHEMA', N'SELECT')               AS can_read_dbo,
    CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128))       AS product_version,
    (SELECT compatibility_level FROM sys.databases WHERE name = DB_NAME()) AS compatibility_level,
    CASE WHEN SCHEMA_ID(N'iam') IS NULL THEN 0 ELSE 1 END         AS iam_schema_exists;
