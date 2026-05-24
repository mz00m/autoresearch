"""Concentrated leveraged — top-1 (not top-2) leveraged ETF.

The most aggressive long-only ETF strategy that respects §2: pick the
single best-trending 3x leveraged ETF and put 100% there. Max
concentration in a leveraged instrument. The 10% trailing stop is your
only floor below §2's bounded-liability rule.

Adversarial review (red_team) ranks leveraged momentum among the most
fragile in the bench. This is even MORE fragile — n=1 instead of n=2.
Use it only if you genuinely believe the trend will continue for the
next rebalance cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH
from fund.strategy.leveraged_momentum import LEVERAGED_UNIVERSE


@dataclass(frozen=True)
class ConcentratedLeveraged:
    universe: tuple[str, ...] = LEVERAGED_UNIVERSE
    lookback_days: int = 42       # short window — these move fast

    @property
    def n_params(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return f"concentrated-leveraged top-1 lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_floor = annual_rate * (self.lookback_days / 252.0)
        best_sym, best_score = None, float("-inf")
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is None or r <= tbill_floor:
                continue
            if r > best_score:
                best_score, best_sym = r, sym
        if best_sym is None:
            return {CASH: 1.0}
        return {best_sym: 1.0}
