"""reconcile.py — pull real broker fills back into portfolio state.

When you fire orders via ``fund.send_orders``, the broker takes ownership of
them and reports fills asynchronously. This module reads those fills back
out, matches each one to a ticket (via the ``fund-<ticket_id>`` client-order-id
threaded through at submission), and applies it to the paper portfolio —
exactly like ``closeout`` would, but using the broker's actual fill price
instead of a synthetic close.

If a ticket has been live with the broker but never filled (canceled, expired,
or just stuck in queue), it's marked ``expired`` so it stops counting against
the next morning's diff.

Run order:

    python3 -m fund.morning                       # writes pending tickets
    python3 -m fund.send_orders --broker alpaca   # broker takes them
    # ... time passes, market trades ...
    python3 -m fund.reconcile --broker alpaca     # broker fills -> portfolio
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone

from fund.brokers import load_broker
from fund.closeout import _append_log, DAILY_LOG
from fund.portfolio import Portfolio


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile broker fills into state.")
    ap.add_argument("--broker", required=True, help="alpaca | ibkr")
    ap.add_argument("--since", type=str, default="",
                    help="ISO date (default: today). Pull fills since this date.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    since = date.fromisoformat(args.since) if args.since else date.today()

    try:
        broker = load_broker(args.broker)
    except Exception as e:
        print(f"could not load broker '{args.broker}': {e}")
        return 2

    pf = Portfolio.load()
    if not pf.pending:
        if not args.quiet:
            print(f"no pending tickets to reconcile against.")
        return 0

    fills = broker.fills_since(since)
    by_ticket = {f.ticket_id: f for f in fills if f.ticket_id}
    matched = unmatched = 0
    today = date.today()

    for t in list(pf.pending):
        f = by_ticket.get(t.ticket_id)
        if not f:
            continue
        # Use broker's actual fill price; slippage is whatever it was.
        pf.apply_fill(t, fill_price=f.fill_price, on=today, slippage_bps=0)
        # apply_fill clears t.status; record the broker order id too.
        t.rationale = (f"[broker:{broker.name}:{f.broker_order_id} @ "
                       f"${f.fill_price:.4f}] " + t.rationale)
        matched += 1
        if not args.quiet:
            print(f"  filled {t.side} {t.qty} {t.symbol} @ ${f.fill_price:.4f}"
                  f" via {broker.name} ({f.broker_order_id})")

    # Anything still pending after the reconcile window expires.
    leftover = [t for t in pf.pending if t.status == "pending"]
    for t in leftover:
        t.status = "expired"
        unmatched += 1
        if not args.quiet:
            print(f"  expired {t.side} {t.qty} {t.symbol} — broker reported no fill")
    pf.pending = []

    # Mark and log if we filled anything.
    if matched:
        # Mark to market using fill prices we just saw.
        prices = {f.symbol: f.fill_price for f in fills}
        pt = pf.mark_to_market(prices, today)
        # day return
        day_ret = 0.0
        if len(pf.history) >= 2 and pf.history[-2].equity > 0:
            day_ret = pt.equity / pf.history[-2].equity - 1.0
        peak = max(h.equity for h in pf.history)
        dd = max(0.0, (peak - pt.equity) / peak) if peak > 0 else 0.0
        _append_log({
            "date": today.isoformat(), "strategy": pf.active_strategy,
            "cash": round(pf.cash, 2),
            "position_value": round(pt.position_value, 2),
            "equity": round(pt.equity, 2),
            "day_return": f"{day_ret:.6f}",
            "cum_return": f"{(pt.equity / pf.principal - 1.0):.6f}"
                          if pf.principal > 0 else "0.0",
            "benchmark_cum_return": "",
            "drawdown": f"{dd:.6f}",
            "n_filled": matched, "n_rejected": 0, "n_expired": unmatched,
            "note": f"reconcile/{broker.name}",
        }, DAILY_LOG)

    pf.save()
    if not args.quiet:
        print(f"\n{matched} filled, {unmatched} expired. "
              f"Open the dashboard to see the updated book.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
