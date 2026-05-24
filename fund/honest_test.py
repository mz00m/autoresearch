"""honest_test.py — does adaptive's edge survive out-of-sample?

The adaptive allocator picks tomorrow's strategy based on the last 90 days
of every candidate's Sortino. The obvious failure mode is whipsaw: trailing
winners mean-revert and adaptive chases noise. The fair test is whether
adaptive *consistently* lands near the top across many regimes, not just
the one window I happened to show in the demo.

For each calendar year, runs every bench strategy on real data, ranks them,
and aggregates. Useful diagnostics printed:

  * cum return + max DD per (year, strategy)
  * rank (1 = best, N = worst) per (year, strategy)
  * average rank across years
  * % of years adaptive finishes top-3
  * adaptive's regret vs the in-hindsight winner each year

Run:
  python3 -m fund.honest_test                   # 2018-2024, default 7 strategies
  python3 -m fund.honest_test --years 2010-2024 # longer span
  python3 -m fund.honest_test --include leveraged_momentum   # opt-in to lev
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date

from fund.portfolio import Portfolio
from fund.simulate import simulate

# Default eval set — leveraged_momentum is excluded by default because its
# leveraged-ETF data only stretches back to ~2010 cleanly, and its inclusion
# muddies the apples-to-apples comparison. Opt in with --include.
DEFAULT_STRATEGIES: list[tuple[str, dict]] = [
    ("sixty_forty", {}),
    ("dual_momentum", {"lookback_days": 252}),
    ("risk_parity", {"vol_window": 63}),
    ("top_n_momentum", {"n": 2, "lookback_days": 126}),
    ("ma_crossover", {"fast": 50, "slow": 200}),
    ("adaptive", {"lookback_days": 90}),
]


def _max_dd(history) -> float:
    if not history:
        return 0.0
    peak = history[0].equity
    mdd = 0.0
    for h in history:
        peak = max(peak, h.equity)
        if peak > 0:
            mdd = max(mdd, (peak - h.equity) / peak)
    return mdd


def _run_one(name: str, params: dict, days: int, end: date,
             source: str = "auto") -> dict | None:
    state = tempfile.mktemp(suffix=".json")
    log = tempfile.mktemp(suffix=".tsv")
    try:
        pf, _ = simulate(days=days, end=end, principal=25_000.0,
                         strategy=name, strategy_params=params,
                         source=source, state_path=state, log_path=log,
                         quiet=True)
        if len(pf.history) < 2:
            return None
        cum = pf.history[-1].equity / pf.history[0].equity - 1.0
        return {"cum": cum, "max_dd": _max_dd(pf.history),
                "ending": pf.history[-1].equity}
    finally:
        for p in (state, log):
            if os.path.exists(p):
                os.unlink(p)


def _spy_year_return(year: int, source: str = "auto") -> float | None:
    """Use simulate's panel loader to get SPY's calendar-year total return.
    Quick way to get the benchmark for a year without writing a separate path."""
    from fund.data.loader import load_panel
    panel, _ = load_panel(["SPY"], date(2005, 1, 1),
                          date(year, 12, 31), source=source)
    spy = panel.series.get("SPY")
    if spy is None or len(spy.dates) < 2:
        return None
    start_slice = spy.as_of(date(year - 1, 12, 31))
    end_slice = spy.as_of(date(year, 12, 31))
    if not start_slice.closes or not end_slice.closes:
        return None
    return end_slice.closes[-1] / start_slice.closes[-1] - 1.0


def evaluate(years: list[int], strategies: list[tuple[str, dict]],
             *, source: str = "auto") -> dict:
    """Returns a nested dict {year: {strategy_id: result_or_None}} plus SPY."""
    results: dict = {"by_year": {}, "spy": {}}
    for year in years:
        end = date(year, 12, 31)
        print(f"\n=== {year} ===")
        spy = _spy_year_return(year, source=source)
        results["spy"][year] = spy
        if spy is not None:
            print(f"  {'SPY':<20} {spy * 100:+7.2f}%")
        results["by_year"][year] = {}
        for name, params in strategies:
            tag = f"{name}{(' ' + ','.join(f'{k}={v}' for k, v in params.items())) if params else ''}"
            r = _run_one(name, params, 252, end, source=source)
            results["by_year"][year][name] = r
            if r:
                print(f"  {tag:<32} {r['cum'] * 100:+7.2f}%  dd -{r['max_dd'] * 100:5.2f}%")
            else:
                print(f"  {tag:<32}  (insufficient data)")
    return results


def summarize(results: dict, strategy_names: list[str]) -> None:
    years = sorted(results["by_year"])
    if not years:
        print("no results")
        return

    print("\n" + "=" * 78)
    print("CUM RETURN BY YEAR (excluding strategies with any missing year)")
    print("=" * 78)
    # Header
    header = f"  {'year':<6}{'SPY':>8}  "
    header += "  ".join(f"{n[:14]:>14}" for n in strategy_names)
    print(header)
    for year in years:
        row = f"  {year:<6}"
        spy = results["spy"].get(year)
        row += f"{(spy * 100) if spy is not None else 0:>+7.2f}%  "
        for n in strategy_names:
            r = results["by_year"][year].get(n)
            if r:
                row += f"{r['cum'] * 100:>+13.2f}%  "
            else:
                row += f"{'—':>14}  "
        print(row)

    # Ranking aggregates
    print("\n" + "=" * 78)
    print("RANK BY YEAR  (1 = best, N = worst)   '*' = winner")
    print("=" * 78)
    ranks: dict[str, list[int]] = {n: [] for n in strategy_names}
    for year in years:
        row = f"  {year:<6}        "
        scored = [(n, results["by_year"][year][n]["cum"])
                  for n in strategy_names
                  if results["by_year"][year][n] is not None]
        scored.sort(key=lambda x: -x[1])
        rank_by_name = {n: i + 1 for i, (n, _) in enumerate(scored)}
        for n in strategy_names:
            rk = rank_by_name.get(n)
            if rk is not None:
                ranks[n].append(rk)
                mark = "*" if rk == 1 else " "
                row += f"{rk:>13}{mark}  "
            else:
                row += f"{'—':>14}  "
        print(row)

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  {'strategy':<22} {'avg rank':>10} {'wins':>8} "
          f"{'top-3':>8} {'>SPY':>8} {'avg cum':>10} {'avg DD':>10}")
    for n in strategy_names:
        rk_list = ranks[n]
        if not rk_list:
            continue
        cums = [results["by_year"][y][n]["cum"]
                for y in years if results["by_year"][y].get(n)]
        dds = [results["by_year"][y][n]["max_dd"]
               for y in years if results["by_year"][y].get(n)]
        wins = sum(1 for r in rk_list if r == 1)
        top3 = sum(1 for r in rk_list if r <= 3)
        beat_spy = sum(
            1 for y in years
            if results["by_year"][y].get(n) and results["spy"].get(y) is not None
            and results["by_year"][y][n]["cum"] > results["spy"][y]
        )
        avg_cum = sum(cums) / len(cums)
        avg_dd = sum(dds) / len(dds)
        avg_rank = sum(rk_list) / len(rk_list)
        print(f"  {n:<22} {avg_rank:>10.2f} {wins:>4}/{len(rk_list):<3} "
              f"{top3:>4}/{len(rk_list):<3} {beat_spy:>4}/{len(rk_list):<3} "
              f"{avg_cum * 100:>+9.2f}% {-avg_dd * 100:>+9.2f}%")

    # Adaptive-specific: regret vs in-hindsight oracle each year
    print("\n" + "=" * 78)
    print("ADAPTIVE'S REGRET vs IN-HINDSIGHT BEST EACH YEAR")
    print("=" * 78)
    print(f"  {'year':<6} {'oracle':<22} {'oracle cum':>12} "
          f"{'adaptive cum':>14} {'regret':>10}")
    regrets = []
    for year in years:
        if "adaptive" not in strategy_names:
            continue
        ad = results["by_year"][year].get("adaptive")
        if ad is None:
            continue
        candidates = [(n, results["by_year"][year][n]["cum"])
                      for n in strategy_names if n != "adaptive"
                      and results["by_year"][year].get(n) is not None]
        if not candidates:
            continue
        oracle_name, oracle_cum = max(candidates, key=lambda x: x[1])
        regret = oracle_cum - ad["cum"]
        regrets.append(regret)
        print(f"  {year:<6} {oracle_name:<22} {oracle_cum * 100:>+11.2f}%  "
              f"{ad['cum'] * 100:>+13.2f}%  {regret * 100:>+9.2f}pp")
    if regrets:
        avg_regret = sum(regrets) / len(regrets)
        print(f"  {'avg regret':<6} {'':<22} {'':<12}  {'':<14}  "
              f"{avg_regret * 100:>+9.2f}pp")


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-year honest test for adaptive.")
    ap.add_argument("--years", default="2018-2024",
                    help="inclusive year range, e.g. 2015-2024")
    ap.add_argument("--include", default="",
                    help="comma-separated extra strategies (e.g. leveraged_momentum)")
    ap.add_argument("--source", default="auto")
    args = ap.parse_args()

    lo, _, hi = args.years.partition("-")
    years = list(range(int(lo), int(hi) + 1))
    strategies = list(DEFAULT_STRATEGIES)
    for extra in args.include.split(","):
        extra = extra.strip()
        if extra:
            strategies.append((extra, {}))
    strategy_names = [n for n, _ in strategies]

    results = evaluate(years, strategies, source=args.source)
    summarize(results, strategy_names)
    return 0


if __name__ == "__main__":
    sys.exit(main())
