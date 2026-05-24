"""End-of-day closeout — fill pending tickets, mark book, record the day.

Run after the close. Fetches today's actual close for every symbol the book
touches, fills each pending morning ticket at that close (with the same
slippage assumption the backtest uses), marks the portfolio to market, and
appends one immutable row to ``daily_log.tsv``.

The daily log is the operational analog of ``research_ledger.tsv``: every row
is "what we did today and what it earned us." Drift = live row vs. backtest
expectation for the same window. If drift exceeds the band for too long, the
scorer is being gamed — see fund.md §5.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date

from fund.data.loader import load_panel
from fund.portfolio import Portfolio, cumulative_return
from fund.strategy.registry import universe_for

DAILY_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "daily_log.tsv")

LOG_FIELDS = [
    "date", "strategy", "cash", "position_value", "equity",
    "day_return", "cum_return", "benchmark_cum_return", "drawdown",
    "n_filled", "n_rejected", "n_expired", "note",
]


def _ensure_header(path: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            csv.writer(f, delimiter="\t").writerow(LOG_FIELDS)


def _append_log(row: dict, path: str = DAILY_LOG) -> None:
    _ensure_header(path)
    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=LOG_FIELDS, delimiter="\t").writerow(row)


def _close_prices(panel, on: date) -> dict[str, float]:
    out: dict[str, float] = {}
    for sym, ps in panel.series.items():
        sub = ps.as_of(on)
        if sub.last is not None and sub.dates and sub.dates[-1] == on:
            out[sym] = sub.last
    return out


def _spy_cum_return(panel, inception_iso: str, on: date) -> float | None:
    """SPY total return from the inception close to `on` close. The reference
    is the SPY close ON (or the last close before) the inception date — not the
    first datapoint in the panel — so portfolio vs benchmark are anchored at
    the same starting line."""
    spy = panel.series.get("SPY")
    if spy is None or not inception_iso:
        return None
    start = spy.as_of(date.fromisoformat(inception_iso))
    end = spy.as_of(on)
    if not start.closes or not end.closes:
        return None
    base = start.closes[-1]
    if base <= 0:
        return None
    return end.closes[-1] / base - 1.0


def close_out(pf: Portfolio, as_of: date, *,
              source: str = "auto", slippage_bps: float = 5.0
              ) -> tuple[Portfolio, dict, dict]:
    """Fill pending tickets at `as_of` close, mark to market, record the day."""
    # Always include SPY for the benchmark even if the strategy doesn't use it.
    symbols = sorted(set(universe_for(pf.active_strategy,
                                      pf.active_strategy_params))
                     | {"SPY"} | set(pf.positions))
    panel, _ = load_panel(symbols, date(2005, 1, 1), as_of, source=source)
    close = _close_prices(panel, as_of)
    if "SPY" not in close and not pf.pending:
        # No close yet (weekend / holiday) and nothing to do — no-op day.
        return pf, {}, close

    # Fill tickets at today's close.
    n_filled = n_rejected = 0
    for t in list(pf.pending):
        px = close.get(t.symbol)
        if px is None:
            t.status = "expired"
            continue
        try:
            pf.apply_fill(t, fill_price=px, on=as_of, slippage_bps=slippage_bps)
            if t.status == "filled":
                n_filled += 1
            else:
                n_rejected += 1
        except Exception:
            t.status = "rejected"
            n_rejected += 1
    n_expired = sum(1 for t in pf.pending if t.status == "expired")
    pf.pending = []  # all morning tickets are resolved one way or the other

    # Mark book at the new close.
    pt = pf.mark_to_market(close, as_of)
    cum = cumulative_return(pf.history)
    bench = _spy_cum_return(panel, pf.inception, as_of)

    # Day return = today's equity / yesterday's equity - 1
    day_ret = 0.0
    if len(pf.history) >= 2:
        prev = pf.history[-2].equity
        if prev > 0:
            day_ret = pt.equity / prev - 1.0

    # Current drawdown from peak
    peak = max(h.equity for h in pf.history)
    dd = max(0.0, (peak - pt.equity) / peak) if peak > 0 else 0.0

    row = {
        "date": as_of.isoformat(), "strategy": pf.active_strategy,
        "cash": round(pf.cash, 2), "position_value": round(pt.position_value, 2),
        "equity": round(pt.equity, 2),
        "day_return": f"{day_ret:.6f}",
        "cum_return": f"{cum:.6f}",
        "benchmark_cum_return": f"{bench:.6f}" if bench is not None else "",
        "drawdown": f"{dd:.6f}",
        "n_filled": n_filled, "n_rejected": n_rejected, "n_expired": n_expired,
        "note": "",
    }
    _append_log(row)
    return pf, row, close


def _print_card(pf: Portfolio, row: dict, prices: dict[str, float],
                as_of: date) -> None:
    print(f"\n=== CLOSEOUT  {as_of}  ===")
    print(f"strategy:  {pf.active_strategy}")
    print(f"equity:    ${row['equity']}  (cash ${row['cash']}, "
          f"positions ${row['position_value']})")
    print(f"day:       {float(row['day_return']) * 100:+.3f}%   "
          f"cum: {float(row['cum_return']) * 100:+.2f}%   "
          f"vs SPY: "
          + (f"{float(row['benchmark_cum_return']) * 100:+.2f}%"
             if row['benchmark_cum_return'] else "n/a")
          + f"   dd: -{float(row['drawdown']) * 100:.2f}%")
    print(f"fills:     {row['n_filled']} filled, "
          f"{row['n_rejected']} rejected, {row['n_expired']} expired")
    if pf.positions:
        held = ", ".join(f"{s} {p.qty} @ ${p.avg_cost:,.2f}"
                         for s, p in pf.positions.items() if p.qty)
        print(f"holdings:  {held}")


def main() -> int:
    ap = argparse.ArgumentParser(description="End-of-day closeout.")
    ap.add_argument("--as-of", type=str, default="",
                    help="ISO date (default: today)")
    ap.add_argument("--source", default="auto",
                    help="data source: auto | real | synthetic")
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())

    pf = Portfolio.load()
    pf, row, prices = close_out(pf, as_of, source=args.source,
                                slippage_bps=args.slippage_bps)
    if not args.quiet:
        if not row:
            print(f"closeout {as_of}: no close available yet (weekend / holiday); no-op.")
        else:
            _print_card(pf, row, prices, as_of)
    pf.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
