"""Derived metrics, flags, and ranking.

Impact is measured by cumulative cost (total_exec_time), not the worst isolated
call — that is the number that actually decides where the database spends time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pgslow.collector import QueryStat

# A query reading more than this fraction from disk (vs cache) is worth a look.
LOW_CACHE_HIT = 0.95


class Order(StrEnum):
    """Ranking criterion."""

    total = "total"
    mean = "mean"
    calls = "calls"
    io = "io"


@dataclass(frozen=True)
class AnalyzedQuery:
    """A pg_stat_statements row enriched with derived metrics and flags."""

    queryid: int | None
    query: str
    calls: int
    total_exec_time: float
    mean_exec_time: float
    stddev_exec_time: float
    rows: int
    pct_total: float
    cache_hit_ratio: float | None  # None when the query touched no shared blocks
    io_blocks: int  # disk reads + temp traffic
    temp_spill: bool
    low_cache: bool
    unstable: bool

    @property
    def flags(self) -> list[str]:
        out: list[str] = []
        if self.temp_spill:
            out.append("temp")
        if self.low_cache:
            out.append("cache")
        if self.unstable:
            out.append("var")
        return out


@dataclass(frozen=True)
class Report:
    """Analyzed queries plus database-wide totals for context."""

    queries: list[AnalyzedQuery]
    total_db_time: float
    total_queries: int


def analyze(stats: list[QueryStat]) -> Report:
    """Compute derived metrics for every row and the database-wide totals."""
    total_db_time = sum(s.total_exec_time for s in stats)
    analyzed = [_analyze_one(s, total_db_time) for s in stats]
    return Report(
        queries=analyzed,
        total_db_time=total_db_time,
        total_queries=len(analyzed),
    )


def _analyze_one(s: QueryStat, total_db_time: float) -> AnalyzedQuery:
    blocks = s.shared_blks_hit + s.shared_blks_read
    cache_hit_ratio = s.shared_blks_hit / blocks if blocks > 0 else None
    return AnalyzedQuery(
        queryid=s.queryid,
        query=s.query,
        calls=s.calls,
        total_exec_time=s.total_exec_time,
        mean_exec_time=s.mean_exec_time,
        stddev_exec_time=s.stddev_exec_time,
        rows=s.rows,
        pct_total=(s.total_exec_time / total_db_time * 100) if total_db_time > 0 else 0.0,
        cache_hit_ratio=cache_hit_ratio,
        io_blocks=s.shared_blks_read + s.temp_blks_read + s.temp_blks_written,
        temp_spill=s.temp_blks_written > 0,
        low_cache=cache_hit_ratio is not None and cache_hit_ratio < LOW_CACHE_HIT,
        # Unstable: spread across calls rivals the mean, with enough calls to mean it.
        unstable=s.calls >= 5 and s.mean_exec_time > 0 and s.stddev_exec_time > s.mean_exec_time,
    )


_SORT_KEYS = {
    Order.total: lambda q: q.total_exec_time,
    Order.mean: lambda q: q.mean_exec_time,
    Order.calls: lambda q: q.calls,
    Order.io: lambda q: q.io_blocks,
}


def rank(queries: list[AnalyzedQuery], order: Order, limit: int) -> list[AnalyzedQuery]:
    """Return the top `limit` queries by the chosen criterion, highest first."""
    ordered = sorted(queries, key=_SORT_KEYS[order], reverse=True)
    return ordered[:limit] if limit > 0 else ordered
