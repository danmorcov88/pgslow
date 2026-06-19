"""Statement classification and the EXPLAIN ANALYZE guards (no database)."""

from __future__ import annotations

import pytest

from pgslow import explain
from pgslow.connection import PgslowError


def test_leading_keyword():
    assert explain.leading_keyword("  SELECT 1") == "select"
    assert explain.leading_keyword("(SELECT 1)") == "select"
    assert explain.leading_keyword("DO $$ ... $$") == "do"


def test_is_plannable():
    assert explain.is_plannable("SELECT * FROM t")
    assert explain.is_plannable("INSERT INTO t VALUES (1)")
    assert not explain.is_plannable("DO $$ BEGIN END $$")
    assert not explain.is_plannable("CREATE TABLE t (a int)")
    assert not explain.is_plannable("ANALYZE t")


def test_is_write():
    assert explain.is_write("INSERT INTO t VALUES (1)")
    assert explain.is_write("UPDATE t SET a = 1")
    assert explain.is_write("DELETE FROM t")
    assert not explain.is_write("SELECT * FROM t")


def test_has_parameters():
    assert explain.has_parameters("SELECT * FROM t WHERE id = $1")
    assert not explain.has_parameters("SELECT * FROM t WHERE id = 1")


def test_ensure_analyzable_rejects_utility():
    with pytest.raises(PgslowError, match="Cannot EXPLAIN"):
        explain.ensure_analyzable("DO $$ BEGIN END $$")


def test_ensure_analyzable_rejects_write():
    with pytest.raises(PgslowError, match="modify data"):
        explain.ensure_analyzable("INSERT INTO t SELECT 1")


def test_ensure_analyzable_rejects_parameterized():
    with pytest.raises(PgslowError, match="parameterized"):
        explain.ensure_analyzable("SELECT * FROM t WHERE id = $1")


def test_ensure_analyzable_allows_plain_select():
    # No exception for a concrete, read-only query.
    explain.ensure_analyzable("SELECT count(*) FROM t")
