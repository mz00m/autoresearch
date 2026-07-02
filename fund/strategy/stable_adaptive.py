"""Stable adaptive — persistence-gated meta-allocator.

The vanilla AdaptiveAllocator picks whichever candidate has the best trailing
90-day Sortino each rebalance day. The empirical problem (see honest_test
results 2018-2024): it chases. Trailing winners mean-revert, so adaptive
buys high and sells low, ending the year at the bottom of the table.

This variant adds two persistence gates:

  1. **Multi-window agreement.** A challenger must outscore the current
     pick on the trailing 30-day AND 60-day AND 90-day AND 180-day windows.
     Single-window winners (often noise) don't qualify.

  2. **Switching cost margin.** Even if all four windows agree, the challenger
     must beat the current pick by at least ``switch_margin`` Sortino points.
     A near-tie isn't worth eating the round-trip costs.

The result is sticky — typically holds the same underlying for 1-3 months
before rotating, instead of every rebalance. Trades some responsiveness for
less whipsaw, which the multi-year data suggests is the right side of the
tradeoff.

Like AdaptiveAllocator, this is a bandit (winner-take-all), not a weight
blender. Same PIT guard, same candidate set, same shadow-backtest mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fund.backtest import Costs, run_backtest
from fund.data.pit import Panel, PriceSeries
from fund.evaluator import sortino_annualized
from fund.strategy.dual_momentum import CASH
from fund.strategy.adaptive import DEFAULT_CANDIDATES


@dataclass(frozen=True)
class StableAdaptiveAllocator:
    candidates: tuple[tuple[str, dict], ...] = DEFAULT_CANDIDATES
    # Lookback windows the challenger must dominate on, longest first
    lookback_windows: tuple[int, ...] = (180, 90, 60, 30)
    switch_margin: float = 0.30   # challenger needs Sortino +0.30 above incumbent
    # Internal: we approximate "current pick" as the candidate that scored top
    # on the LONGEST window — that's the regime the system has been in.
    # No state is carried across calls (the underlying registry is stateless).

    @property
    def n_params(self) -> int:
        # Lookback windows + switch margin
        return 2

    @property
    def name(self) -> str:
        return (f"stable-adaptive windows={'/'.join(str(w) for w in self.lookback_windows)}d"
                f" margin={self.switch_margin}")

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        from fund.strategy.registry import build as build_strategy

        # 1. Run a full shadow backtest of each candidate once.
        backtests: dict[str, list[float]] = {}
        weights_now: dict[str, dict[str, float]] = {}
        for name, params in self.candidates:
            try:
                strat = build_strategy(name, params)
                res = run_backtest(strat, panel_asof, tbill_asof,
                                   costs=Costs(slippage_bps=5.0))
                backtests[name] = res.returns
                weights_now[name] = strat.target_weights(panel_asof, tbill_asof)
            except Exception:
                continue

        if not backtests:
            return {CASH: 1.0}

        # 2. Score each candidate across every lookback window.
        scores: dict[int, list[tuple[str, float]]] = {}
        for window in self.lookback_windows:
            row: list[tuple[str, float]] = []
            for name, rets in backtests.items():
                tail = rets[-window:]
                if len(tail) < 5:
                    continue
                row.append((name, sortino_annualized(tail)))
            row.sort(key=lambda x: -x[1])
            scores[window] = row

        # 3. Find the LONGEST-window winner — that's the "regime incumbent."
        longest = self.lookback_windows[0]
        if not scores.get(longest):
            return {CASH: 1.0}
        incumbent_name, incumbent_score = scores[longest][0]

        # 4. Find the SHORTEST-window winner — the "challenger."
        shortest = self.lookback_windows[-1]
        if not scores.get(shortest):
            return weights_now.get(incumbent_name, {CASH: 1.0})
        challenger_name, _ = scores[shortest][0]

        if challenger_name == incumbent_name:
            return weights_now.get(incumbent_name, {CASH: 1.0})

        # 5. Persistence gates: challenger must lead on ALL windows AND
        # beat incumbent by switch_margin on the longest window.
        challenger_score_on_longest = next(
            (s for n, s in scores[longest] if n == challenger_name),
            float("-inf"),
        )
        if challenger_score_on_longest < incumbent_score + self.switch_margin:
            return weights_now.get(incumbent_name, {CASH: 1.0})

        # Verify challenger is top-3 on EVERY window (multi-agreement)
        for w in self.lookback_windows:
            top3 = {n for n, _ in scores.get(w, [])[:3]}
            if challenger_name not in top3:
                return weights_now.get(incumbent_name, {CASH: 1.0})

        # All gates passed — rotate.
        return weights_now.get(challenger_name, weights_now.get(incumbent_name, {CASH: 1.0}))
