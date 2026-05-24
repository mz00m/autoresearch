"""Multi-day simulator — replay the morning/closeout loop on real history.

Builds up ``portfolio_state.json`` + ``daily_log.tsv`` as if Matt had been
running the daily ops loop for the last N trading days. Convention mirrors
real life:

  * Morning runs against ``as_of = previous trading day`` close
    (the reference price the human would see before market open).
  * Closeout fills at the actual ``as_of = today`` close.

This intentionally exposes the one-day stale-price drag, so the simulated
P&L matches what the real loop will produce — no friction-free idealization.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

from fund.closeout import close_out
from fund.daily_report import write as write_report, REPORT_PATH
from fund.data.loader import load_panel
from fund.morning import generate_tickets
from fund.portfolio import Portfolio, STATE_PATH
from fund.strategy.registry import build as build_strategy, universe_for


def _trading_days(panel, start: date, end: date) -> list[date]:
    """Calendar dates with SPY (or any common symbol) closes in [start, end]."""
    spy = panel.series.get("SPY") or next(iter(panel.series.values()))
    return [d for d in spy.dates if start <= d <= end]


def _previous_trading_day(panel, on: date) -> date | None:
    spy = panel.series.get("SPY") or next(iter(panel.series.values()))
    prior = [d for d in spy.dates if d < on]
    return prior[-1] if prior else None


def simulate(*, days: int = 30, end: date | None = None,
             principal: float = 25_000.0,
             strategy: str = "sixty_forty",
             strategy_params: dict | None = None,
             source: str = "auto",
             state_path: str = STATE_PATH,
             log_path: str | None = None,
             quiet: bool = False) -> tuple[Portfolio, list[date]]:
    """Run a clean simulation. Always starts from a fresh portfolio."""
    from fund.closeout import DAILY_LOG
    log_path = log_path or DAILY_LOG

    end = end or date.today()
    # Preload enough history so the strategy has its lookback window already.
    symbols = sorted(set(universe_for(strategy, strategy_params)) | {"SPY"})
    panel, _ = load_panel(symbols, date(2005, 1, 1), end, source=source)
    trading = _trading_days(panel, end - timedelta(days=int(days * 1.8) + 14), end)
    if len(trading) < days + 1:
        raise RuntimeError(f"only {len(trading)} trading days in window; need {days + 1}")
    sim_days = trading[-(days + 1):]   # the +1 is the inception "day 0"
    inception = sim_days[0]

    # Fresh state + clean log.
    if os.path.exists(state_path):
        os.remove(state_path)
    if os.path.exists(log_path):
        os.remove(log_path)
    pf = Portfolio.fresh(principal, inception, strategy=strategy,
                         params=strategy_params)
    pf.save(state_path)

    if not quiet:
        print(f"sim: {strategy} | inception {inception} -> {end} "
              f"| {len(sim_days) - 1} trading days | principal ${principal:,.0f}")

    # Day 0: just mark to market so we have an anchor in history.
    pf = Portfolio.load(state_path)
    # initialize history at inception with 100% cash
    pf.mark_to_market({}, inception)
    pf.save(state_path)

    for d in sim_days[1:]:
        prev = _previous_trading_day(panel, d) or d
        # MORNING — size against previous close.
        pf = Portfolio.load(state_path)
        pf, tickets, prices_ref = generate_tickets(pf, prev, source=source)
        pf.save(state_path)
        # CLOSEOUT — fill at today's close.
        pf = Portfolio.load(state_path)
        pf, row, prices_close = close_out(pf, d, source=source)
        pf.save(state_path)
        if not quiet and row:
            print(f"  {d}  day {float(row['day_return']) * 100:+5.2f}%  "
                  f"cum {float(row['cum_return']) * 100:+6.2f}%  "
                  f"vs SPY "
                  + (f"{float(row['benchmark_cum_return']) * 100:+6.2f}%"
                     if row['benchmark_cum_return'] else "  n/a")
                  + f"  eq ${float(row['equity']):>10,.0f}  "
                  f"fills {row['n_filled']} rej {row['n_rejected']}")

    return pf, sim_days


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulate N trading days.")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--end", type=str, default="",
                    help="ISO date (default: today)")
    ap.add_argument("--principal", type=float, default=25_000.0)
    ap.add_argument("--strategy", default="sixty_forty",
                    help="sixty_forty | dual_momentum | risk_parity")
    ap.add_argument("--lookback", type=int, default=None,
                    help="dual_momentum lookback days (default 252)")
    ap.add_argument("--vol-window", type=int, default=None,
                    help="risk_parity vol estimation window (default 63)")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    end = date.fromisoformat(args.end) if args.end else date.today()
    params: dict = {}
    if args.lookback is not None:
        params["lookback_days"] = args.lookback
    if args.vol_window is not None:
        params["vol_window"] = args.vol_window

    pf, _ = simulate(days=args.days, end=end, principal=args.principal,
                     strategy=args.strategy, strategy_params=params,
                     source=args.source, quiet=args.quiet)

    if not args.no_report:
        # Re-derive today's tickets + prices for the report.
        from fund.closeout import DAILY_LOG
        # If today's a trading day, generate fresh tickets for the next session.
        try:
            pf, tickets, ref_prices = generate_tickets(pf, end, source=args.source)
            pf.save()
        except Exception as e:
            tickets, ref_prices = [], {}
        path = write_report(pf, today_tickets=tickets, prices=ref_prices,
                            daily_log_path=DAILY_LOG, as_of=end)
        if not args.quiet:
            print(f"\nreport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
