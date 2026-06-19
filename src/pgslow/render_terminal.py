"""Sober terminal output for `top`.

One dense table. Functional colour only: the accent (amber/red) marks values
worth attention — low cache hit, temp spill, instability. Nothing decorative.
"""

from __future__ import annotations

import re

from rich.console import Console
from rich.table import Table
from rich.text import Text

from pgslow.analyzer import Report

_WHITESPACE = re.compile(r"\s+")
QUERY_WIDTH = 60  # characters of query text shown in the table

ACCENT = "red"  # critical values
WARN = "yellow"  # secondary attention
MUTED = "dim"

FLAG_STYLE = {"temp": ACCENT, "cache": ACCENT, "var": WARN}


def render_top(console: Console, report: Report, shown: list, order: str) -> None:
    """Print the ranked table plus a one-line summary header."""
    if not shown:
        console.print(
            "[dim]No queries recorded yet. Run some workload, then try again.[/dim]"
        )
        return

    _print_summary(console, report)

    table = Table(
        box=None,
        pad_edge=False,
        header_style="bold",
        expand=False,
    )
    table.add_column("#", justify="right", style=MUTED)
    # Query is truncated to a fixed budget in Python (ASCII "..."), so numeric
    # columns always keep their full width and never collapse into ellipses.
    table.add_column("query", no_wrap=True)
    table.add_column("calls", justify="right")
    table.add_column("total ms", justify="right")
    table.add_column("mean ms", justify="right")
    table.add_column("% total", justify="right")
    table.add_column("cache", justify="right")
    table.add_column("flags", justify="left")

    for i, q in enumerate(shown, start=1):
        table.add_row(
            str(i),
            _short_query(q.query),
            _int(q.calls),
            _ms(q.total_exec_time),
            _ms(q.mean_exec_time),
            _pct(q.pct_total),
            _cache(q.cache_hit_ratio, q.low_cache),
            _flags(q.flags),
        )

    console.print(table)
    console.print(
        f"[dim]ranked by {order}; {len(shown)} of {report.total_queries} queries[/dim]"
    )


def _print_summary(console: Console, report: Report) -> None:
    top_pct = report.queries and max(q.pct_total for q in report.queries) or 0.0
    console.print(
        Text.assemble(
            ("queries analyzed ", MUTED),
            (str(report.total_queries), "bold"),
            ("   total db time ", MUTED),
            (_ms(report.total_db_time), "bold"),
            (" ms", MUTED),
            ("   top consumer ", MUTED),
            (f"{top_pct:.1f}%", "bold"),
        )
    )


# Formatting helpers ----------------------------------------------------------

def _short_query(query: str) -> str:
    collapsed = _WHITESPACE.sub(" ", query).strip()
    if len(collapsed) > QUERY_WIDTH:
        return collapsed[: QUERY_WIDTH - 3] + "..."
    return collapsed


def _int(value: int) -> str:
    return f"{value:,}"


def _ms(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 1:
        return f"{value:,.1f}"
    return f"{value:.3f}"


def _pct(value: float) -> Text:
    style = ACCENT if value >= 25 else ""
    return Text(f"{value:.1f}", style=style)


def _cache(ratio: float | None, low: bool) -> Text:
    if ratio is None:
        return Text("-", style=MUTED)
    style = ACCENT if low else ""
    return Text(f"{ratio * 100:.1f}", style=style)


def _flags(flags: list[str]) -> Text:
    if not flags:
        return Text("")
    parts = Text()
    for i, flag in enumerate(flags):
        if i:
            parts.append(" ")
        parts.append(flag, style=FLAG_STYLE.get(flag, ""))
    return parts
