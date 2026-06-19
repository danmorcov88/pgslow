"""Shared fixtures.

Unit tests (analyzer, explain classification, CLI wiring) need no database.
Integration tests use a live PostgreSQL with pg_stat_statements, reached via the
``PGSLOW_TEST_DSN`` environment variable; without it they are skipped.
"""

from __future__ import annotations

import os

import psycopg
import pytest

# A query with a constant, so pg_stat_statements normalizes it to a stable text.
MARKER_SQL = "SELECT 424242 AS pgslow_marker"
MARKER_TEXT = "pgslow_marker"
MARKER_CALLS = 7


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """DSN of a live PostgreSQL, or skip. Ensures the extension exists."""
    dsn = os.environ.get("PGSLOW_TEST_DSN")
    if not dsn:
        pytest.skip("PGSLOW_TEST_DSN not set; skipping integration tests")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    return dsn


@pytest.fixture
def seeded_dsn(pg_dsn: str) -> str:
    """Reset stats and run a known marker query a fixed number of times."""
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_stat_statements_reset()")
        for _ in range(MARKER_CALLS):
            conn.execute(MARKER_SQL)
    return pg_dsn
