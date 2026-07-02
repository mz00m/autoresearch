"""cancel_orders.py — DELETE every open order at the broker, period.

Use when:
  * You fired tickets sized for the wrong equity (local state was stale).
  * A rotation included phantom SELLs the broker hasn't rejected yet.
  * You changed your mind before the open and want a clean slate.

Doesn't touch positions. Doesn't touch local state. Just cancels every
broker-side open order. Pair with `fund.sync_from_broker` after to get
the local view back in lockstep.

    python3 -m fund.cancel_orders --broker alpaca           # interactive
    python3 -m fund.cancel_orders --broker alpaca --yes     # no prompt
    python3 -m fund.cancel_orders --broker alpaca --dry-run # list only
"""

from __future__ import annotations

import argparse
import sys

from fund.brokers import load_broker


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Cancel every open order at the broker.")
    ap.add_argument("--broker", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    broker = load_broker(args.broker)
    if not hasattr(broker, "cancel_open_orders"):
        print(f"{args.broker} adapter doesn't implement cancel_open_orders yet.")
        return 2

    if args.dry_run:
        # Use a probe — we know cancel_open_orders returns the list it would
        # have hit. Call it once with no actual deletes by introspecting the
        # underlying _req. Simpler: just list orders via account_snapshot-ish.
        try:
            from fund.brokers.alpaca import AlpacaBroker
            if isinstance(broker, AlpacaBroker):
                opens = broker._req("GET", "/v2/orders",
                                    params={"status": "open", "limit": "500"})
                if not opens:
                    print("(no open orders)")
                else:
                    print(f"Would cancel {len(opens)} order(s):")
                    for o in opens:
                        print(f"  {o.get('side','?'):>4} {o.get('qty'):>6} "
                              f"{o.get('symbol','?'):<5} "
                              f"client_id={o.get('client_order_id','')}")
                return 0
        except Exception as e:
            print(f"dry-run probe failed: {e}")
            return 3

    if not args.yes:
        if not _confirm(f"Cancel ALL open orders at {args.broker}?"):
            print("aborted.")
            return 1

    result = broker.cancel_open_orders()   # type: ignore[attr-defined]
    print(f"\nCanceled {result['canceled']} order(s).")
    for stub in result.get("would_have_canceled", []):
        print(f"  {stub.get('side','?'):>4} {stub.get('qty'):>6} "
              f"{stub.get('symbol','?'):<5} "
              f"client_id={stub.get('client_order_id','')}")
    if result.get("errors"):
        print("\nErrors:")
        for e in result["errors"]:
            print(f"  {e}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
