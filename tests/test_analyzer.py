"""Derived metrics, flags, and ranking on controlled data (no database)."""

from __future__ import annotations

from pgslow.analyzer import Order, analyze, rank
from pgslow.collector import QueryStat


def make_stat(**overrides) -> QueryStat:
    base = dict(
        queryid=1,
        query="SELECT 1",
        calls=1,
        total_exec_time=1.0,
        mean_exec_time=1.0,
        stddev_exec_time=0.0,
        min_exec_time=0.0,
        max_exec_time=1.0,
        rows=0,
        shared_blks_hit=0,
        shared_blks_read=0,
        shared_blks_written=0,
        temp_blks_read=0,
        temp_blks_written=0,
    )
    base.update(overrides)
    return QueryStat(**base)


def only(stats) -> object:
    report = analyze(stats)
    assert len(report.queries) == 1
    return report.queries[0]


def test_cache_hit_ratio_computed():
    q = only([make_stat(shared_blks_hit=90, shared_blks_read=10)])
    assert q.cache_hit_ratio == 0.9


def test_cache_hit_ratio_none_when_no_blocks():
    q = only([make_stat(shared_blks_hit=0, shared_blks_read=0)])
    assert q.cache_hit_ratio is None
    assert q.low_cache is False


def test_percent_of_total_db_time():
    report = analyze(
        [
            make_stat(queryid=1, total_exec_time=75.0),
            make_stat(queryid=2, total_exec_time=25.0),
        ]
    )
    assert report.total_db_time == 100.0
    by_id = {q.queryid: q for q in report.queries}
    assert by_id[1].pct_total == 75.0
    assert by_id[2].pct_total == 25.0


def test_temp_spill_flag():
    assert only([make_stat(temp_blks_written=5)]).temp_spill is True
    assert only([make_stat(temp_blks_written=0)]).temp_spill is False


def test_low_cache_flag_threshold():
    low = only([make_stat(shared_blks_hit=80, shared_blks_read=20)])  # 0.80
    high = only([make_stat(shared_blks_hit=99, shared_blks_read=1)])  # 0.99
    assert low.low_cache is True
    assert high.low_cache is False


def test_unstable_needs_enough_calls():
    unstable = only([make_stat(calls=6, mean_exec_time=10.0, stddev_exec_time=15.0)])
    too_few = only([make_stat(calls=3, mean_exec_time=10.0, stddev_exec_time=15.0)])
    steady = only([make_stat(calls=6, mean_exec_time=10.0, stddev_exec_time=2.0)])
    assert unstable.unstable is True
    assert too_few.unstable is False
    assert steady.unstable is False


def test_flags_property_order():
    q = only(
        [
            make_stat(
                calls=6,
                mean_exec_time=10.0,
                stddev_exec_time=15.0,
                shared_blks_hit=80,
                shared_blks_read=20,
                temp_blks_written=3,
            )
        ]
    )
    assert q.flags == ["temp", "cache", "var"]


def test_io_blocks_sum():
    q = only([make_stat(shared_blks_read=100, temp_blks_read=10, temp_blks_written=200)])
    assert q.io_blocks == 310


def _ranked_ids(stats, order):
    report = analyze(stats)
    return [q.queryid for q in rank(report.queries, order, limit=10)]


def test_rank_by_total():
    stats = [
        make_stat(queryid=1, total_exec_time=10.0),
        make_stat(queryid=2, total_exec_time=30.0),
        make_stat(queryid=3, total_exec_time=20.0),
    ]
    assert _ranked_ids(stats, Order.total) == [2, 3, 1]


def test_rank_by_mean():
    stats = [
        make_stat(queryid=1, mean_exec_time=5.0),
        make_stat(queryid=2, mean_exec_time=1.0),
        make_stat(queryid=3, mean_exec_time=9.0),
    ]
    assert _ranked_ids(stats, Order.mean) == [3, 1, 2]


def test_rank_by_calls():
    stats = [
        make_stat(queryid=1, calls=5),
        make_stat(queryid=2, calls=50),
        make_stat(queryid=3, calls=15),
    ]
    assert _ranked_ids(stats, Order.calls) == [2, 3, 1]


def test_rank_by_io():
    stats = [
        make_stat(queryid=1, shared_blks_read=100),
        make_stat(queryid=2, temp_blks_written=500),
        make_stat(queryid=3, shared_blks_read=50, temp_blks_read=50),
    ]
    assert _ranked_ids(stats, Order.io) == [2, 1, 3]


def test_rank_respects_limit():
    stats = [make_stat(queryid=i, total_exec_time=float(i)) for i in range(1, 6)]
    report = analyze(stats)
    top2 = rank(report.queries, Order.total, limit=2)
    assert [q.queryid for q in top2] == [5, 4]
