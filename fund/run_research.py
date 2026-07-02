"""run_research.py — one pass of the overnight factory, end to end.

Demonstrates the full discipline on a single strategy family (dual momentum):

  1. Load point-in-time data (real if allowlisted, else deterministic synthetic).
  2. Lock an OOS vault (last 30% of dates) the SELECTION never sees.
  3. Scan a few lookbacks; pick the best by IN-SAMPLE objective only.
  4. Score the winner ONCE on the locked OOS slice, deflating by the number of
     trials tried this session.
  5. Append keep/discard verdicts to research_ledger.tsv.

Run from the repo root:
    python3 -m fund.run_research                 # synthetic (default, offline)
    python3 -m fund.run_research --source real   # needs Stooq/FRED allowlisted

This proves the plumbing. A synthetic "keep" is NOT an edge — only live,
out-of-sample, after-cost results are.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date

from fund import ledger
from fund.backtest import Costs, run_backtest
from fund.data.loader import load_panel
from fund.evaluator import Constraints, evaluate, sortino_annualized
from fund.strategy.dual_momentum import DualMomentum

UNIVERSE = ("SPY", "EFA", "AGG", "GLD", "QQQ")
START, END = date(2006, 1, 1), date(2023, 12, 31)
LOOKBACKS = (63, 126, 189, 252)  # ~3, 6, 9, 12 months
OOS_FRAC = 0.30


def _git_short() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "nogit"


def main(source: str = "auto") -> None:
    panel, tbill = load_panel(list(UNIVERSE), START, END, source=source)
    dates = panel.common_dates()
    if len(dates) < 200:
        print("not enough data to run; aborting.")
        return
    cutoff = dates[int(len(dates) * (1.0 - OOS_FRAC))]
    print(f"data: {dates[0]}..{dates[-1]}  ({len(dates)} days)  OOS vault > {cutoff}\n")

    # --- scan candidates; SELECT on in-sample only -------------------------
    rows = []
    for lb in LOOKBACKS:
        strat = DualMomentum(UNIVERSE, lookback_days=lb)
        res = run_backtest(strat, panel, tbill, costs=Costs(slippage_bps=5.0))
        ins, oos = res.partition(cutoff)
        ins_sortino = sortino_annualized(ins["returns"])
        rows.append({"lb": lb, "strat": strat, "ins": ins, "oos": oos,
                     "ins_sortino": ins_sortino})

    from fund.evaluator import sharpe_per_period
    trial_sharpes = [sharpe_per_period(r["ins"]["returns"]) for r in rows]
    winner = max(rows, key=lambda r: r["ins_sortino"])
    print("in-sample selection (OOS NOT consulted):")
    for r in rows:
        flag = "  <- selected" if r is winner else ""
        print(f"  lookback {r['lb']:>3}d  in-sample Sortino {r['ins_sortino']:+.2f}{flag}")
    print()

    # --- score the winner ONCE on the locked OOS slice ---------------------
    commit = _git_short()
    constraints = Constraints()
    for r in rows:
        oos = r["oos"]
        score = evaluate(oos["returns"], trial_sharpes,
                         turnover=oos["turnover_annualized"],
                         n_trades=oos["n_rebal"], n_params=r["strat"].n_params,
                         constraints=constraints)
        is_winner = r is winner
        if is_winner:
            status = "keep" if score.passed else "discard"
            desc = (f"dual-momentum lb={r['lb']}d; selected in-sample; "
                    f"OOS verdict: {'PASS' if score.passed else 'FAIL'}")
        else:
            status = "discard"
            desc = f"dual-momentum lb={r['lb']}d; lost in-sample selection"
        ledger.append(ledger.Entry(
            strategy_id=f"dual-momentum-lb{r['lb']}", commit=commit, status=status,
            oos_deflated_sharpe=round(score.deflated_sharpe, 4),
            oos_sortino=round(score.sortino, 4),
            oos_max_dd=round(score.max_drawdown, 4),
            n_trials=len(LOOKBACKS), n_params=r["strat"].n_params,
            objective=round(score.objective, 4), description=desc))
        if is_winner:
            print("WINNER OOS scorecard:")
            for reason in score.reasons:
                print(f"  {reason}")
            print(f"  deflated_sharpe={score.deflated_sharpe:.3f}  "
                  f"OOS_sortino={score.sortino:.2f}  max_dd={score.max_drawdown:.1%}  "
                  f"OOS_rebalances={oos['n_rebal']}")
            print(f"\n  -> logged as '{status}' to research_ledger.tsv")


if __name__ == "__main__":
    src = "auto"
    if "--source" in sys.argv:
        src = sys.argv[sys.argv.index("--source") + 1]
    main(source=src)
