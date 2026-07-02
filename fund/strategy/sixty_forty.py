"""Sixty-forty — the everyman's benchmark.

Fixed 60% SPY / 40% AGG, rebalanced on the harness's monthly cadence. Not a
discovered edge — a *baseline* every other strategy must beat to be worth
running. Long-only by construction, so bounded liability holds trivially.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class SixtyForty:
    equity: str = "SPY"
    bonds: str = "AGG"
    equity_weight: float = 0.60

    @property
    def n_params(self) -> int:
        return 0  # fixed weights; no tuning

    @property
    def name(self) -> str:
        return f"60/40 {self.equity}/{self.bonds}"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        eq = panel_asof.series.get(self.equity)
        bd = panel_asof.series.get(self.bonds)
        if eq is None or eq.last is None or bd is None or bd.last is None:
            return {CASH: 1.0}
        return {self.equity: self.equity_weight,
                self.bonds: 1.0 - self.equity_weight}
