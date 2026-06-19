"""EXPLAIN a query selected by its pg_stat_statements queryid.

Two honest constraints shape this module:

1. pg_stat_statements stores *normalized* text — literals become ``$1``, ``$2``.
   A parameterized statement can't be planned without values, so for plain
   EXPLAIN we use ``EXPLAIN (GENERIC_PLAN ...)`` (PostgreSQL 16+), which plans
   the parameterized form directly. On older servers we say so instead of
   failing with a raw "there is no parameter $1".

2. EXPLAIN ANALYZE *executes* the query. It therefore needs concrete parameter
   values (which the normalized form lacks) and it must never touch data. We
   refuse ANALYZE for parameterized and for writing statements, and the
   connection is read-only as a backstop.
"""

from __future__ import annotations

import re

import psycopg

from pgslow.connection import PgslowError

_PARAM_RE = re.compile(r"\$\d+")
_LEADING_WORD_RE = re.compile(r"^\s*\(*\s*(\w+)")

# Statements EXPLAIN can plan. Everything else (DO, CREATE, DROP, ALTER, SET,
# ANALYZE, VACUUM, TRUNCATE, ...) is a utility statement with no plan.
_PLANNABLE = {"select", "insert", "update", "delete", "merge", "values", "with", "table"}
_WRITES = {"insert", "update", "delete", "merge"}

# GENERIC_PLAN landed in PostgreSQL 16 (server_version_num >= 160000).
_GENERIC_PLAN_MIN_VERSION = 160000


def get_query_text(conn: psycopg.Connection, queryid: int) -> str:
    """Return the normalized query for a queryid in the current database."""
    row = conn.execute(
        """
        SELECT query
        FROM pg_stat_statements
        WHERE queryid = %s
          AND dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        ORDER BY total_exec_time DESC
        LIMIT 1
        """,
        (queryid,),
    ).fetchone()
    if row is None:
        raise PgslowError(
            f"No query with queryid {queryid} in this database.\n"
            "Run `pgslow top` to see available queryids."
        )
    return row[0]


def server_version_num(conn: psycopg.Connection) -> int:
    """Return server_version_num, e.g. 160004 for PostgreSQL 16.4."""
    return int(conn.execute("SHOW server_version_num").fetchone()[0])


def leading_keyword(query: str) -> str:
    match = _LEADING_WORD_RE.match(query)
    return match.group(1).lower() if match else ""


def is_plannable(query: str) -> bool:
    return leading_keyword(query) in _PLANNABLE


def is_write(query: str) -> bool:
    return leading_keyword(query) in _WRITES


def has_parameters(query: str) -> bool:
    return _PARAM_RE.search(query) is not None


def run_plain_explain(conn: psycopg.Connection, query: str) -> str:
    """Plan a query without executing it.

    Uses GENERIC_PLAN for parameterized statements on PostgreSQL 16+.
    """
    if not is_plannable(query):
        raise PgslowError(
            f"Cannot EXPLAIN a `{leading_keyword(query).upper()}` statement: "
            "it is a utility command with no execution plan."
        )

    use_generic = has_parameters(query)
    if use_generic and server_version_num(conn) < _GENERIC_PLAN_MIN_VERSION:
        raise PgslowError(
            "This query is parameterized ($1, $2, ...) and EXPLAIN needs values.\n"
            "GENERIC_PLAN requires PostgreSQL 16+. On this server, copy the query, "
            "substitute representative values, and run EXPLAIN manually."
        )

    options = "GENERIC_PLAN, FORMAT TEXT" if use_generic else "FORMAT TEXT"
    return _execute_explain(conn, f"EXPLAIN ({options}) {query}")


def ensure_analyzable(query: str) -> None:
    """Raise PgslowError if EXPLAIN ANALYZE can't safely run on this query.

    Checked before prompting, so the user is never asked to confirm something
    that would be refused anyway.
    """
    if not is_plannable(query):
        raise PgslowError(
            f"Cannot EXPLAIN a `{leading_keyword(query).upper()}` statement."
        )
    if is_write(query):
        raise PgslowError(
            f"Refusing EXPLAIN ANALYZE on a `{leading_keyword(query).upper()}` "
            "statement: it would modify data. ANALYZE only runs on read-only queries."
        )
    if has_parameters(query):
        raise PgslowError(
            "This query is parameterized ($1, $2, ...). EXPLAIN ANALYZE must execute "
            "it with real values, which the normalized form does not have.\n"
            "Run plain `pgslow explain` for the generic plan, or substitute values "
            "and run EXPLAIN ANALYZE manually."
        )


def run_analyze_explain(conn: psycopg.Connection, query: str) -> str:
    """Run EXPLAIN ANALYZE — this EXECUTES the query. Caller must have confirmed."""
    ensure_analyzable(query)
    return _execute_explain(conn, f"EXPLAIN (ANALYZE, FORMAT TEXT) {query}")


def _execute_explain(conn: psycopg.Connection, sql: str) -> str:
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return "\n".join(row[0] for row in cur.fetchall())
    except psycopg.errors.SyntaxError as exc:
        # Some normalized text can't be re-parsed, e.g. INTERVAL '90 days'
        # becomes `interval $1`, which is invalid where a typed literal is required.
        raise PgslowError(
            f"Could not plan this query: {_first_line(exc)}\n"
            "The normalized text from pg_stat_statements is not always re-parseable "
            "(e.g. INTERVAL '...' becomes `interval $1`). Copy the query from "
            "`pgslow top`, substitute representative values, and run EXPLAIN manually."
        ) from exc
    except psycopg.Error as exc:
        raise PgslowError(f"EXPLAIN failed: {_first_line(exc)}") from exc


def _first_line(exc: Exception) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__
