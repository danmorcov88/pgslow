"""End-to-end tests against a live PostgreSQL with pg_stat_statements.

Skipped unless PGSLOW_TEST_DSN is set (see conftest).
"""

from __future__ import annotations

import psycopg
import pytest
from conftest import MARKER_CALLS, MARKER_TEXT

from pgslow import analyzer, collector, explain
from pgslow.connection import PgslowError, connect

pytestmark = pytest.mark.integration


def _find_marker(stats):
    return next((s for s in stats if MARKER_TEXT in s.query), None)


def test_collector_returns_seeded_query(seeded_dsn):
    with connect(seeded_dsn) as conn:
        stats = collector.collect(conn)
    marker = _find_marker(stats)
    assert marker is not None
    assert marker.calls == MARKER_CALLS


def test_analyzer_computes_metrics_on_real_data(seeded_dsn):
    with connect(seeded_dsn) as conn:
        report = analyzer.analyze(collector.collect(conn))
    assert report.total_db_time > 0
    marker = _find_marker(report.queries)
    assert marker is not None
    assert 0 <= marker.pct_total <= 100


def test_connection_is_read_only(seeded_dsn):
    """The session refuses writes, so an accidental modification fails loudly."""
    with connect(seeded_dsn) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TABLE pgslow_should_not_exist (x int)")


def test_explain_plain_select(seeded_dsn):
    with connect(seeded_dsn) as conn:
        plan = explain.run_plain_explain(conn, "SELECT 1")
    assert "cost=" in plan


def test_explain_generic_plan_for_parameterized(seeded_dsn):
    with connect(seeded_dsn) as conn:
        plan = explain.run_plain_explain(conn, "SELECT * FROM pg_class WHERE relpages > $1")
    assert "cost=" in plan


def test_explain_rejects_utility_statement(seeded_dsn):
    with connect(seeded_dsn) as conn:
        with pytest.raises(PgslowError, match="utility"):
            explain.run_plain_explain(conn, "ANALYZE pg_class")
