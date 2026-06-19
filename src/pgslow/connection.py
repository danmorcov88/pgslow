"""DSN resolution and read-only connections.

The tool is read-only by design. Every connection opens with
``default_transaction_read_only = on`` so a stray write fails loudly at the
database, not just by convention.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


class PgslowError(Exception):
    """User-facing error. The CLI prints the message and exits non-zero."""


def resolve_dsn(dsn: str | None) -> str:
    """Return the connection string from the flag or the environment.

    Order: explicit ``--dsn`` > ``$PGSLOW_DSN`` > ``$DATABASE_URL``.
    """
    candidate = dsn or os.environ.get("PGSLOW_DSN") or os.environ.get("DATABASE_URL")
    if not candidate:
        raise PgslowError(
            "No connection string given.\n"
            "Pass --dsn, or set PGSLOW_DSN or DATABASE_URL.\n"
            "Example: --dsn postgresql://user:pass@host:5432/dbname"
        )
    return candidate


@contextmanager
def connect(dsn: str | None, *, read_only: bool = True) -> Iterator[psycopg.Connection]:
    """Open a connection to the resolved DSN.

    By default the session is read-only, so a stray write fails at the server.
    `reset` is the one command that opens with ``read_only=False``.

    Raises ``PgslowError`` with a friendly message when the database cannot be
    reached, rather than surfacing a raw psycopg traceback.
    """
    conninfo = resolve_dsn(dsn)
    try:
        conn = psycopg.connect(conninfo, autocommit=True, application_name="pgslow")
    except psycopg.OperationalError as exc:
        raise PgslowError(f"Could not connect to PostgreSQL.\n{_clean(exc)}") from exc

    try:
        if read_only:
            conn.execute("SET default_transaction_read_only = on")
        yield conn
    finally:
        conn.close()


def _clean(exc: Exception) -> str:
    """Trim psycopg's multi-line error text to its first meaningful line."""
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__
