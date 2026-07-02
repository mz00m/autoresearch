"""Moving-average crossover — classic regime filter.

If the asset's fast SMA is above its slow SMA, fully invest in it; otherwise
sit in cash. The canonical 50/200 is intentionally slow — it accepts you'll
miss the bottom and the top in exchange for almost never being whipsawed in
choppy markets. One asset, one regime call. Bounded liability holds because
the only two states are 100% long the asset or 100% cash.

Two tunables (fast and slow). Per Bailey-Lopez de Prado, more knobs == more
overfit surface, so this strategy must clear a meaningfully higher deflated-
Sharpe bar than the zero-param sixty_forty to be worth running.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


def _sma(closes: tuple[float, ...], window: int) -> float | None:
    if len(closes) < window or window <= 0:
        return None
    return sum(closes[-window:]) / window


@dataclass(frozen=True)
class MovingAverageCrossover:
    asset: str = "SPY"
    fast: int = 50
    slow: int = 200

    @property
    def n_params(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return f"MA crossover {self.fast}/{self.slow} {self.asset}"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        ps = panel_asof.series.get(self.asset)
        if ps is None:
            return {CASH: 1.0}
        fast = _sma(ps.closes, self.fast)
        slow = _sma(ps.closes, self.slow)
        if fast is None or slow is None:
            return {CASH: 1.0}
        return {self.asset: 1.0} if fast > slow else {CASH: 1.0}
