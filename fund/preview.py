"""preview.py — single-strategy "what would this recommend?" — JSON output.

Designed for the dashboard's StrategyPicker: pick a strategy, see the
allocation it would produce *for the current portfolio's equity*, without
touching state.

Output is JSON to stdout so the API route can parse it directly:

    python3 -m fund.preview --strategy top_n_momentum \\
        --params '{"n": 2, "lookback_days": 126}' --principal 25000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from fund.portfolio import Portfolio
from fund.recommendations import compute_one


def main() -> int:
    ap = argparse.ArgumentParser(description="Preview one strategy's recommendation.")
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--params", default="{}", help="JSON dict of params")
    ap.add_argument("--principal", type=float, default=0.0,
                    help="0 = use active portfolio's principal")
    ap.add_argument("--as-of", default="")
    ap.add_argument("--source", default="auto")
    args = ap.parse_args()

    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as e:
        json.dump({"error": f"invalid --params JSON: {e}"}, sys.stdout)
        return 2

    principal = args.principal
    if principal <= 0:
        try:
            pf = Portfolio.load()
            principal = pf.principal
        except FileNotFoundError:
            principal = 25_000.0

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        result = compute_one(args.strategy, params, as_of,
                             principal=principal, source=args.source)
        json.dump(result, sys.stdout, default=str)
        return 0
    except Exception as e:
        json.dump({"error": f"{type(e).__name__}: {e}"}, sys.stdout)
        return 1


if __name__ == "__main__":
    sys.exit(main())
