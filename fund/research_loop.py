"""research_loop.py — large-scale autoresearch across multiple OOS splits.

Runs the 56-hypothesis grid through proper_research at 4 different
in-sample cut dates (2015, 2017, 2019, 2021) — so we can see WHICH
strategies survive deflation in WHICH market regimes, and whether ANY
strategy survives in a majority of splits.

A strategy that survives 3-of-4 cuts has materially stronger evidence
than one that only wins in one specific selection window — that's the
practical replacement for walk-forward at strategy-selection granularity.

Output: per-cut winners + aggregated "consensus winner" report.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date

from fund.hypothesis_generator import full_grid
from fund.proper_research import run as proper_run


CUTS = [
    (date(2015, 12, 31), date(2024, 12, 31)),
    (date(2017, 12, 31), date(2024, 12, 31)),
    (date(2019, 12, 31), date(2024, 12, 31)),
    (date(2021, 12, 31), date(2024, 12, 31)),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="auto")
    ap.add_argument("--no-ledger", action="store_true",
                    help="don't append to research_ledger.tsv")
    args = ap.parse_args()

    grid = full_grid()
    print(f"\nautoresearch loop: {len(grid)} hypotheses × {len(CUTS)} cuts "
          f"= {len(grid) * len(CUTS)} trials\n")

    # Aggregate: strategy_label -> list of (cut, in_sample_rank, deflated_SR)
    results_by_strategy: dict[str, list[dict]] = defaultdict(list)
    cut_winners: list[dict] = []

    for is_end, oos_end in CUTS:
        print(f"\n{'=' * 70}")
        print(f"CUT: IS through {is_end}, OOS {is_end + (oos_end - is_end)/2}..{oos_end}")
        print(f"{'=' * 70}")
        try:
            result = proper_run(
                in_sample_end=is_end,
                oos_end=oos_end,
                source=args.source,
                write_ledger=not args.no_ledger,
                grid=grid,
            )
        except Exception as e:
            print(f"  cut failed: {type(e).__name__}: {e}")
            continue
        winner = result.get("winner")
        score = result.get("score")
        if winner is None or score is None:
            continue
        cut_winners.append({
            "cut": is_end.isoformat(),
            "winner_label": winner.label,
            "winner_name": winner.name,
            "is_sortino": winner.is_sortino,
            "oos_sortino": winner.oos_sortino,
            "oos_max_dd": winner.oos_max_dd,
            "deflated_sharpe": winner.oos_deflated_sharpe,
            "passed_gate": score.passed,
            "reasons": list(score.reasons),
        })
        # Rank all trials in this cut by IS Sortino so we can aggregate
        trials_sorted = sorted(result["trials"], key=lambda t: -t.is_sortino)
        for rank, t in enumerate(trials_sorted, start=1):
            results_by_strategy[t.label].append({
                "cut": is_end.isoformat(),
                "is_rank": rank,
                "is_sortino": t.is_sortino,
            })

    # Final aggregation
    print(f"\n\n{'=' * 70}")
    print(f"CONSENSUS WINNERS — top by average in-sample rank across {len(CUTS)} cuts")
    print(f"{'=' * 70}")
    print(f"  {'strategy':<28} {'avg rank':>9} {'best rank':>10} {'cuts':>6}")
    aggregated = []
    for label, results in results_by_strategy.items():
        if not results:
            continue
        ranks = [r["is_rank"] for r in results]
        aggregated.append({
            "label": label, "avg_rank": sum(ranks) / len(ranks),
            "best_rank": min(ranks), "n_cuts": len(results),
        })
    aggregated.sort(key=lambda a: a["avg_rank"])
    for a in aggregated[:20]:
        print(f"  {a['label']:<28} {a['avg_rank']:>9.2f} "
              f"{a['best_rank']:>10d} {a['n_cuts']:>6d}/{len(CUTS)}")

    print(f"\n{'=' * 70}")
    print(f"DEFLATION GATE — winners that survived the deflated-SR test")
    print(f"{'=' * 70}")
    print(f"  {'cut':<12} {'winner':<28} {'IS Sort':>8} "
          f"{'OOS Sort':>9} {'def SR':>7} {'gate':>6}")
    for w in cut_winners:
        gate = "KEEP" if w["passed_gate"] else "fail"
        print(f"  {w['cut']:<12} {w['winner_label']:<28} "
              f"{w['is_sortino']:>+7.2f} {w['oos_sortino']:>+8.2f} "
              f"{w['deflated_sharpe']:>6.3f} {gate:>6}")
    keeps = sum(1 for w in cut_winners if w["passed_gate"])
    print(f"\n  {keeps}/{len(cut_winners)} cuts produced a KEEP-grade winner.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
