"""Daily HTML card — what Matt reads with coffee.

Combines yesterday's closeout + today's morning guide into a single editorial
page. Pure stdlib SVG charts, zero JS, zero CSS framework — designed to read
like a one-page memo, not a dashboard. Tufte's ratio: ink that informs only.

Sections:
  1. Header     — strategy, equity, day P&L, drawdown
  2. Track      — equity vs SPY benchmark (SVG), drawdown ribbon
  3. Today      — pending tickets with risk verdicts and rationales
  4. Yesterday  — what filled, day P&L, drift signal
  5. Log tail   — last N days from daily_log.tsv
"""

from __future__ import annotations

import csv
import html as _html
import math
import os
from datetime import date, datetime
from typing import Iterable

from fund.decision import DecisionConfig, evaluate as evaluate_decision
from fund.portfolio import EquityPoint, Portfolio, Ticket

REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "daily.html")

# Tufte-leaning palette — restrained, high contrast on white
_INK = "#1a1a1a"
_MUTED = "#666"
_RULE = "#dcdcdc"
_POS = "#1a7d3a"   # subtle green
_NEG = "#a83232"   # subtle red
_ACCENT = "#1f4f8b"  # editorial blue


# --- chart primitives -------------------------------------------------------

def _svg_line_chart(width: int, height: int,
                    series: list[tuple[str, list[tuple[float, float]], str]],
                    *, title: str = "", y_format: str = "{:.0%}",
                    pad_left: int = 56, pad_right: int = 84,
                    pad_top: int = 28, pad_bottom: int = 30) -> str:
    """Render labeled line series. `series` = [(label, [(x, y), ...], color)].
    x's must be numeric (e.g., days since inception); y's are returns."""
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    if plot_w <= 10 or plot_h <= 10 or not series:
        return ""
    all_pts = [pt for _, pts, _ in series for pt in pts]
    if not all_pts:
        return ""
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1
    if y_max == y_min:
        y_max = y_min + 0.01
    # pad y slightly
    y_span = y_max - y_min
    y_min -= y_span * 0.05
    y_max += y_span * 0.05

    def sx(x: float) -> float:
        return pad_left + (x - x_min) / (x_max - x_min) * plot_w

    def sy(y: float) -> float:
        return pad_top + (1 - (y - y_min) / (y_max - y_min)) * plot_h

    parts: list[str] = []
    parts.append(f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
                 f'font-family="Iowan Old Style, Georgia, serif" font-size="11" fill="{_INK}">')
    if title:
        parts.append(f'<text x="{pad_left}" y="16" font-size="12" font-weight="600" fill="{_INK}">{_html.escape(title)}</text>')

    # zero baseline if range crosses zero
    if y_min < 0 < y_max:
        y0 = sy(0)
        parts.append(f'<line x1="{pad_left}" y1="{y0}" x2="{pad_left + plot_w}" y2="{y0}" stroke="{_RULE}" stroke-dasharray="2,3"/>')

    # y-axis ticks (3)
    for frac in (0.0, 0.5, 1.0):
        yv = y_min + frac * (y_max - y_min)
        yp = sy(yv)
        parts.append(f'<line x1="{pad_left - 4}" y1="{yp}" x2="{pad_left}" y2="{yp}" stroke="{_MUTED}"/>')
        parts.append(f'<text x="{pad_left - 8}" y="{yp + 4}" text-anchor="end" fill="{_MUTED}">{y_format.format(yv)}</text>')

    # axis lines
    parts.append(f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{pad_top + plot_h}" stroke="{_INK}" stroke-width="0.5"/>')
    parts.append(f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" stroke="{_INK}" stroke-width="0.5"/>')

    # series lines + endpoint labels
    for label, pts, color in series:
        if len(pts) < 2:
            continue
        d_parts = []
        for i, (x, y) in enumerate(pts):
            d_parts.append(f"{'M' if i == 0 else 'L'}{sx(x):.1f},{sy(y):.1f}")
        parts.append(f'<path d="{" ".join(d_parts)}" fill="none" stroke="{color}" stroke-width="1.4"/>')
        last_x, last_y = pts[-1]
        parts.append(f'<text x="{sx(last_x) + 4}" y="{sy(last_y) + 4}" fill="{color}" font-size="10">'
                     f'{_html.escape(label)} {y_format.format(last_y)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _equity_chart(history: list[EquityPoint], spy_curve: list[tuple[str, float]],
                  width: int = 720, height: int = 220) -> str:
    if len(history) < 2:
        return '<p style="color:#666;font-style:italic">No track record yet.</p>'
    base = history[0].equity
    if base <= 0:
        return ""
    port_pts = [(i, h.equity / base - 1.0) for i, h in enumerate(history)]
    series = [("portfolio", port_pts, _ACCENT)]
    if spy_curve:
        idx_by_date = {h.date: i for i, h in enumerate(history)}
        spy_pts = []
        for d, r in spy_curve:
            if d in idx_by_date:
                spy_pts.append((idx_by_date[d], r))
        if len(spy_pts) >= 2:
            series.append(("SPY", spy_pts, _MUTED))
    return _svg_line_chart(width, height, series,
                           title="Cumulative return since inception")


def _drawdown_chart(history: list[EquityPoint],
                    width: int = 720, height: int = 120) -> str:
    if len(history) < 2:
        return ""
    peak = 0.0
    pts = []
    for i, h in enumerate(history):
        peak = max(peak, h.equity)
        if peak <= 0:
            continue
        pts.append((i, -(peak - h.equity) / peak))
    return _svg_line_chart(width, height, [("drawdown", pts, _NEG)],
                           title="Drawdown from peak", y_format="{:.1%}")


# --- log tail ---------------------------------------------------------------

def _read_log(path: str, tail: int = 30) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return rows[-tail:]


def _spy_history_from_log(rows: list[dict]) -> list[tuple[str, float]]:
    out = []
    for r in rows:
        b = r.get("benchmark_cum_return", "")
        if b:
            try:
                out.append((r["date"], float(b)))
            except ValueError:
                continue
    return out


# --- the page ---------------------------------------------------------------

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  font-family: "Iowan Old Style", "Charter", Georgia, serif;
  background: #fafaf7; color: #1a1a1a;
  max-width: 860px; margin: 0 auto; padding: 56px 32px 80px;
  line-height: 1.55;
}
header { border-bottom: 1px solid #1a1a1a; padding-bottom: 18px; margin-bottom: 36px; }
header .eyebrow { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: #666; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }
header h1 { font-size: 30px; margin: 6px 0 0; font-weight: 600; letter-spacing: -0.01em; }
header .meta { margin-top: 8px; color: #666; font-size: 14px; }
h2 { font-size: 17px; font-weight: 600; margin: 36px 0 12px; padding-bottom: 4px; border-bottom: 1px solid #dcdcdc; letter-spacing: -0.005em; }
.kpi-row { display: flex; gap: 28px; margin: 16px 0 8px; flex-wrap: wrap; }
.kpi { min-width: 110px; }
.kpi .label { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #666; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }
.kpi .value { font-size: 22px; font-weight: 500; margin-top: 2px; }
.kpi .value.pos { color: #1a7d3a; }
.kpi .value.neg { color: #a83232; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }
table th { text-align: left; font-weight: 500; color: #666; border-bottom: 1px solid #1a1a1a; padding: 8px 10px; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }
table td { padding: 8px 10px; border-bottom: 1px solid #ececec; vertical-align: top; }
table tr:last-child td { border-bottom: none; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.tag { display: inline-block; padding: 1px 6px; border-radius: 2px; font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase; font-weight: 500; }
.tag.buy  { background: #e7f1ea; color: #1a5d2a; }
.tag.sell { background: #f3e7e7; color: #802222; }
.tag.rejected { background: #fdf0d3; color: #6b4a00; }
.tag.filled { background: #e7e9f1; color: #2b3b66; }
.rationale { color: #444; font-size: 12px; margin-top: 2px; }
.muted { color: #666; }
.empty { color: #888; font-style: italic; padding: 12px 0; }
.verdict { padding: 14px 16px; border-left: 3px solid #1a1a1a; background: #fff; margin: 14px 0 0; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }
.verdict .label { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #666; }
.verdict .head { font-size: 16px; font-weight: 600; margin-top: 2px; }
.verdict.ok      { border-left-color: #1a7d3a; }
.verdict.ok      .head { color: #1a7d3a; }
.verdict.watch   { border-left-color: #b88216; }
.verdict.watch   .head { color: #8a5e0a; }
.verdict.iterate { border-left-color: #a83232; }
.verdict.iterate .head { color: #a83232; }
.verdict .reason { color: #444; margin-top: 4px; font-size: 13px; }
.verdict .stats  { color: #666; font-size: 12px; margin-top: 8px; font-variant-numeric: tabular-nums; }
footer { margin-top: 56px; padding-top: 16px; border-top: 1px solid #dcdcdc; color: #888; font-size: 11px; font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }
"""


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _kpi(label: str, value_html: str) -> str:
    return f'<div class="kpi"><div class="label">{label}</div><div class="value">{value_html}</div></div>'


def _signed_kpi(label: str, x: float, formatter=_fmt_pct) -> str:
    cls = "pos" if x > 0 else ("neg" if x < 0 else "")
    return (f'<div class="kpi"><div class="label">{label}</div>'
            f'<div class="value {cls}">{formatter(x)}</div></div>')


def _tickets_table(tickets: list[Ticket]) -> str:
    if not tickets:
        return '<div class="empty">No tickets — portfolio is already at target.</div>'
    rows = []
    for t in tickets:
        side_class = "buy" if t.side == "BUY" else "sell"
        if t.status == "rejected":
            side_class = "rejected"
        rows.append(
            f'<tr>'
            f'<td><span class="tag {side_class}">{t.status if t.status != "pending" else t.side}</span></td>'
            f'<td><strong>{_html.escape(t.symbol)}</strong></td>'
            f'<td class="num">{t.qty}</td>'
            f'<td class="num">${t.ref_price:,.2f}</td>'
            f'<td class="num">${t.qty * t.ref_price:,.0f}</td>'
            f'<td><div class="rationale">{_html.escape(t.rationale)}</div></td>'
            f'</tr>'
        )
    return ('<table><thead><tr><th></th><th>Symbol</th><th class="num">Qty</th>'
            '<th class="num">Ref price</th><th class="num">Notional</th>'
            '<th>Rationale</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>')


def _fills_table(filled_today: list[Ticket]) -> str:
    if not filled_today:
        return '<div class="empty">No fills.</div>'
    rows = []
    for t in filled_today:
        rows.append(
            f'<tr>'
            f'<td><span class="tag {"buy" if t.side == "BUY" else "sell"}">{t.side}</span></td>'
            f'<td><strong>{_html.escape(t.symbol)}</strong></td>'
            f'<td class="num">{t.qty}</td>'
            f'<td class="num">${t.ref_price:,.2f}</td>'
            f'<td class="num">${t.fill_price:,.2f}</td>'
            f'<td class="num">{(t.fill_price - t.ref_price) * (1 if t.side == "BUY" else -1):+.4f}</td>'
            f'</tr>'
        )
    return ('<table><thead><tr><th></th><th>Symbol</th><th class="num">Qty</th>'
            '<th class="num">Ref</th><th class="num">Fill</th>'
            '<th class="num">Slippage</th></tr></thead><tbody>'
            + "".join(rows) + '</tbody></table>')


def _holdings_table(pf: Portfolio, prices: dict[str, float]) -> str:
    if not pf.positions:
        return '<div class="empty">All cash.</div>'
    rows = []
    for sym, p in sorted(pf.positions.items()):
        if not p.qty:
            continue
        px = prices.get(sym, p.avg_cost)
        mv = p.qty * px
        unreal = (px - p.avg_cost) * p.qty
        unreal_cls = "pos" if unreal > 0 else ("neg" if unreal < 0 else "")
        rows.append(
            f'<tr><td><strong>{_html.escape(sym)}</strong></td>'
            f'<td class="num">{p.qty}</td>'
            f'<td class="num">${p.avg_cost:,.2f}</td>'
            f'<td class="num">${px:,.2f}</td>'
            f'<td class="num">${mv:,.2f}</td>'
            f'<td class="num {unreal_cls}">{unreal:+,.2f}</td></tr>'
        )
    return ('<table><thead><tr><th>Symbol</th><th class="num">Qty</th>'
            '<th class="num">Avg cost</th><th class="num">Last</th>'
            '<th class="num">Market value</th><th class="num">Unrealized</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>')


def _verdict_card(d) -> str:
    """Compact 'right path or iterate' card driven by fund.decision.evaluate."""
    if d.n_days == 0:
        return ('<div class="verdict ok"><div class="label">Decision</div>'
                '<div class="head">No track record yet</div>'
                '<div class="reason">Run the loop for a few days before any verdict means anything.</div>'
                '</div>')
    cls = d.verdict
    head = {"ok": "On track", "watch": "Watching", "iterate": "Consider iterating"}[cls]
    return (
        f'<div class="verdict {cls}">'
        f'<div class="label">Decision &middot; {d.n_days}-day trailing</div>'
        f'<div class="head">{head}</div>'
        f'<div class="reason">{_html.escape(d.reason)}</div>'
        f'<div class="stats">'
        f'portfolio {d.trailing_return * 100:+.2f}%  &middot;  '
        f'SPY {d.trailing_benchmark * 100:+.2f}%  &middot;  '
        f'excess {d.trailing_excess * 100:+.2f}pp  &middot;  '
        f'hit rate {d.hit_rate * 100:.0f}%  &middot;  '
        f'worst day {d.worst_day * 100:+.2f}%  &middot;  '
        f'dd -{d.current_drawdown * 100:.2f}%'
        f'</div></div>'
    )


def _log_table(rows: list[dict], n: int = 14) -> str:
    if not rows:
        return '<div class="empty">No closeouts logged yet.</div>'
    tail = rows[-n:][::-1]
    body = []
    for r in tail:
        day_r = float(r.get("day_return") or 0)
        cum_r = float(r.get("cum_return") or 0)
        bench = float(r.get("benchmark_cum_return") or 0) if r.get("benchmark_cum_return") else None
        excess = (cum_r - bench) if bench is not None else None
        body.append(
            f'<tr><td>{r["date"]}</td>'
            f'<td class="num {"pos" if day_r > 0 else ("neg" if day_r < 0 else "")}">{day_r * 100:+.2f}%</td>'
            f'<td class="num">{cum_r * 100:+.2f}%</td>'
            f'<td class="num muted">{(bench * 100):+.2f}%</td>'
            f'<td class="num {"pos" if (excess or 0) > 0 else ("neg" if (excess or 0) < 0 else "")}">'
            f'{(excess * 100):+.2f}%</td>'
            f'<td class="num">${float(r["equity"]):,.0f}</td>'
            f'</tr>'
        ) if bench is not None else body.append(
            f'<tr><td>{r["date"]}</td>'
            f'<td class="num">{day_r * 100:+.2f}%</td>'
            f'<td class="num">{cum_r * 100:+.2f}%</td>'
            f'<td class="num muted">—</td><td class="num">—</td>'
            f'<td class="num">${float(r["equity"]):,.0f}</td></tr>'
        )
    return ('<table><thead><tr><th>Date</th><th class="num">Day</th>'
            '<th class="num">Cum</th><th class="num">SPY</th>'
            '<th class="num">Excess</th><th class="num">Equity</th>'
            '</tr></thead><tbody>' + "".join(body) + '</tbody></table>')


def render(pf: Portfolio, *, today_tickets: list[Ticket] | None = None,
           prices: dict[str, float] | None = None,
           daily_log_path: str | None = None,
           as_of: date | None = None) -> str:
    today_tickets = today_tickets or []
    prices = prices or {}
    as_of = as_of or date.today()
    log_rows = _read_log(daily_log_path) if daily_log_path else []
    spy_curve = _spy_history_from_log(log_rows)

    equity = pf.equity(prices) if prices else (pf.history[-1].equity if pf.history else pf.cash)
    cum = (equity / pf.principal - 1.0) if pf.principal > 0 else 0.0
    day_ret = 0.0
    if log_rows:
        try:
            day_ret = float(log_rows[-1].get("day_return") or 0)
        except ValueError:
            day_ret = 0.0
    peak = max((h.equity for h in pf.history), default=equity)
    dd = max(0.0, (peak - equity) / peak) if peak > 0 else 0.0

    fills_today = [t for t in pf.filled if t.fill_date == as_of.isoformat()]

    equity_svg = _equity_chart(pf.history, spy_curve)
    dd_svg = _drawdown_chart(pf.history)

    decision = evaluate_decision(log_rows, DecisionConfig())
    verdict_html = _verdict_card(decision)

    strategy_label = pf.active_strategy
    if pf.active_strategy_params:
        strategy_label += " " + ", ".join(f"{k}={v}" for k, v in pf.active_strategy_params.items())

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Daily — {as_of.isoformat()}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="eyebrow">Daily research note</div>
  <h1>{as_of.strftime('%A, %B %-d, %Y')}</h1>
  <div class="meta">Strategy: <strong>{_html.escape(strategy_label)}</strong>
   &middot; Inception {pf.inception or "—"}
   &middot; Principal ${pf.principal:,.0f}</div>
</header>

<div class="kpi-row">
  {_kpi("Equity", _fmt_money(equity))}
  {_signed_kpi("Today", day_ret)}
  {_signed_kpi("Since inception", cum)}
  {_kpi("Drawdown", f'<span class="neg">-{dd * 100:.2f}%</span>' if dd > 0 else "0.00%")}
  {_kpi("Cash", _fmt_money(pf.cash))}
</div>

{verdict_html}

<h2>Track record</h2>
{equity_svg}
{dd_svg}

<h2>Today's guide — {as_of.isoformat()}</h2>
{_tickets_table(today_tickets)}

<h2>Holdings</h2>
{_holdings_table(pf, prices)}

<h2>Today's fills</h2>
{_fills_table(fills_today)}

<h2>Last 14 days</h2>
{_log_table(log_rows)}

<footer>
Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.
This is paper research. Every live order remains human-gated per <code>fund.md</code> §7.
</footer>
</body>
</html>
"""
    return html


def write(pf: Portfolio, *, today_tickets: list[Ticket] | None = None,
          prices: dict[str, float] | None = None,
          daily_log_path: str | None = None,
          as_of: date | None = None,
          path: str = REPORT_PATH) -> str:
    html = render(pf, today_tickets=today_tickets, prices=prices,
                  daily_log_path=daily_log_path, as_of=as_of)
    with open(path, "w") as f:
        f.write(html)
    return path
