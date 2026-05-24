"""Vol-scaled momentum — Sharpe-like ranking, not raw trailing return.

Premise: raw 126d-trailing-return picking over-weights the most fragile,
most catalyst-dependent assets. USO at +98% trailing (vol ~30%) is a
different bet than XLE at +34% (vol ~18%) — the same momentum signal but
much more bid-up risk. Scaling by inverse vol prefers smoother, more
durable trends.

  score = trailing_return(lookback) / trailing_vol(vol_window)

Then pick top-N by score, gated by the T-bill floor (same as
top_n_momentum). Long-only, weights sum to 1.0, bounded liability holds.

Same architecture as top_n_momentum. Three tunable params (n, lookback,
vol_window) is one more than top_n's two — the deflated-Sharpe penalty
discounts this; the strategy must clear a meaningfully higher bar to be
worth running.

The empirical question for this strategy: does the vol scaling actually
improve the selection, or does it just penalize the very trends we want
to ride? honest_test will tell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH
from fund.strategy.risk_parity import _daily_vol


@dataclass(frozen=True)
class VolScaledMomentum:
    universe: tuple[str, ...]
    n: int = 2
    lookback_days: int = 126
    vol_window: int = 63

    @property
    def n_params(self) -> int:
        return 3   # n, lookback, vol_window

    @property
    def name(self) -> str:
        return (f"vol-scaled momentum top-{self.n} "
                f"lb={self.lookback_days}d vol={self.vol_window}d")

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_window_ret = annual_rate * (self.lookback_days / 252.0)

        cands: list[tuple[float, str]] = []   # (score, symbol)
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            ret = ps.trailing_return(self.lookback_days)
            if ret is None or ret <= tbill_window_ret:
                continue
            vol = _daily_vol(ps.closes, self.vol_window)
            if vol is None or vol <= 0:
                continue
            # Annualize realized vol so the score has Sharpe-like units
            annual_vol = vol * math.sqrt(252.0)
            score = ret / annual_vol if annual_vol > 0 else float("-inf")
            cands.append((score, sym))

        if not cands:
            return {CASH: 1.0}
        cands.sort(reverse=True)
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
