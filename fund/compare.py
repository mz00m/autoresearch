"""Strategy comparison — would another bench candidate be doing better?

Runs every strategy in the registry side-by-side over the same real-data
window, in isolated portfolio state files (the live ``portfolio_state.json``
is never touched). Writes ``fund/comparison.html`` with overlaid equity
curves and a metrics table.

This is the "should I switch?" companion to the daily card's on-track/iterate
verdict. The daily card tells you whether your strategy is doing badly; this
tells you whether anything else would have done better in the same window —
which is the much more important question.
"""

from __future__ import annotations

import argparse
import csv
import html as _html
import os
import sys
import tempfile
from datetime import date, datetime

from fund.daily_report import _INK, _ACCENT, _MUTED, _NEG, _POS, _svg_line_chart
from fund.portfolio import Portfolio
from fund.simulate import simulate
from fund.strategy.registry import list_strategies

COMPARISON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "comparison.html")

# distinct colors for up to ~6 series; everything else gets gray
_PALETTE = ["#1f4f8b", "#1a7d3a", "#a83232", "#b88216", "#5e3a8c", "#157d7d"]


def _run_one(name: str, *, days: int, end: date, principal: float,
             source: str, params: dict | None = None) -> tuple[Portfolio, list[dict]]:
    """Run a sim into a tempfile state + log, return (final pf, log rows)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        state_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as f:
        log_path = f.name
    # delete the placeholders so simulate creates fresh files
    os.unlink(state_path)
    os.unlink(log_path)
    try:
        pf, _ = simulate(days=days, end=end, principal=principal,
                         strategy=name, strategy_params=params,
                         source=source, state_path=state_path,
                         log_path=log_path, quiet=True)
        with open(log_path, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        return pf, rows
    finally:
        for p in (state_path, log_path):
            if os.path.exists(p):
                os.unlink(p)


def _metrics(pf: Portfolio, rows: list[dict]) -> dict:
    """Compact metrics for the comparison table."""
    if not pf.history or len(pf.history) < 2:
        return {"cum": 0.0, "max_dd": 0.0, "best_day": 0.0, "worst_day": 0.0,
                "hit_rate": 0.0, "ending_eq": pf.cash, "n_days": 0,
                "bench_cum": 0.0, "excess": 0.0}
    cum = pf.history[-1].equity / pf.history[0].equity - 1.0
    running_peak = pf.history[0].equity
    max_dd = 0.0
    for h in pf.history:
        running_peak = max(running_peak, h.equity)
        if running_peak > 0:
            max_dd = max(max_dd, (running_peak - h.equity) / running_peak)
    day_rets = [float(r.get("day_return") or 0) for r in rows]
    best = max(day_rets) if day_rets else 0.0
    worst = min(day_rets) if day_rets else 0.0
    bench_cum = 0.0
    bench_last = [r for r in rows if r.get("benchmark_cum_return")]
    if bench_last:
        try:
            bench_cum = float(bench_last[-1]["benchmark_cum_return"])
        except ValueError:
            bench_cum = 0.0
    # hit rate: portfolio beats benchmark daily
    bench_daily: list[float] = []
    prior = 0.0
    for r in rows:
        b = r.get("benchmark_cum_return", "")
        if not b:
            bench_daily.append(0.0)
            continue
        cur = float(b)
        prev = 1.0 + prior
        bench_daily.append((1 + cur) / prev - 1.0 if prev > 0 else 0.0)
        prior = cur
    paired = list(zip(day_rets, bench_daily))
    hit = sum(1 for p, b in paired if p > b) / len(paired) if paired else 0.0
    return {
        "cum": cum, "max_dd": max_dd, "best_day": best, "worst_day": worst,
        "hit_rate": hit, "ending_eq": pf.history[-1].equity,
        "n_days": len(rows), "bench_cum": bench_cum, "excess": cum - bench_cum,
    }


# --- HTML rendering ---------------------------------------------------------

_CSS = """
body {
  font-family: "Iowan Old Style", "Charter", Georgia, serif;
  background: #fafaf7; color: #1a1a1a;
  max-width: 920px; margin: 0 auto; padding: 56px 32px 80px;
  line-height: 1.55;
}
header { border-bottom: 1px solid #1a1a1a; padding-bottom: 18px; margin-bottom: 36px; }
header .eyebrow { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #666; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
header h1 { font-size: 30px; margin: 6px 0 0; font-weight: 600; }
header .meta { margin-top: 8px; color: #666; font-size: 14px; }
h2 { font-size: 17px; font-weight: 600; margin: 36px 0 12px; padding-bottom: 4px; border-bottom: 1px solid #dcdcdc; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
table th { text-align: left; font-weight: 500; color: #666; border-bottom: 1px solid #1a1a1a; padding: 8px 10px; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }
table td { padding: 8px 10px; border-bottom: 1px solid #ececec; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.pos { color: #1a7d3a; }
.neg { color: #a83232; }
.muted { color: #666; }
.swatch { display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: middle; border-radius: 1px; }
.winner { background: #f3f6ee; }
footer { margin-top: 56px; padding-top: 16px; border-top: 1px solid #dcdcdc; color: #888; font-size: 11px; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
.note { color: #666; font-size: 13px; margin-top: 8px; }
"""


def _curve_chart(results: list[tuple[str, Portfolio, list[dict], str]],
                 width: int = 820, height: int = 280) -> str:
    series = []
    for name, pf, _rows, color in results:
        if len(pf.history) < 2:
            continue
        base = pf.history[0].equity
        if base <= 0:
            continue
        pts = [(i, h.equity / base - 1.0) for i, h in enumerate(pf.history)]
        series.append((name, pts, color))
    # SPY benchmark from any one of them (they all loaded the same history)
    for name, pf, rows, _ in results:
        spy_pts = []
        for i, r in enumerate(rows):
            b = r.get("benchmark_cum_return", "")
            if b:
                try:
                    spy_pts.append((i + 1, float(b)))  # +1 because history[0] is inception day
                except ValueError:
                    pass
        if len(spy_pts) >= 2:
            series.append(("SPY", spy_pts, _MUTED))
            break
    return _svg_line_chart(width, height, series,
                           title="Cumulative return — strategies vs SPY")


def _metrics_table(results: list[tuple[str, Portfolio, list[dict], str]]) -> str:
    rows_html = []
    # winner row gets highlighted
    if not results:
        return '<div class="muted">No results.</div>'
    metrics = [(name, color, _metrics(pf, rows)) for name, pf, rows, color in results]
    winner = max(metrics, key=lambda m: m[2]["cum"])[0]
    for name, color, m in metrics:
        cls = "winner" if name == winner else ""
        rows_html.append(
            f'<tr class="{cls}">'
            f'<td><span class="swatch" style="background:{color}"></span>'
            f'<strong>{_html.escape(name)}</strong></td>'
            f'<td class="num {"pos" if m["cum"] > 0 else "neg"}">{m["cum"] * 100:+.2f}%</td>'
            f'<td class="num muted">{m["bench_cum"] * 100:+.2f}%</td>'
            f'<td class="num {"pos" if m["excess"] > 0 else "neg"}">{m["excess"] * 100:+.2f}pp</td>'
            f'<td class="num neg">-{m["max_dd"] * 100:.2f}%</td>'
            f'<td class="num">{m["best_day"] * 100:+.2f}%</td>'
            f'<td class="num">{m["worst_day"] * 100:+.2f}%</td>'
            f'<td class="num">{m["hit_rate"] * 100:.0f}%</td>'
            f'<td class="num">${m["ending_eq"]:,.0f}</td>'
            f'</tr>'
        )
    return ('<table><thead><tr><th>Strategy</th><th class="num">Cum</th>'
            '<th class="num">SPY</th><th class="num">Excess</th>'
            '<th class="num">Max DD</th><th class="num">Best day</th>'
            '<th class="num">Worst day</th><th class="num">Hit rate</th>'
            '<th class="num">End equity</th>'
            '</tr></thead><tbody>' + "".join(rows_html) + '</tbody></table>')


def render(results: list[tuple[str, Portfolio, list[dict], str]], *,
           days: int, end: date, principal: float, active: str | None) -> str:
    metrics_html = _metrics_table(results)
    chart_html = _curve_chart(results)
    active_note = ""
    if active:
        active_obj = [(n, _metrics(pf, rows)) for n, pf, rows, _ in results
                      if n == active]
        if active_obj:
            n, m = active_obj[0]
            top = max((_metrics(pf, rows)["cum"], n2)
                      for n2, pf, rows, _ in results)
            top_cum, top_name = top
            if top_name == active:
                active_note = (f'<p class="note">Your active strategy '
                               f'<strong>{active}</strong> would have led this window.</p>')
            else:
                gap = (top_cum - m["cum"]) * 100
                active_note = (f'<p class="note">Your active strategy '
                               f'<strong>{active}</strong> trails the bench leader '
                               f'<strong>{top_name}</strong> by {gap:.2f}pp over this window. '
                               f'A persistent gap is the signal — not one window.</p>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Strategy comparison — {end.isoformat()}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="eyebrow">Strategy comparison</div>
  <h1>{end.strftime('%A, %B %-d, %Y')}</h1>
  <div class="meta">{days} trading days &middot; principal ${principal:,.0f}
    &middot; isolated paper accounts (live state untouched)</div>
</header>

<h2>Side-by-side</h2>
{chart_html}
{metrics_html}
{active_note}

<footer>
Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. Counterfactual sim on
real Yahoo data with the same costs and rebalance rules as the live loop.
One window is not alpha. Use this to spot persistent regime gaps, not to
chase last week's winner.
</footer>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare all strategies side-by-side.")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--end", type=str, default="",
                    help="ISO date (default: today)")
    ap.add_argument("--principal", type=float, default=25_000.0)
    ap.add_argument("--source", default="auto")
    ap.add_argument("--strategies", default="",
                    help="comma-separated names; default = full registry")
    ap.add_argument("--out", default=COMPARISON_PATH)
    args = ap.parse_args()
    end = date.fromisoformat(args.end) if args.end else date.today()
    names = ([n.strip() for n in args.strategies.split(",") if n.strip()]
             if args.strategies else list_strategies())

    active = None
    try:
        active = Portfolio.load().active_strategy
    except FileNotFoundError:
        pass

    results: list[tuple[str, Portfolio, list[dict], str]] = []
    for i, name in enumerate(names):
        color = _PALETTE[i % len(_PALETTE)]
        print(f"  simulating {name}...")
        pf, rows = _run_one(name, days=args.days, end=end,
                            principal=args.principal, source=args.source)
        results.append((name, pf, rows, color))

    html = render(results, days=args.days, end=end,
                  principal=args.principal, active=active)
    with open(args.out, "w") as f:
        f.write(html)
    # Console summary
    print(f"\n{'strategy':<18} {'cum':>9} {'spy':>9} {'excess':>9} {'max dd':>9} {'end eq':>12}")
    print("-" * 70)
    for name, pf, rows, _ in results:
        m = _metrics(pf, rows)
        print(f"{name:<18} {m['cum'] * 100:>+8.2f}% {m['bench_cum'] * 100:>+8.2f}%"
              f" {m['excess'] * 100:>+7.2f}pp {-m['max_dd'] * 100:>+8.2f}%"
              f" ${m['ending_eq']:>10,.0f}")
    print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
