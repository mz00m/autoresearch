"""honest_test.py — does adaptive's edge survive out-of-sample?

The adaptive allocator picks tomorrow's strategy based on the last 90 days of
every candidate's Sortino. The obvious failure mode is whipsaw: trailing
winners mean-revert and adaptive chases noise. The fair test is whether
adaptive *consistently* lands near the top across many regimes, not just the
one window I happened to pick for the demo.

For each calendar year, runs every bench strategy through the full window
once (via fund.quick_eval — uses run_backtest directly, skipping the morning
+ closeout I/O of the production loop). Then aggregates: cum return per year,
rank, average rank, % top-3 finishes, % beats SPY, regret vs in-hindsight
winner.

Run:
  python3 -m fund.honest_test                   # 2018-2024
  python3 -m fund.honest_test --years 2010-2024 # longer span
  python3 -m fund.honest_test --include leveraged_momentum
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from fund.quick_eval import (full_backtest, panel_and_tbill,
                             spy_window_return, universe_union, window_stats)

# Leveraged ETF data only goes back to ~2010 and skews comparisons earlier
# than that — opt in via --include if you want it in the table.
DEFAULT_STRATEGIES: list[tuple[str, dict]] = [
    ("sixty_forty", {}),
    ("dual_momentum", {"lookback_days": 252}),
    ("risk_parity", {"vol_window": 63}),
    ("top_n_momentum", {"n": 2, "lookback_days": 126}),
    ("ma_crossover", {"fast": 50, "slow": 200}),
    ("adaptive", {"lookback_days": 90}),
]


def evaluate(years: list[int], strategies: list[tuple[str, dict]],
             source: str = "auto") -> dict:
    end = date(years[-1], 12, 31)
    symbols = universe_union(strategies) + ["SPY"]
    print(f"loading {len(symbols)} symbols through {end}...")
    panel, tbill = panel_and_tbill(sorted(set(symbols)), end, source=source)

    print(f"running {len(strategies)} strategies once each over full panel...")
    results_by_strategy: dict[str, "BacktestResult"] = {}
    for name, params in strategies:
        tag = f"{name}{(' ' + ','.join(f'{k}={v}' for k, v in params.items())) if params else ''}"
        print(f"  {tag}")
        results_by_strategy[name] = full_backtest(name, params, panel, tbill)

    # Slice each strategy's returns by calendar year
    out: dict = {"by_year": {}, "spy": {}, "years": years}
    for year in years:
        y_start = date(year, 1, 1)
        y_end = date(year, 12, 31)
        out["spy"][year] = spy_window_return(panel, y_start, y_end)
        out["by_year"][year] = {}
        for name, params in strategies:
            stats = window_stats(results_by_strategy[name], y_start, y_end)
            out["by_year"][year][name] = stats
    return out


def summarize(results: dict, strategy_names: list[str]) -> None:
    years = results["years"]
    print("\n" + "=" * 90)
    print("CUM RETURN BY YEAR")
    print("=" * 90)
    header = f"  {'year':<6}{'SPY':>9}  "
    header += "  ".join(f"{n[:14]:>14}" for n in strategy_names)
    print(header)
    for year in years:
        row = f"  {year:<6}"
        spy = results["spy"].get(year)
        row += f"{(spy * 100) if spy is not None else 0:>+8.2f}%  "
        for n in strategy_names:
            r = results["by_year"][year].get(n) or {}
            cum = r.get("cum")
            if cum is None or r.get("n_days", 0) == 0:
                row += f"{'—':>14}  "
            else:
                row += f"{cum * 100:>+13.2f}%  "
        print(row)

    print("\n" + "=" * 90)
    print("RANK BY YEAR  (1 = best in cohort; '*' = winner)")
    print("=" * 90)
    print(f"  {'year':<6}        " + "  ".join(f"{n[:14]:>14}" for n in strategy_names))
    ranks: dict[str, list[int]] = {n: [] for n in strategy_names}
    for year in years:
        row = f"  {year:<6}        "
        scored = []
        for n in strategy_names:
            r = results["by_year"][year].get(n) or {}
            if r.get("n_days", 0) > 0:
                scored.append((n, r["cum"]))
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

    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"  {'strategy':<22} {'avg rank':>10} {'wins':>10} "
          f"{'top-3':>10} {'>SPY':>10} {'avg cum':>10} {'avg DD':>10}")
    for n in strategy_names:
        rk_list = ranks[n]
        if not rk_list:
            continue
        cums = [results["by_year"][y][n]["cum"] for y in years
                if results["by_year"][y].get(n)
                and results["by_year"][y][n].get("n_days", 0) > 0]
        dds = [results["by_year"][y][n]["max_dd"] for y in years
               if results["by_year"][y].get(n)
               and results["by_year"][y][n].get("n_days", 0) > 0]
        wins = sum(1 for r in rk_list if r == 1)
        top3 = sum(1 for r in rk_list if r <= 3)
        beat_spy = sum(
            1 for y in years
            if results["by_year"][y].get(n)
            and results["spy"].get(y) is not None
            and results["by_year"][y][n].get("n_days", 0) > 0
            and results["by_year"][y][n]["cum"] > results["spy"][y]
        )
        avg_cum = sum(cums) / len(cums) if cums else 0
        avg_dd = sum(dds) / len(dds) if dds else 0
        avg_rank = sum(rk_list) / len(rk_list)
        print(f"  {n:<22} {avg_rank:>10.2f} {wins:>6}/{len(rk_list):<3}"
              f"{top3:>6}/{len(rk_list):<3}{beat_spy:>6}/{len(rk_list):<3}"
              f"{avg_cum * 100:>+9.2f}%{-avg_dd * 100:>+9.2f}%")

    # Adaptive-specific: regret vs in-hindsight oracle
    if "adaptive" in strategy_names:
        print("\n" + "=" * 90)
        print("ADAPTIVE'S REGRET vs IN-HINDSIGHT BEST EACH YEAR")
        print("=" * 90)
        print(f"  {'year':<6} {'oracle':<24} {'oracle':>10} "
              f"{'adaptive':>10} {'regret':>10}")
        regrets = []
        for year in years:
            ad = results["by_year"][year].get("adaptive")
            if not ad or ad.get("n_days", 0) == 0:
                continue
            candidates = [(n, results["by_year"][year][n]["cum"])
                          for n in strategy_names if n != "adaptive"
                          and results["by_year"][year].get(n)
                          and results["by_year"][year][n].get("n_days", 0) > 0]
            if not candidates:
                continue
            oracle_name, oracle_cum = max(candidates, key=lambda x: x[1])
            regret = oracle_cum - ad["cum"]
            regrets.append(regret)
            print(f"  {year:<6} {oracle_name:<24}"
                  f"{oracle_cum * 100:>+9.2f}%"
                  f"{ad['cum'] * 100:>+9.2f}%"
                  f"{regret * 100:>+9.2f}pp")
        if regrets:
            avg_regret = sum(regrets) / len(regrets)
            print(f"\n  Adaptive's average annual regret vs oracle: "
                  f"{avg_regret * 100:+.2f}pp")
            beat_avg = sum(
                1 for year in years
                if results["by_year"][year].get("adaptive")
                and results["by_year"][year]["adaptive"].get("n_days", 0) > 0
                and (
                    results["by_year"][year]["adaptive"]["cum"]
                    > sum(results["by_year"][year][n]["cum"]
                          for n in strategy_names if n != "adaptive"
                          and results["by_year"][year].get(n))
                       / max(1, sum(1 for n in strategy_names if n != "adaptive"
                                    and results["by_year"][year].get(n)))
                )
            )
            print(f"  Years adaptive beat the average-of-others: "
                  f"{beat_avg}/{len(years)}")


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
