"""outcomes.py — did your conviction mean anything? Thesis outcome tracking.

Theses carry a 1-5 conviction, but nothing measures whether that number
predicts anything. This module closes the loop: when a thesis ends
(invalidated, expired, or the position exits), record what the symbol
actually did over the thesis window vs SPY. After enough closed theses the
calibration report answers the question that decides whether the options
layer has positive expected value: do your conviction-4s beat your
conviction-3s, and do they beat the benchmark at all?

Usage:
  python3 -m fund.outcomes close QQQ --reason "capex thesis played out"
      invalidates the active thesis AND records the outcome row
  python3 -m fund.outcomes report
      calibration table: avg excess return + hit rate by conviction level

Storage: fund/thesis_outcomes.tsv — append-only, same audit rules as the
research ledger. Gitignored (personal trading record).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime

from fund import thesis as thesis_mod
from fund.data.loader import load_panel

BENCHMARK = "SPY"

OUTCOMES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "thesis_outcomes.tsv")

FIELDS = ["closed_on", "symbol", "conviction", "opened_on", "days_held",
          "symbol_return", "benchmark_return", "excess_return", "hit",
          "reason", "catalyst"]


@dataclass
class Outcome:
    closed_on: str
    symbol: str
    conviction: int
    opened_on: str
    days_held: int
    symbol_return: float      # over the thesis window
    benchmark_return: float   # SPY over the same window
    excess_return: float
    hit: bool                 # beat the benchmark?
    reason: str
    catalyst: str


def _window_return(symbol: str, start: date, end: date,
                   source: str = "auto") -> float | None:
    panel, _ = load_panel([symbol], start, end, source=source)
    ps = panel.series.get(symbol)
    if ps is None or len(ps) < 2 or ps.closes[0] <= 0:
        return None
    return ps.closes[-1] / ps.closes[0] - 1.0


def close_thesis(symbol: str, reason: str, *, on: date | None = None,
                 source: str = "auto",
                 path: str = OUTCOMES_PATH) -> Outcome | None:
    """Invalidate the active thesis for ``symbol`` and record its outcome.
    Returns None (and leaves the thesis untouched) when no active thesis."""
    on = on or date.today()
    th = thesis_mod.active_for(symbol)
    if th is None:
        return None
    try:
        opened = datetime.fromisoformat(th["created_at"]).date()
    except (KeyError, ValueError):
        opened = on

    sym_ret = _window_return(symbol, opened, on, source=source)
    bench_ret = _window_return(BENCHMARK, opened, on, source=source)
    if sym_ret is None or bench_ret is None:
        sym_ret = sym_ret if sym_ret is not None else 0.0
        bench_ret = bench_ret if bench_ret is not None else 0.0
        reason = f"{reason} [WARN: window return unavailable, logged 0]"

    out = Outcome(
        closed_on=on.isoformat(), symbol=symbol.upper(),
        conviction=int(th.get("confidence", 0)),
        opened_on=opened.isoformat(), days_held=(on - opened).days,
        symbol_return=round(sym_ret, 6), benchmark_return=round(bench_ret, 6),
        excess_return=round(sym_ret - bench_ret, 6),
        hit=sym_ret > bench_ret,
        reason=reason.replace("\t", " ").replace("\n", " "),
        catalyst=str(th.get("catalyst", "")).replace("\t", " ").replace("\n", " "),
    )
    _append(out, path)
    thesis_mod.invalidate(symbol, reason, on=on)
    return out


def _append(out: Outcome, path: str) -> None:
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t")
        if new:
            w.writeheader()
        w.writerow(asdict(out))


def load_outcomes(path: str = OUTCOMES_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def calibration(path: str = OUTCOMES_PATH) -> list[dict]:
    """Per conviction level: n, hit rate, avg excess return. The table that
    tells you whether your conviction scale is informative."""
    rows = load_outcomes(path)
    by_conv: dict[int, list[dict]] = {}
    for r in rows:
        try:
            by_conv.setdefault(int(r["conviction"]), []).append(r)
        except (KeyError, ValueError):
            continue
    out = []
    for conv in sorted(by_conv, reverse=True):
        grp = by_conv[conv]
        hits = sum(1 for r in grp if r.get("hit") in ("True", True, "true"))
        avg_excess = sum(float(r["excess_return"]) for r in grp) / len(grp)
        out.append({"conviction": conv, "n": len(grp),
                    "hit_rate": round(hits / len(grp), 3),
                    "avg_excess_return": round(avg_excess, 4)})
    return out


def _cli_close(args) -> int:
    out = close_thesis(args.symbol, args.reason, source=args.source)
    if out is None:
        print(f"no active thesis for {args.symbol.upper()} — nothing to close.")
        return 1
    print(f"closed {out.symbol} thesis (conviction {out.conviction}, "
          f"{out.days_held}d held)")
    print(f"  {out.symbol}: {out.symbol_return:+.1%}   "
          f"{BENCHMARK}: {out.benchmark_return:+.1%}   "
          f"excess: {out.excess_return:+.1%}   {'HIT' if out.hit else 'MISS'}")
    return 0


def _cli_report(args) -> int:
    rows = calibration()
    n_total = sum(r["n"] for r in rows)
    if not rows:
        print("no closed theses yet — close one with:\n"
              "  python3 -m fund.outcomes close SYMBOL --reason '...'")
        return 0
    print(f"\n THESIS CALIBRATION — {n_total} closed theses")
    print(f" {'conviction':>10} {'n':>4} {'hit rate':>9} {'avg excess':>11}")
    for r in rows:
        print(f" {r['conviction']:>10} {r['n']:>4} {r['hit_rate']:>8.0%} "
              f"{r['avg_excess_return']:>+10.1%}")
    if n_total < 15:
        print(f"\n (small sample — treat as noise until ~15-20 closed theses)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Thesis outcome tracking + calibration.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("close", help="invalidate a thesis and record its outcome")
    c.add_argument("symbol")
    c.add_argument("--reason", required=True)
    c.add_argument("--source", default="auto")
    c.set_defaults(fn=_cli_close)
    r = sub.add_parser("report", help="calibration by conviction level")
    r.set_defaults(fn=_cli_report)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
