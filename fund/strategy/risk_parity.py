"""Inverse-volatility ("risk parity-lite") weighting.

True risk parity requires the full covariance matrix. For a small ETF universe
the inverse-vol approximation captures most of the benefit: each asset gets
weight ~ 1/sigma_i, so each contributes roughly equally to portfolio vol *under
the assumption of equal correlations*. Long-only and weights sum to 1.0, so
bounded liability holds.

One tunable parameter (the vol-estimation window), which keeps overfit surface
small. Slow-moving — typically <12 rebalances/year of meaningful turnover.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


def _daily_vol(closes: tuple[float, ...], window: int) -> float | None:
    """Stdev of last `window` daily log-returns. None if insufficient history."""
    if len(closes) <= window:
        return None
    rets = []
    for i in range(len(closes) - window, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev <= 0 or cur <= 0:
            return None
        rets.append(math.log(cur / prev))
    if not rets:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    return math.sqrt(var)


@dataclass(frozen=True)
class RiskParity:
    universe: tuple[str, ...]
    vol_window: int = 63  # ~3 months of daily returns

    @property
    def n_params(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return f"risk-parity w={self.vol_window}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        inv_vols: dict[str, float] = {}
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            v = _daily_vol(ps.closes, self.vol_window)
            if v is None or v <= 0:
                continue
            inv_vols[sym] = 1.0 / v
        total = sum(inv_vols.values())
        if total <= 0:
            return {CASH: 1.0}
        return {sym: w / total for sym, w in inv_vols.items()}
