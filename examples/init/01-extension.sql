-- Runs automatically on first container boot (docker-entrypoint-initdb.d).
-- Enables pg_stat_statements in the demo database. Idempotent.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
