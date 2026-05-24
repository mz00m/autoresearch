"""Adaptive allocator — the closest thing to "learning" in this repo.

A meta-strategy that, on every rebalance, runs a quick shadow backtest of each
bench candidate over the trailing window and routes that day's allocation
through the highest Sortino candidate. The feedback loop is real: yesterday's
relative performance shapes today's allocation, *without* any peeking past
``panel_asof`` (the PIT guard still holds — see fund/data/pit.py).

This is a bandit, not an ML model. There's no parameter learning, no
gradient descent — just "which simple strategy is currently working best on
this real history?" picked fresh each rebalance day. That's a fair definition
of learning for a system whose primary defense against overfitting is keeping
the moving parts countable.

What it does NOT do:
  * Mix multiple strategies' weights into a blend (it's winner-take-all).
  * See the locked OOS vault — same guard as every other strategy.
  * Modify any strategy's parameters; only the *choice* of which to delegate to.

Caveat: this strategy backs the trailing winner. In rapid regime changes it
can chase. The 90-day default lookback is a compromise between responsiveness
and stability; if you set it shorter, expect more whipsaws.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.backtest import Costs, run_backtest
from fund.data.pit import Panel, PriceSeries
from fund.evaluator import sortino_annualized
from fund.strategy.dual_momentum import CASH

# Default bench excludes 'adaptive' itself (no recursion) and 'leveraged_momentum'
# (different universe — let it be opted in explicitly).
DEFAULT_CANDIDATES: tuple[tuple[str, dict], ...] = (
    ("sixty_forty", {}),
    ("dual_momentum", {"lookback_days": 252}),
    ("dual_momentum", {"lookback_days": 126}),
    ("risk_parity", {"vol_window": 63}),
    ("top_n_momentum", {"n": 2, "lookback_days": 126}),
    ("ma_crossover", {"fast": 50, "slow": 200}),
)


@dataclass(frozen=True)
class AdaptiveAllocator:
    candidates: tuple[tuple[str, dict], ...] = DEFAULT_CANDIDATES
    lookback_days: int = 90

    @property
    def n_params(self) -> int:
        # The candidate set is architectural, not tunable; only the window matters
        # for overfitting accounting.
        return 1

    @property
    def name(self) -> str:
        return f"adaptive best-of-{len(self.candidates)} lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        # Local import keeps the registry import graph free of cycles.
        from fund.strategy.registry import build as build_strategy

        best_score = float("-inf")
        best_weights: dict[str, float] = {CASH: 1.0}
        for name, params in self.candidates:
            try:
                strat = build_strategy(name, params)
            except (ValueError, KeyError):
                continue
            try:
                res = run_backtest(strat, panel_asof, tbill_asof,
                                   costs=Costs(slippage_bps=5.0))
            except Exception:
                continue
            returns = res.returns[-self.lookback_days:]
            if len(returns) < 5:
                continue
            score = sortino_annualized(returns)
            if score > best_score:
                best_score = score
                best_weights = strat.target_weights(panel_asof, tbill_asof)
        return best_weights
