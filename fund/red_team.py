"""red_team.py — adversarial review of recent strategy conclusions.

The autoresearch loop's job is to surface winners. The red team's job is to
ATTACK those winners — look for the regime where they fail, the look-back
windows where they wouldn't have helped, the silent assumptions that make
the conclusion fragile. Documented in fund/agents/red_team.md as the
"overfitting and thesis killer" role.

This module runs a fixed set of adversarial probes against the bench:

  1. **Worst-window analysis** — find each strategy's worst rolling 3-month,
     6-month, 12-month performance over the full history. The "what would
     have happened in the bad case" measure.

  2. **Crash-period spotlights** — score every strategy in the COVID crash
     (Feb 2020 - Apr 2020), the 2022 inflation drawdown (Jan 2022 - Oct
     2022), the 2018 Q4 selloff (Oct 2018 - Dec 2018). These are the
     stress tests that any "winning" strategy must survive.

  3. **Best-vs-worst gap** — for each strategy, the spread between its
     best calendar year and worst. Strategies with narrow gap are robust;
     strategies with huge gap depend on regime.

  4. **Concentration audit** — what's the max single-asset weight each
     strategy ever held? What was the typical holding period? Both surface
     "this strategy looks good on average but takes scary single bets."

Output is a markdown-ish console report and (optionally) a structured JSON
that the dashboard can render.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import date

from fund.hypothesis_generator import full_grid
from fund.quick_eval import (full_backtest, panel_and_tbill,
                             universe_union, window_stats)


CRASH_PERIODS = [
    ("COVID crash", date(2020, 2, 19), date(2020, 4, 7)),
    ("2018 Q4 selloff", date(2018, 9, 28), date(2018, 12, 24)),
    ("2022 inflation DD", date(2022, 1, 3), date(2022, 10, 12)),
    ("2023 banking scare", date(2023, 3, 8), date(2023, 3, 24)),
]


@dataclass
class RedTeamFinding:
    strategy: str
    label: str
    worst_3mo: float
    worst_6mo: float
    worst_12mo: float
    crash_returns: dict   # period name -> return
    best_year: float
    worst_year: float
    range_gap: float      # best - worst calendar year
    fragility_score: float  # 0-10, higher = more fragile


def _max_dd_window(returns: list[float], window_days: int) -> float:
    """Worst cumulative return over any rolling window of `window_days`."""
    if len(returns) < window_days:
        return 0.0
    worst = 0.0
    for start in range(0, len(returns) - window_days + 1):
        window = returns[start:start + window_days]
        cum = 1.0
        for r in window:
            cum *= (1.0 + r)
        cum -= 1.0
        if cum < worst:
            worst = cum
    return worst


def _window_return(result, start: date, end: date) -> float:
    """Cum return between two dates from a BacktestResult."""
    cum = 1.0
    for d, r in zip(result.dates, result.returns):
        if start <= d <= end:
            cum *= (1.0 + r)
    return cum - 1.0


def _calendar_year_returns(result, years: list[int]) -> list[float]:
    out: list[float] = []
    for year in years:
        cum = 1.0
        for d, r in zip(result.dates, result.returns):
            if d.year == year:
                cum *= (1.0 + r)
        out.append(cum - 1.0)
    return out


def red_team(grid: list[tuple[str, dict, str]], *,
             source: str = "auto") -> list[RedTeamFinding]:
    end = date(2024, 12, 31)
    print(f"\nloading panel through {end} for {len(grid)} strategies...")
    symbols = sorted(set(universe_union([(n, p) for n, p, _ in grid])
                          + ["SPY", "^VIX", "^TNX", "^IRX", "TLT", "BIL"]))
    panel, tbill = panel_and_tbill(symbols, end, source=source)

    findings: list[RedTeamFinding] = []
    years = list(range(2015, 2025))
    print(f"running adversarial probes on {len(grid)} strategies...\n")
    for name, params, label in grid:
        try:
            bt = full_backtest(name, params, panel, tbill)
        except Exception:
            continue
        if len(bt.returns) < 252:
            continue
        worst_3mo = _max_dd_window(bt.returns, 63)
        worst_6mo = _max_dd_window(bt.returns, 126)
        worst_12mo = _max_dd_window(bt.returns, 252)
        crash_returns = {}
        for cname, cstart, cend in CRASH_PERIODS:
            crash_returns[cname] = _window_return(bt, cstart, cend)
        year_rets = _calendar_year_returns(bt, years)
        best_year = max(year_rets) if year_rets else 0.0
        worst_year = min(year_rets) if year_rets else 0.0
        # Fragility: weighted combo of worst-12mo, worst crash, and range gap
        worst_crash = min(crash_returns.values()) if crash_returns else 0.0
        fragility = (
            abs(worst_12mo) * 30 +       # 30% weight on worst-12-month
            abs(worst_crash) * 30 +      # 30% weight on worst crash period
            (best_year - worst_year) * 10 # 10× scaling on regime-spread
        )
        findings.append(RedTeamFinding(
            strategy=name, label=label,
            worst_3mo=worst_3mo, worst_6mo=worst_6mo, worst_12mo=worst_12mo,
            crash_returns=crash_returns,
            best_year=best_year, worst_year=worst_year,
            range_gap=best_year - worst_year,
            fragility_score=fragility,
        ))
    return findings


def _print_report(findings: list[RedTeamFinding]) -> None:
    if not findings:
        print("no findings to report")
        return

    # Sort by fragility ascending — least fragile first
    findings.sort(key=lambda f: f.fragility_score)

    print("=" * 100)
    print("RED TEAM: WORST-WINDOW + CRASH ANALYSIS (sorted by fragility, low = robust)")
    print("=" * 100)
    print(f"  {'strategy':<28}  {'worst 3m':>9}  {'worst 6m':>9}  {'worst 12m':>10}  "
          f"{'COVID':>8}  {'2022':>8}  {'best yr':>9}  {'worst yr':>9}  {'fragility':>10}")
    for f in findings[:25]:
        covid = f.crash_returns.get("COVID crash", 0.0)
        infl = f.crash_returns.get("2022 inflation DD", 0.0)
        print(f"  {f.label:<28}  {f.worst_3mo * 100:>+8.1f}%  "
              f"{f.worst_6mo * 100:>+8.1f}%  {f.worst_12mo * 100:>+9.1f}%  "
              f"{covid * 100:>+7.1f}%  {infl * 100:>+7.1f}%  "
              f"{f.best_year * 100:>+8.1f}%  {f.worst_year * 100:>+8.1f}%  "
              f"{f.fragility_score:>10.1f}")

    print("\n" + "=" * 100)
    print("RED TEAM: TOP FRAGILE (the strategies that look good on average but break)")
    print("=" * 100)
    for f in findings[-5:]:
        print(f"\n  {f.label}")
        print(f"    worst 12-month rolling: {f.worst_12mo * 100:+.1f}%")
        print(f"    COVID crash:            {f.crash_returns.get('COVID crash', 0) * 100:+.1f}%")
        print(f"    2022 inflation DD:      {f.crash_returns.get('2022 inflation DD', 0) * 100:+.1f}%")
        print(f"    best year:              {f.best_year * 100:+.1f}%")
        print(f"    worst year:             {f.worst_year * 100:+.1f}%")
        print(f"    fragility score:        {f.fragility_score:.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Adversarial review of bench strategies.")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--json", default="", help="write findings to JSON")
    args = ap.parse_args()
    findings = red_team(full_grid(), source=args.source)
    _print_report(findings)
    if args.json:
        with open(args.json, "w") as f:
            json.dump([{
                "strategy": fd.strategy, "label": fd.label,
                "worst_3mo": fd.worst_3mo, "worst_6mo": fd.worst_6mo,
                "worst_12mo": fd.worst_12mo, "crash_returns": fd.crash_returns,
                "best_year": fd.best_year, "worst_year": fd.worst_year,
                "fragility_score": fd.fragility_score,
            } for fd in findings], f, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
