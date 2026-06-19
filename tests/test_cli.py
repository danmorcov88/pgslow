"""CLI wiring, help text, and graceful failure (no database)."""

from __future__ import annotations

import contextlib

from typer.testing import CliRunner

from pgslow import cli, collector
from pgslow.connection import PgslowError

runner = CliRunner()


def test_root_help_lists_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in ("top", "explain", "report", "reset"):
        assert command in result.output


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "pgslow" in result.output


def test_top_help_shows_order_options():
    result = runner.invoke(cli.app, ["top", "--help"])
    assert result.exit_code == 0
    assert "--order" in result.output
    assert "--limit" in result.output


def test_explain_help_warns_about_analyze():
    result = runner.invoke(cli.app, ["explain", "--help"])
    assert result.exit_code == 0
    assert "--analyze" in result.output
    assert "EXECUTES" in result.output


def test_missing_dsn_exits_nonzero():
    result = runner.invoke(cli.app, ["top"], env={"PGSLOW_DSN": "", "DATABASE_URL": ""})
    assert result.exit_code == 1


def test_top_handles_missing_extension_gracefully(monkeypatch):
    """A PgslowError from the collector becomes a clean exit, not a traceback."""

    @contextlib.contextmanager
    def fake_connect(dsn):
        yield object()

    def boom(conn):
        raise PgslowError("pg_stat_statements is not available on this database.")

    monkeypatch.setattr(cli, "connect", fake_connect)
    monkeypatch.setattr(cli.collector, "collect", boom)

    result = runner.invoke(cli.app, ["top", "--dsn", "postgresql://example/db"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)


class _FakeResult:
    def fetchone(self):
        return None  # extension row not found


class _FakeConn:
    def execute(self, *args, **kwargs):
        return _FakeResult()


def test_collector_missing_extension_message():
    """The collector explains how to enable the extension instead of crashing."""
    import pytest

    with pytest.raises(PgslowError) as exc:
        collector.collect(_FakeConn())
    message = str(exc.value)
    assert "shared_preload_libraries" in message
    assert "CREATE EXTENSION" in message
