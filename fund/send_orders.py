"""send_orders.py — the human-approved bridge from tickets to a broker.

Reads pending tickets from ``portfolio_state.json``, sends each one through
the chosen broker, and records the broker's order ID back on the ticket. By
default this is **interactive**: every order requires the human to type "y"
before it fires, mirroring fund.md §7 ("Execution is human-gated").

Use ``--yes`` to fire the whole batch without prompts — only after you've
read the morning card and want to send the slate as-is. Use ``--dry-run``
to print what would happen without contacting the broker.

This does NOT mark tickets as filled. Fills are reported asynchronously by
the broker — run ``python3 -m fund.reconcile`` (or just the regular
``closeout``) to pull fills back into portfolio state.
"""

from __future__ import annotations

import argparse
import sys

from fund.brokers import load_broker
from fund.portfolio import Portfolio


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans == "y" or ans == "yes"


def main() -> int:
    ap = argparse.ArgumentParser(description="Send pending tickets to a broker.")
    ap.add_argument("--broker", required=True,
                    help="alpaca | ibkr")
    ap.add_argument("--yes", action="store_true",
                    help="fire all orders without per-ticket confirmation")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent, contact no broker")
    args = ap.parse_args()

    pf = Portfolio.load()
    if not pf.pending:
        print("no pending tickets — run `python3 -m fund.morning` first.")
        return 0

    print(f"\n{len(pf.pending)} pending ticket(s) for {pf.active_strategy}:")
    for t in pf.pending:
        notional = t.qty * t.ref_price
        qty_str = (f"{int(t.qty):>5d}" if t.qty == int(t.qty)
                   else f"{t.qty:>8.4f}")
        print(f"  {t.side:4s} {qty_str} {t.symbol:<5s} ~${t.ref_price:,.2f}"
              f"   ${notional:,.0f}   {t.rationale[:60]}")

    if args.dry_run:
        print("\n--dry-run: nothing sent.")
        return 0

    if not args.yes:
        if not _confirm("\nSend all of these now?"):
            print("aborted by user — nothing sent.")
            return 1

    try:
        broker = load_broker(args.broker)
    except Exception as e:
        print(f"could not load broker '{args.broker}': {e}")
        return 2

    sent = rejected = 0
    print(f"\nrouting via {broker.name}...")
    for t in pf.pending:
        if not args.yes:
            ok = _confirm(f"  send {t.side} {t.qty} {t.symbol}?")
            if not ok:
                print(f"    skipped {t.ticket_id}")
                continue
        ack = broker.place_order(t)
        if ack.status == "pending":
            # Stash the broker order id in the ticket note for reconciliation.
            t.rationale = f"[broker:{broker.name}:{ack.broker_order_id}] " + t.rationale
            print(f"    sent  {t.side} {t.qty} {t.symbol} -> {ack.broker_order_id}")
            sent += 1
        else:
            t.status = "rejected"
            t.rationale = f"BROKER REJECTED: {ack.reason}"
            print(f"    REJECTED {t.symbol}: {ack.reason}")
            rejected += 1

    # Drop rejected from pending; broker now owns the sent ones.
    pf.pending = [t for t in pf.pending if t.status == "pending"]
    pf.save()
    print(f"\n{sent} sent, {rejected} rejected. "
          f"Wait for the close, then `python3 -m fund.reconcile --broker {broker.name}`"
          f" (or `closeout` if you're sticking with simulated fills).")
    return 0 if rejected == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
