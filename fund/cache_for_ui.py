"""cache_for_ui.py — compute recommendations + sell-guide once, write JSON.

The Next.js dashboard is a viewer (no Python in process). This module is the
bridge: runs both `recommendations` and `sell_guide` for the current
portfolio + as-of date, writes the combined result to `fund/ui_cache.json`,
which the UI reads via server components.

Re-run whenever you want fresh numbers:

    python3 -m fund.cache_for_ui                 # uses today + active portfolio
    python3 -m fund.cache_for_ui --as-of 2026-05-22

You can also wire this into a cron / launchd plist that runs at market close.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date, datetime

from fund.portfolio import Portfolio
from fund.recommendations import compute_all
from fund.sell_guide import compute as compute_sell

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ui_cache.json")


def build(as_of: date, *, source: str = "auto",
          pf: Portfolio | None = None) -> dict:
    if pf is None:
        try:
            pf = Portfolio.load()
        except FileNotFoundError:
            pf = None

    principal = pf.principal if pf else 25_000.0
    active = pf.active_strategy if pf else None
    active_params = pf.active_strategy_params if pf else {}

    recs = compute_all(as_of, principal=principal, source=source)

    sell_signals = []
    if pf is not None and any(p.qty for p in pf.positions.values()):
        signals, _ = compute_sell(pf, as_of, source=source)
        sell_signals = [asdict(s) for s in signals]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": recs["as_of"],
        "principal": principal,
        "active_strategy": active,
        "active_strategy_params": active_params,
        "recommendations": recs["by_strategy"],
        "prices": recs["prices"],
        "sell_signals": sell_signals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Cache rec+sell for the UI.")
    ap.add_argument("--as-of", type=str, default="")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--out", default=CACHE_PATH)
    args = ap.parse_args()

    as_of = (date.fromisoformat(args.as_of) if args.as_of else date.today())
    cache = build(as_of, source=args.source)
    with open(args.out, "w") as f:
        json.dump(cache, f, indent=2, default=str)
    print(f"wrote {args.out}  (as_of={cache['as_of']}, "
          f"{len(cache['recommendations'])} strategies, "
          f"{len(cache['sell_signals'])} positions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
