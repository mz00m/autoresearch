"""Top-N momentum — diversified cousin of dual_momentum.

Where ``dual_momentum`` concentrates 100% into the single best-trending asset
(big swings, big regret), this rule splits equally across the top-N. Trades
some upside for variance reduction without giving up the trend-following
character. Still long-only, weights sum to 1.0, bounded liability holds.

Absolute-momentum gate is shared with the dual_momentum implementation: any
asset whose trailing return is below the T-bill window return is excluded
from the top-N pool (so all three could fall back to cash in a deep risk-off).
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class TopNMomentum:
    universe: tuple[str, ...]
    n: int = 2
    lookback_days: int = 126   # ~6 months

    @property
    def n_params(self) -> int:
        return 2  # n and lookback

    @property
    def name(self) -> str:
        return f"top-{self.n} momentum lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_window_ret = annual_rate * (self.lookback_days / 252.0)

        candidates: list[tuple[float, str]] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is None:
                continue
            if r <= tbill_window_ret:  # absolute-momentum gate
                continue
            candidates.append((r, sym))

        if not candidates:
            return {CASH: 1.0}
        candidates.sort(reverse=True)
        picks = candidates[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
