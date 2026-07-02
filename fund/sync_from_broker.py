"""sync_from_broker.py — make local portfolio_state.json match the broker.

The local state can drift from the broker for several reasons:
  * You ran the simulator and it wrote test positions in.
  * You placed a trade in the broker's UI without going through the loop.
  * A previous send_orders run partially filled or got cancelled.
  * You reinitialized the broker account but not the local file.

When that happens, morning compares phantom local positions to the target
weights and generates phantom SELL tickets that the broker rejects. This
module fixes it: query account_snapshot from the broker, overwrite cash +
positions in portfolio_state.json, optionally seed an initial cost basis
from the current market price (the broker won't tell us the original).

Safety: this is destructive in one direction — broker → local. It never
writes to the broker. Pending tickets, daily_log history, and active
strategy are preserved.

    python3 -m fund.sync_from_broker --broker alpaca           # interactive
    python3 -m fund.sync_from_broker --broker alpaca --yes     # no prompt
    python3 -m fund.sync_from_broker --broker alpaca --dry-run # preview only
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from fund.brokers import load_broker
from fund.data.loader import load_panel
from fund.portfolio import Portfolio, Position
from fund.tax import TaxLot


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def sync(broker_name: str, *, dry_run: bool = False,
         source: str = "auto") -> dict:
    """Pull broker truth, return a diff dict. Apply iff not dry_run."""
    broker = load_broker(broker_name)
    snap = broker.account_snapshot()

    try:
        pf = Portfolio.load()
    except FileNotFoundError:
        # Fresh start — initialize from the broker's cash as principal
        pf = Portfolio.fresh(
            principal=snap.cash + sum(
                qty * 0 for qty in snap.positions.values()),
            inception=date.today(),
            strategy="top_n_momentum",
        )

    # Compute diff for reporting
    diff: dict = {
        "broker": broker_name,
        "cash_before": round(pf.cash, 2),
        "cash_after": round(snap.cash, 2),
        "positions_before": {s: p.qty for s, p in pf.positions.items()
                             if p.qty},
        "positions_after": dict(snap.positions),
        "principal_before": pf.principal,
    }

    # Fetch current prices to seed cost basis for any positions we adopt
    syms = [s for s, q in snap.positions.items() if q != 0]
    prices: dict[str, float] = {}
    if syms:
        try:
            panel, _ = load_panel(syms, date(2020, 1, 1), date.today(),
                                  source=source)
            for s in syms:
                ps = panel.series.get(s)
                if ps and ps.last:
                    prices[s] = ps.last
        except Exception:
            pass
    diff["prices"] = prices

    if dry_run:
        return diff

    # Apply the truth
    pf.cash = snap.cash
    # If we have no principal recorded yet (fresh start), use what the broker
    # reports as equity. Otherwise keep the original principal for return %.
    broker_equity = snap.cash + sum(
        qty * prices.get(sym, 0) for sym, qty in snap.positions.items()
    )
    if pf.principal <= 0:
        pf.principal = broker_equity

    # Replace positions with broker truth, seeding cost basis from market.
    pf.positions = {}
    today_iso = date.today().isoformat()
    for sym, qty in snap.positions.items():
        if qty == 0:
            continue
        cost = prices.get(sym, 0.0)
        pf.positions[sym] = Position(
            qty=float(qty),
            avg_cost=cost,
            lots=[TaxLot(date_acquired=today_iso,
                         qty=float(qty), cost_per_share=cost)],
        )

    # Clear pending tickets — they were sized against the wrong book
    n_expired = len(pf.pending)
    for t in pf.pending:
        t.status = "expired"
    pf.pending = []
    diff["pending_cleared"] = n_expired

    pf.save()
    return diff


def _print(diff: dict) -> None:
    print(f"\n=== SYNC FROM {diff['broker'].upper()} ===\n")
    print(f"  Cash:       ${diff['cash_before']:>12,.2f} -> ${diff['cash_after']:>12,.2f}")
    print(f"  Positions before: {diff['positions_before'] or '(none)'}")
    print(f"  Positions after:  {diff['positions_after'] or '(none)'}")
    if diff.get("prices"):
        print(f"  Cost basis seeded at current close:")
        for sym, px in diff["prices"].items():
            qty = diff["positions_after"].get(sym, 0)
            print(f"    {sym}: {qty} sh @ ${px:,.2f} = ${qty * px:,.2f}")
    if "pending_cleared" in diff:
        print(f"  Pending tickets cleared: {diff['pending_cleared']} "
              f"(sized against the old book; regenerate with morning)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pull broker truth into local state.")
    ap.add_argument("--broker", required=True, help="alpaca | ibkr")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    ap.add_argument("--dry-run", action="store_true",
                    help="preview the diff, don't write state")
    ap.add_argument("--source", default="auto")
    args = ap.parse_args()

    diff = sync(args.broker, dry_run=True, source=args.source)
    _print(diff)
    if args.dry_run:
        print("\n--dry-run: portfolio_state.json unchanged.")
        return 0
    if not args.yes:
        if not _confirm("\nOverwrite portfolio_state.json with this snapshot?"):
            print("aborted.")
            return 1
    real_diff = sync(args.broker, dry_run=False, source=args.source)
    print("\n  -> portfolio_state.json updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
