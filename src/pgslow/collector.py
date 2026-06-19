"""Read pg_stat_statements for the connected database.

Degrades gracefully: if the extension is not installed or not preloaded, raise a
``PgslowError`` explaining how to enable it instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from pgslow.connection import PgslowError

ENABLE_HELP = (
    "pg_stat_statements is not available on this database.\n\n"
    "To enable it:\n"
    "  1. Add to postgresql.conf:  shared_preload_libraries = 'pg_stat_statements'\n"
    "  2. Restart PostgreSQL (this setting needs a restart).\n"
    "  3. Connect to the target database and run:\n"
    "       CREATE EXTENSION pg_stat_statements;\n"
)

# Scope to the current database; other DBs' stats are noise here.
_STATS_QUERY = """
SELECT
    s.queryid,
    s.query,
    s.calls,
    s.total_exec_time,
    s.mean_exec_time,
    s.stddev_exec_time,
    s.min_exec_time,
    s.max_exec_time,
    s.rows,
    s.shared_blks_hit,
    s.shared_blks_read,
    s.shared_blks_written,
    s.temp_blks_read,
    s.temp_blks_written
FROM pg_stat_statements s
WHERE s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
"""


@dataclass(frozen=True)
class QueryStat:
    """One raw row from pg_stat_statements (current database only)."""

    queryid: int | None
    query: str
    calls: int
    total_exec_time: float
    mean_exec_time: float
    stddev_exec_time: float
    min_exec_time: float
    max_exec_time: float
    rows: int
    shared_blks_hit: int
    shared_blks_read: int
    shared_blks_written: int
    temp_blks_read: int
    temp_blks_written: int


def collect(conn: psycopg.Connection) -> list[QueryStat]:
    """Return all pg_stat_statements rows for the current database.

    Raises ``PgslowError`` (with enable instructions) if the extension is
    missing or not preloaded.
    """
    if not _extension_installed(conn):
        raise PgslowError(ENABLE_HELP)

    try:
        with conn.cursor() as cur:
            cur.execute(_STATS_QUERY)
            columns = [c.name for c in cur.description]
            return [
                QueryStat(**dict(zip(columns, row, strict=True)))
                for row in cur.fetchall()
            ]
    except psycopg.Error as exc:
        # Extension row exists but the library was never preloaded, or the view
        # is otherwise unusable. Translate to the same friendly guidance.
        raise PgslowError(f"{ENABLE_HELP}\n(database said: {_first_line(exc)})") from exc


def _extension_installed(conn: psycopg.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'"
    ).fetchone()
    return row is not None


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__
