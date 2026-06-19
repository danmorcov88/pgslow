"""Render a self-contained HTML report (CSS and JS inlined, no external CDNs)."""

from __future__ import annotations

import re
from importlib.resources import files
from typing import Any

import jinja2

_WHITESPACE = re.compile(r"\s+")

# Minimal vanilla JS: click a row to expand its plan; click a numeric header to
# sort, keeping each detail row attached to its parent.
_JS = """
(function () {
  var table = document.querySelector('table');
  if (!table) return;
  var tbody = table.tBodies[0];

  Array.prototype.forEach.call(tbody.querySelectorAll('tr.row'), function (row) {
    row.addEventListener('click', function () {
      var detail = row.nextElementSibling;
      if (!detail || !detail.classList.contains('detail')) return;
      if (detail.hasAttribute('hidden')) {
        detail.removeAttribute('hidden');
        row.classList.add('open');
      } else {
        detail.setAttribute('hidden', '');
        row.classList.remove('open');
      }
    });
  });

  var state = { key: null, dir: 1 };
  Array.prototype.forEach.call(table.querySelectorAll('th[data-key]'), function (th) {
    th.addEventListener('click', function () {
      var key = th.getAttribute('data-key');
      state.dir = (state.key === key) ? -state.dir : 1;
      state.key = key;
      var pairs = [];
      Array.prototype.forEach.call(tbody.querySelectorAll('tr.row'), function (r) {
        pairs.push([r, r.nextElementSibling]);
      });
      function value(row) {
        var cell = row.querySelector('[data-col="' + key + '"]');
        var n = parseFloat(cell.getAttribute('data-value'));
        return isNaN(n) ? -Infinity : n;
      }
      pairs.sort(function (a, b) {
        return (value(a[0]) - value(b[0])) * state.dir;
      });
      pairs.forEach(function (p) {
        tbody.appendChild(p[0]);
        if (p[1]) tbody.appendChild(p[1]);
      });
      Array.prototype.forEach.call(table.querySelectorAll('th'), function (h) {
        h.removeAttribute('data-sorted');
      });
      th.setAttribute('data-sorted', state.dir > 0 ? 'asc' : 'desc');
    });
  });
})();
"""

# Cache hit threshold for functional colour. Only problems are coloured (red);
# healthy values stay neutral so the column doesn't read as a wall of green.
_LOW_CACHE = 0.95
_PCT_CRIT = 25.0


def render_report(
    *,
    db: str,
    pg_version: str,
    tool_version: str,
    generated_at: str,
    order: str,
    total_queries: int,
    shown_count: int,
    total_db_time: float,
    top_pct: float,
    rows: list[dict[str, Any]],
) -> str:
    """Return the complete HTML document as a string."""
    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.from_string(_load("template.html.j2"))
    return template.render(
        css=_load("style.css"),
        js=_JS,
        db=db,
        pg_version=pg_version,
        tool_version=tool_version,
        generated_at=generated_at,
        order=order,
        total_queries=total_queries,
        shown_count=shown_count,
        total_db_time=_fmt_ms(total_db_time),
        top_pct=_fmt_pct(top_pct),
        top_pct_crit=top_pct >= _PCT_CRIT,
        rows=[_view(r) for r in rows],
    )


def _view(r: dict[str, Any]) -> dict[str, Any]:
    """Turn a raw row into the pre-formatted fields the template expects."""
    ratio = r["cache_ratio"]
    return {
        "queryid": r["queryid"],
        "short": _collapse(r["query"]),
        "full": r["query"].strip(),
        "calls": r["calls"],
        "calls_fmt": f"{r['calls']:,}",
        "total": r["total"],
        "total_fmt": _fmt_ms(r["total"]),
        "mean": r["mean"],
        "mean_fmt": _fmt_ms(r["mean"]),
        "pct": r["pct"],
        "pct_fmt": _fmt_pct(r["pct"]),
        "pct_bar": round(min(r["pct"], 100.0), 2),
        "pct_crit": r["pct"] >= _PCT_CRIT,
        "cache_fmt": "-" if ratio is None else _fmt_pct(ratio * 100),
        "cache_sort": -1 if ratio is None else round(ratio * 100, 4),
        "cache_class": _cache_class(ratio),
        "flags": r["flags"],
        "has_plan": r["plan"] is not None,
        "plan": r["plan"] if r["plan"] is not None else r["plan_error"],
        "plan_label": _plan_label(r),
    }


def _plan_label(r: dict[str, Any]) -> str:
    if r["plan"] is None:
        return "explain (not available)"
    if r["parameterized"]:
        return "explain (generic plan)"
    return "explain"


def _cache_class(ratio: float | None) -> str:
    if ratio is not None and ratio < _LOW_CACHE:
        return "crit"
    return ""


def _collapse(query: str) -> str:
    return _WHITESPACE.sub(" ", query).strip()


def _fmt_ms(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 1:
        return f"{value:,.1f}"
    return f"{value:.3f}"


def _fmt_pct(value: float) -> str:
    return f"{value:.1f}"


def _load(name: str) -> str:
    return (files(__package__) / name).read_text(encoding="utf-8")
