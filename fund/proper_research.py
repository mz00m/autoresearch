"""proper_research.py — apply the autoresearch overfitting protocol to my own work.

Until now my "research" has been: backtest 16 strategies on 2018-2024, pick
the winner, ship it. That's exactly what evaluator.deflated_sharpe_ratio was
built to discount — testing N hypotheses on the same window and selecting
the best is a *machine for manufacturing overfit results*.

This module does it the right way:

  1. Lock the last `oos_frac` of dates as the OOS vault — strategies never
     get scored on it during selection.
  2. For every (strategy, parameter combo) in the grid, run backtest on the
     in-sample slice. Record in-sample Sortino (the selection metric) and
     in-sample per-period Sharpe (for deflation math).
  3. Pick the winner ON IN-SAMPLE ONLY.
  4. Score the winner ONCE on the locked OOS slice, passing ALL trial
     Sharpes so the deflated SR knows how many hypotheses we tried.
  5. Hard constraints first (drawdown, turnover, trade count). Then
     deflated SR must clear 0.95 to be "keep"; otherwise "discard".
  6. Append every trial AND the winner verdict to research_ledger.tsv —
     append-only, never rewritten.

If the winner clears the gate, that's a genuine signal. If it doesn't, the
honest_test's "skip_month_momentum beats top_n_momentum" result was probably
a single-window artifact and we should stay defensive.

Run:
    python3 -m fund.proper_research                            # default grid
    python3 -m fund.proper_research --in-sample 2005-2018      # custom split
    python3 -m fund.proper_research --no-ledger                # don't log
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date

from fund.evaluator import (Constraints, deflated_sharpe_ratio, evaluate,
                            max_drawdown, sharpe_per_period,
                            sortino_annualized)
from fund.ledger import Entry, append as ledger_append
from fund.quick_eval import full_backtest, panel_and_tbill, universe_union


# --- the grid -------------------------------------------------------------
# Each entry is (name, params, label). Same-strategy parameter variants count
# as separate trials for deflation purposes.

GRID: list[tuple[str, dict, str]] = [
    ("sixty_forty", {}, "60/40"),

    ("dual_momentum", {"lookback_days": 126}, "dual-mom 126d"),
    ("dual_momentum", {"lookback_days": 252}, "dual-mom 252d"),

    ("top_n_momentum", {"n": 2, "lookback_days": 63}, "top2 63d"),
    ("top_n_momentum", {"n": 2, "lookback_days": 126}, "top2 126d"),
    ("top_n_momentum", {"n": 2, "lookback_days": 252}, "top2 252d"),
    ("top_n_momentum", {"n": 3, "lookback_days": 126}, "top3 126d"),

    ("skip_month_momentum", {"n": 2, "long_lookback": 126, "skip_lookback": 21},
        "skip-month 126-21"),
    ("skip_month_momentum", {"n": 2, "long_lookback": 252, "skip_lookback": 21},
        "skip-month 252-21"),
    ("skip_month_momentum", {"n": 3, "long_lookback": 252, "skip_lookback": 21},
        "skip-month top3 252-21"),

    ("time_series_momentum", {"lookback_days": 126}, "tsmom 126d"),
    ("time_series_momentum", {"lookback_days": 252}, "tsmom 252d"),

    ("risk_parity", {"vol_window": 63}, "risk-parity 63d"),
    ("risk_parity", {"vol_window": 126}, "risk-parity 126d"),

    ("ma_crossover", {"fast": 50, "slow": 200}, "MA 50/200"),
    ("ma_crossover", {"fast": 20, "slow": 100}, "MA 20/100"),

    ("faber_gtaa", {}, "Faber GTAA"),
    ("all_weather", {}, "All-Weather"),
    ("permanent_portfolio", {}, "Permanent Portfolio"),
    ("rp_crisis_hedge", {}, "RP + 15% TLT"),
    ("trend_carry", {}, "trend+carry"),
    ("low_vol", {}, "low-vol bottom-3"),
]


# --- trial result -----------------------------------------------------------

@dataclass
class Trial:
    name: str
    params: dict
    label: str
    # in-sample selection metrics
    is_sortino: float
    is_sharpe_per_period: float
    is_n_days: int
    # OOS scoring (filled only for the winner)
    oos_sortino: float = 0.0
    oos_max_dd: float = 0.0
    oos_deflated_sharpe: float = 0.0
    oos_n_days: int = 0
    n_trades: int = 0
    turnover_per_year: float = 0.0


def _backtest_window(bt, lo_idx: int, hi_idx: int) -> dict:
    """Slice a BacktestResult by index range; return summary stats."""
    rets = bt.returns[lo_idx:hi_idx]
    dates = bt.dates[lo_idx:hi_idx]
    rebal_in_window = [d for d in bt.rebal_dates
                       if dates and dates[0] <= d <= dates[-1]]
    n_trades = len(rebal_in_window)
    turnover_total = sum(bt.rebal_turnover.get(d, 0.0)
                         for d in rebal_in_window)
    years = (len(rets) / 252.0) if rets else 0.0
    return {
        "returns": rets,
        "n_days": len(rets),
        "n_trades": n_trades,
        "turnover_per_year": turnover_total / years if years > 0 else 0.0,
    }


def run(*, in_sample_end: date | None = None, oos_end: date | None = None,
        source: str = "auto", write_ledger: bool = True,
        constraints: Constraints | None = None,
        grid: list[tuple[str, dict, str]] | None = None) -> dict:
    """Execute the protocol. Returns a result dict."""
    constraints = constraints or Constraints()
    oos_end = oos_end or date(2024, 12, 31)
    in_sample_end = in_sample_end or date(2018, 12, 31)
    grid = grid if grid is not None else GRID

    # Load the union of every symbol any candidate might use
    symbols = list(set(universe_union([(n, p) for n, p, _ in grid])
                       + ["SPY", "^VIX", "^TNX", "^IRX", "TLT", "BIL"]))
    print(f"loading {len(symbols)} symbols through {oos_end}...")
    panel, tbill = panel_and_tbill(sorted(symbols), oos_end, source=source)

    # Use SPY's date sequence as the canonical timeline (consistent with
    # backtest.run_backtest)
    spy = panel.series.get("SPY")
    if spy is None:
        raise RuntimeError("SPY not loaded — can't establish timeline")
    all_dates = list(spy.dates)
    cut_idx = next((i for i, d in enumerate(all_dates) if d > in_sample_end),
                   len(all_dates))
    n_in = cut_idx
    n_out = len(all_dates) - cut_idx
    print(f"in-sample: {all_dates[0]}..{all_dates[cut_idx - 1]}  ({n_in} days)")
    print(f"OOS vault: {all_dates[cut_idx]}..{all_dates[-1]}  ({n_out} days)")
    print(f"grid: {len(grid)} trials\n")

    # Pass 1: backtest every candidate, slice by IS / OOS, record selection
    # metrics on IS only.
    trials: list[Trial] = []
    full_returns: dict[int, list[float]] = {}   # trial idx -> full returns

    for i, (name, params, label) in enumerate(grid):
        try:
            bt = full_backtest(name, params, panel, tbill)
        except Exception as e:
            print(f"  [skip {label}] {type(e).__name__}: {e}")
            continue
        # The backtest's date-index alignment to all_dates may be off by 1
        # (it skips the very first day). Use rets length to slice.
        rets_full = bt.returns
        # IS = first n_in - 1 returns (since backtest produces N-1 returns
        # for N dates). OOS = the rest.
        is_slice = rets_full[:max(0, cut_idx - 1)]
        oos_slice = rets_full[max(0, cut_idx - 1):]
        is_n = len(is_slice)
        if is_n < 50:
            print(f"  [skip {label}] only {is_n} IS days — too short")
            continue

        is_sortino = sortino_annualized(is_slice)
        is_sr = sharpe_per_period(is_slice)
        oos_n_trades = sum(1 for d in bt.rebal_dates
                           if d > in_sample_end and d <= oos_end)
        oos_turnover = sum(bt.rebal_turnover.get(d, 0.0)
                           for d in bt.rebal_dates
                           if d > in_sample_end and d <= oos_end)
        oos_years = len(oos_slice) / 252.0 if oos_slice else 0.0

        t = Trial(
            name=name, params=params, label=label,
            is_sortino=is_sortino, is_sharpe_per_period=is_sr,
            is_n_days=is_n,
            oos_n_days=len(oos_slice),
            n_trades=oos_n_trades,
            turnover_per_year=oos_turnover / oos_years if oos_years > 0 else 0.0,
        )
        trials.append(t)
        full_returns[len(trials) - 1] = rets_full
        print(f"  {label:<28}  IS Sortino {is_sortino:>+6.2f}  IS SR/period {is_sr:>+7.4f}")

    if not trials:
        print("\nno trials made it through — nothing to score.")
        return {"winner": None, "trials": []}

    # Pass 2: pick winner by IS Sortino, score it ONCE on OOS with deflation
    trials_sorted = sorted(trials, key=lambda x: -x.is_sortino)
    winner_idx = trials.index(trials_sorted[0])
    winner = trials[winner_idx]
    print(f"\n  WINNER (in-sample only): {winner.label}  "
          f"IS Sortino {winner.is_sortino:+.2f}")

    # Compute OOS metrics for the winner using its OOS slice
    rets_full = full_returns[winner_idx]
    oos_rets = rets_full[max(0, cut_idx - 1):]
    winner.oos_sortino = sortino_annualized(oos_rets)
    winner.oos_max_dd = max_drawdown(oos_rets)
    trial_sharpes = [t.is_sharpe_per_period for t in trials]
    winner.oos_deflated_sharpe = deflated_sharpe_ratio(oos_rets, trial_sharpes)

    print(f"\n  OOS SCORECARD (winner, scored ONCE):")
    print(f"    OOS Sortino           {winner.oos_sortino:+.2f}")
    print(f"    OOS max drawdown      {winner.oos_max_dd:.1%}")
    print(f"    OOS trades            {winner.n_trades}")
    print(f"    OOS turnover / year   {winner.turnover_per_year:.1f}")
    print(f"    OOS deflated Sharpe   {winner.oos_deflated_sharpe:.3f}   "
          f"(want ≥ {constraints.min_deflated_sharpe:.2f})")

    score = evaluate(
        oos_rets, trial_sharpes,
        turnover=winner.turnover_per_year,
        n_trades=winner.n_trades,
        n_params=2,   # rough — each strategy averages ~2 tunable params
        constraints=constraints,
    )
    verdict = "keep" if score.passed else "discard"
    print(f"\n  VERDICT: {verdict.upper()}")
    for r in score.reasons:
        print(f"    {r}")

    # Pass 3: write to research_ledger.tsv (every trial + winner verdict)
    if write_ledger:
        import subprocess
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            commit = "nogit"
        for i, t in enumerate(trials):
            is_winner = i == winner_idx
            row_status = (verdict if is_winner else "discard")
            ledger_append(Entry(
                strategy_id=f"{t.name}/{t.label}",
                commit=commit, status=row_status,
                oos_deflated_sharpe=round(t.oos_deflated_sharpe, 4) if is_winner else 0.0,
                oos_sortino=round(t.oos_sortino, 4) if is_winner else 0.0,
                oos_max_dd=round(t.oos_max_dd, 4) if is_winner else 0.0,
                n_trials=len(trials),
                n_params=len(t.params),
                objective=round(score.objective if is_winner else 0.0, 4),
                description=(f"proper_research IS->OOS split @ {in_sample_end} | "
                             f"IS Sortino {t.is_sortino:+.2f}"
                             + (" | WINNER" if is_winner else "")),
            ))
        print(f"\n  -> {len(trials)} trials + winner verdict appended to research_ledger.tsv")

    return {"winner": winner, "trials": trials, "score": score}


def main() -> int:
    ap = argparse.ArgumentParser(description="OOS + deflated-Sharpe research protocol.")
    ap.add_argument("--in-sample-end", default="2018-12-31",
                    help="date that ends in-sample slice (rest = OOS)")
    ap.add_argument("--oos-end", default="2024-12-31")
    ap.add_argument("--source", default="auto")
    ap.add_argument("--no-ledger", action="store_true",
                    help="don't write to research_ledger.tsv")
    args = ap.parse_args()
    run(
        in_sample_end=date.fromisoformat(args.in_sample_end),
        oos_end=date.fromisoformat(args.oos_end),
        source=args.source,
        write_ledger=not args.no_ledger,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
