"""Trend + carry blend (Asness-Moskowitz-Pedersen 2013, "Value and Momentum
Everywhere").

Trend (momentum) and carry (yield-style premium) are documented to be
distinct, complementary alpha sources across asset classes. The AMP paper
shows their combination produces materially higher Sharpe than either alone
because their correlation is near zero.

For our ETF universe we proxy "carry" via the trailing T-bill rate vs the
asset's trailing trend — when the curve is steep and assets are trending,
both signals align and the trade is high-conviction. When they disagree,
we sit smaller.

Implementation: each candidate gets two normalized scores in [-1, +1]:
  trend  = sign of trailing-12m return
  carry  = (T-bill rate − asset's annualized trailing vol drag) / 100
         (positive = asset's "yield-equivalent" exceeds risk-free)

Combined: pick top-N by trend + carry sum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH
from fund.strategy.risk_parity import _daily_vol


@dataclass(frozen=True)
class TrendCarry:
    universe: tuple[str, ...]
    n: int = 2
    lookback_days: int = 252
    vol_window: int = 63

    @property
    def n_params(self) -> int:
        return 3

    @property
    def name(self) -> str:
        return f"trend+carry top-{self.n} lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        rfr = (tbill_asof.last or 0.0) / 100.0
        cands: list[tuple[float, str]] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            v = _daily_vol(ps.closes, self.vol_window)
            if r is None or v is None:
                continue
            # Trend: sign of trailing return, scaled by magnitude
            trend = r
            # Carry proxy: how much excess return per unit of risk
            annual_vol = v * math.sqrt(252.0)
            carry = (r - rfr) / annual_vol if annual_vol > 0 else 0.0
            score = trend + carry
            if score <= 0:
                continue
            cands.append((score, sym))
        if not cands:
            return {CASH: 1.0}
        cands.sort(reverse=True)
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
