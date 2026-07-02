"""place_stops.py — submit a GTC trailing-stop SELL for each held position.

Run after fills land so positions are real at the broker. For each open
position, places ONE trailing-stop SELL good-till-cancelled at the broker.
If a stop already exists for the symbol, it's left alone (no doubles).

The trailing stop re-anchors automatically as price rises — broker math,
zero polling on our side. If price drops `trail_percent` from its rolling
peak, the broker fires a market sell. Default trail = 15%, matches the
sell_guide's default. Tighten with --trail for more aggressive locking.

  python3 -m fund.place_stops --broker alpaca                # 15% trail
  python3 -m fund.place_stops --broker alpaca --trail 10     # 10% trail
  python3 -m fund.place_stops --broker alpaca --dry-run

This is the missing piece between morning (BUY tickets fired) and the
strategy-exit signal (rotation tickets from the next morning). With the
trailing stops in place, you're protected against an overnight gap or
intraday rout even if you forget to run morning the next day.
"""

from __future__ import annotations

import argparse
import json
import sys

from fund.brokers import load_broker
from fund.portfolio import Portfolio

DEFAULT_TRAIL_PCT = 15.0

# Per-symbol trail overrides — used when --trail isn't passed. Calibrated
# so a typical 1-2 day move doesn't whipsaw the stop. Tighter than 15%
# only where the underlying has low realized vol.
PER_SYMBOL_TRAIL: dict[str, float] = {
    # 3x leveraged equity — 5% underlying ≈ 15% on the ETF
    "TQQQ": 15.0, "SOXL": 15.0, "UPRO": 15.0,
    # 3x leveraged bond / 2x leveraged gold
    "TMF": 18.0, "UGL": 12.0,
    # High-vol single-commodity ETFs
    "USO": 10.0, "URA": 12.0,
    # Sector ETFs (moderate vol)
    "XLE": 10.0,
    # Broad equity / crypto
    "SPY": 8.0, "QQQ": 9.0, "EFA": 8.0, "IWM": 10.0, "BITO": 18.0,
    # Bonds, gold, cash-like (low vol)
    "AGG": 5.0, "TLT": 8.0, "GLD": 8.0, "BIL": 3.0,
}


def _confirm(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _trail_for(symbol: str, override: float | None) -> float:
    """If user passed --trail, that wins. Else per-symbol; else default."""
    if override is not None:
        return override
    return PER_SYMBOL_TRAIL.get(symbol.upper(), DEFAULT_TRAIL_PCT)


def main() -> int:
    ap = argparse.ArgumentParser(description="GTC trailing-stop on every position.")
    ap.add_argument("--broker", required=True, help="alpaca | ibkr (alpaca only for now)")
    ap.add_argument("--trail", type=float, default=None,
                    help=f"override trailing percent (default = per-symbol table; "
                         f"fallback {DEFAULT_TRAIL_PCT})")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.broker != "alpaca":
        print("place_stops currently supports Alpaca only "
              "(IBKR has different stop-order plumbing — wire next).")
        return 2

    broker = load_broker(args.broker)
    if not hasattr(broker, "place_trailing_stop"):
        print(f"{args.broker} adapter doesn't expose place_trailing_stop yet.")
        return 2

    snap = broker.account_snapshot()
    held = {sym: qty for sym, qty in snap.positions.items() if qty != 0}
    if not held:
        print("no broker-side positions — nothing to protect.")
        return 0

    print(f"\nWould place trailing-stop SELL on:")
    plan: list[tuple[str, int, float]] = []
    for sym, qty in sorted(held.items()):
        existing = broker.open_stops_for(sym)   # type: ignore[attr-defined]
        if existing:
            print(f"  - {sym}  qty {qty}  SKIP (already has "
                  f"{len(existing)} open stop order)")
            continue
        trail = _trail_for(sym, args.trail)
        print(f"  - {sym}  qty {qty}  @ {trail}% trail")
        plan.append((sym, int(qty), trail))

    if not plan:
        print("\nevery position already has a stop. nothing to do.")
        return 0

    if args.dry_run:
        print("\n--dry-run: no orders submitted.")
        return 0
    if not args.yes:
        if not _confirm("\nSubmit these trailing-stops now?"):
            print("aborted.")
            return 1

    placed = 0
    errors: list[str] = []
    for sym, qty, trail in plan:
        result = broker.place_trailing_stop(   # type: ignore[attr-defined]
            sym, qty, trail,
            client_id=f"fund-trail-{sym.lower()}",
        )
        if "error" in result:
            errors.append(f"{sym}: {result['error']}")
            print(f"  X {sym}: {result['error']}")
        else:
            placed += 1
            print(f"  -> {sym}  order_id={result.get('id','?')}  "
                  f"trail {trail}%")

    print(f"\n{placed} trailing-stop(s) submitted, {len(errors)} error(s).")
    if errors:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
