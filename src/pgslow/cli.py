"""pgslow command-line interface.

Read-only by design. The only command that writes is `reset`, which clears the
pg_stat_statements counters and requires an explicit `--confirm`. EXPLAIN ANALYZE
executes the query, so it never runs implicitly, only behind `--analyze`.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import psycopg
import typer
from rich.console import Console

from pgslow import __version__, analyzer, collector
from pgslow import explain as explain_mod
from pgslow.analyzer import Order
from pgslow.connection import PgslowError, connect
from pgslow.render_terminal import render_top
from pgslow.report import render_report


def _make_console() -> Console:
    # Use the real terminal width when interactive; fall back to a comfortable
    # width when piped or redirected so the dense table isn't squeezed to 80.
    if sys.stdout.isatty():
        return Console()
    return Console(width=120)


console = _make_console()
err_console = Console(stderr=True)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Analyze slow PostgreSQL queries from pg_stat_statements. Read-only.",
)


# Shared option definitions ---------------------------------------------------

DsnOption = typer.Option(
    None,
    "--dsn",
    help="PostgreSQL connection string. Falls back to $PGSLOW_DSN, then $DATABASE_URL.",
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"pgslow {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """pgslow — find and explain your most expensive Postgres queries."""


@app.command()
def top(
    dsn: str | None = DsnOption,
    limit: int = typer.Option(20, "--limit", "-n", help="Number of queries to show."),
    order: Order = typer.Option(
        Order.total, "--order", help="Rank by total time, mean time, calls, or I/O."
    ),
) -> None:
    """Show the top queries by impact (default: total execution time)."""
    try:
        with connect(dsn) as conn:
            report = analyzer.analyze(collector.collect(conn))
    except PgslowError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    shown = analyzer.rank(report.queries, order, limit)
    render_top(console, report, shown, order.value)


@app.command()
def explain(
    dsn: str | None = DsnOption,
    queryid: int = typer.Option(..., "--queryid", help="pg_stat_statements queryid."),
    analyze: bool = typer.Option(
        False,
        "--analyze",
        help="Run EXPLAIN ANALYZE. WARNING: this EXECUTES the query.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt for --analyze (for non-interactive use).",
    ),
) -> None:
    """Show the execution plan for a query. EXPLAIN ANALYZE only with --analyze."""
    try:
        with connect(dsn) as conn:
            query = explain_mod.get_query_text(conn, queryid)
            _print_query(queryid, query)
            if analyze:
                _explain_analyze(conn, query, yes)
            else:
                plan = explain_mod.run_plain_explain(conn, query)
                _print_plan(plan, parameterized=explain_mod.has_parameters(query))
    except PgslowError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None


def _print_query(queryid: int, query: str) -> None:
    console.print(f"[dim]queryid[/dim] {queryid}")
    console.print("[dim]query[/dim]")
    for line in query.strip().splitlines():
        console.print(f"  {line}")
    console.print()


def _print_plan(plan: str, *, parameterized: bool, executed: bool = False) -> None:
    label = "EXPLAIN ANALYZE (executed)" if executed else "EXPLAIN"
    if parameterized and not executed:
        label += " - generic plan (normalized query has $1, $2, ...)"
    console.print(f"[dim]{label}[/dim]")
    console.print(plan)


def _explain_analyze(conn, query: str, yes: bool) -> None:
    # Validate up front: never prompt for something that would be refused.
    explain_mod.ensure_analyzable(query)

    console.print(
        "[red]WARNING:[/red] EXPLAIN ANALYZE will [bold]execute[/bold] this query "
        "against the database."
    )
    console.print(
        "[dim]It runs the real query (read-only; it will not modify data), "
        "and may be slow or load the server.[/dim]"
    )
    if not yes and not typer.confirm("Run EXPLAIN ANALYZE now?", default=False):
        console.print("Aborted. Nothing was executed.")
        raise typer.Exit(code=0)

    plan = explain_mod.run_analyze_explain(conn, query)
    console.print()
    _print_plan(plan, parameterized=False, executed=True)


@app.command()
def report(
    dsn: str | None = DsnOption,
    out: str = typer.Option("report.html", "--out", "-o", help="Output HTML file."),
    limit: int = typer.Option(30, "--limit", "-n", help="Number of queries to include."),
) -> None:
    """Export a self-contained HTML report of the slowest queries."""
    try:
        with connect(dsn) as conn:
            rep = analyzer.analyze(collector.collect(conn))
            shown = analyzer.rank(rep.queries, Order.total, limit)
            db = conn.execute("SELECT current_database()").fetchone()[0]
            pg_version = conn.execute("SHOW server_version").fetchone()[0].split()[0]
            rows = [_report_row(conn, q) for q in shown]
    except PgslowError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None

    top_pct = max((q.pct_total for q in rep.queries), default=0.0)
    html = render_report(
        db=db,
        pg_version=pg_version,
        tool_version=__version__,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        order="total time",
        total_queries=rep.total_queries,
        shown_count=len(shown),
        total_db_time=rep.total_db_time,
        top_pct=top_pct,
        rows=rows,
    )
    Path(out).write_text(html, encoding="utf-8")
    console.print(f"Wrote {out} ({len(shown)} queries).")


def _report_row(conn, q) -> dict:
    """Build one report row: analyzed metrics plus a safe EXPLAIN plan (no ANALYZE)."""
    parameterized = explain_mod.has_parameters(q.query)
    try:
        plan = explain_mod.run_plain_explain(conn, q.query)
        plan_error = None
    except PgslowError as exc:
        plan = None
        plan_error = str(exc)
    return {
        "queryid": q.queryid,
        "query": q.query,
        "calls": q.calls,
        "total": q.total_exec_time,
        "mean": q.mean_exec_time,
        "pct": q.pct_total,
        "cache_ratio": q.cache_hit_ratio,
        "flags": q.flags,
        "plan": plan,
        "plan_error": plan_error,
        "parameterized": parameterized,
    }


@app.command()
def reset(
    dsn: str | None = DsnOption,
    confirm: bool = typer.Option(
        False,
        "--confirm",
        help="Required. Resets pg_stat_statements (the only write this tool makes).",
    ),
) -> None:
    """Reset pg_stat_statements counters. Requires --confirm."""
    if not confirm:
        err_console.print(
            "[red]error:[/red] reset clears all pg_stat_statements counters. "
            "Re-run with --confirm to proceed."
        )
        raise typer.Exit(code=1)
    try:
        with connect(dsn, read_only=False) as conn:
            conn.execute("SELECT pg_stat_statements_reset()")
    except psycopg.Error as exc:
        err_console.print(
            f"[red]error:[/red] could not reset pg_stat_statements.\n{exc}"
        )
        raise typer.Exit(code=1) from None
    except PgslowError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from None
    console.print("pg_stat_statements counters reset.")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
