# pgslow

A read-only command-line tool that finds the queries costing your PostgreSQL the
most, ranks them by cumulative impact, runs `EXPLAIN` on demand, and exports a
single-file HTML report.

It reads `pg_stat_statements` so you don't have to query that wide table by hand.
The ranking is by total execution time (cumulative cost across all calls), not
the slowest single run, because that is what actually decides where the database
spends its time.

<!-- Add your terminal and report screenshots here once you have them:
![terminal](docs/terminal-screenshot.png)
![report](docs/report-screenshot.png)
-->

## Safety

- Read-only. The session opens with `default_transaction_read_only = on`, so a
  stray write fails at the server, not just by convention.
- `EXPLAIN ANALYZE` executes the query, so it never runs implicitly. You get a
  plain `EXPLAIN` unless you pass `--analyze`, which warns and asks to confirm.
- `reset` is the only command that writes (it clears the `pg_stat_statements`
  counters) and it requires `--confirm`.
- The connection string comes from `--dsn`, `$PGSLOW_DSN`, or `$DATABASE_URL` —
  never hardcoded.

## Install

```bash
pip install -e .
```

Requires Python 3.11+ and a PostgreSQL with the `pg_stat_statements` extension.
If the extension is missing, pgslow prints how to enable it instead of failing.

## Usage

```bash
# Top queries by impact (default: total time)
pgslow top --dsn postgresql://... [--limit 20] [--order total|mean|calls|io]

# Execution plan for one query (safe EXPLAIN, no execution)
pgslow explain --dsn postgresql://... --queryid 12345

# EXPLAIN ANALYZE — executes the query; explicit flag, asks to confirm
pgslow explain --dsn postgresql://... --queryid 12345 --analyze

# Single-file HTML report
pgslow report --dsn postgresql://... --out report.html [--limit 30]

# Reset pg_stat_statements counters (the only write; requires --confirm)
pgslow reset --dsn postgresql://... --confirm
```

`--dsn` can be omitted when `PGSLOW_DSN` or `DATABASE_URL` is set.

The `top` table shows calls, total and mean time, percent of total database time,
cache hit ratio, and flags: `temp` (spilled to disk), `cache` (low hit ratio),
and `var` (unstable runtime). The HTML report adds a click-to-expand plan per
query and is self-contained (CSS and JS inlined, no external requests).

## Demo

A throwaway PostgreSQL with `pg_stat_statements` enabled and a varied workload:

```bash
docker compose -f examples/docker-compose.yml up -d
export PGSLOW_DSN=postgresql://pgslow:pgslow@localhost:5432/pgslow_demo
psql "$PGSLOW_DSN" -f examples/workload.sql

pgslow top
pgslow report --out report.html
```

Set `PGSLOW_HOST_PORT` before `up` if port 5432 is taken locally.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest                                  # unit tests only
PGSLOW_TEST_DSN=postgresql://... pytest  # plus integration tests
```

## License

MIT
