"""Low-vol anomaly (Frazzini & Pedersen, "Betting Against Beta" 2014).

Documented anomaly: low-vol assets historically deliver better
*risk-adjusted* returns than high-vol assets, in violation of CAPM. The
"BAB" trade is long low-vol + short high-vol; we do the long-only
version: hold the bottom-N by trailing realized vol.

Different premise from `vol_scaled_momentum` (which divides return BY vol).
This just picks low-vol assets, period — no return signal. Expected to
underperform in trending markets (would have held AGG forever instead of
QQQ in the 2010s), but smooth-equity in down markets.

Useful as a benchmark to see how much of the bench's drawdown is just
from holding higher-vol assets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH
from fund.strategy.risk_parity import _daily_vol


@dataclass(frozen=True)
class LowVol:
    universe: tuple[str, ...]
    n: int = 3
    vol_window: int = 63

    @property
    def n_params(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return f"low-vol bottom-{self.n} window={self.vol_window}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        cands: list[tuple[float, str]] = []   # (vol, sym) — ascending = low first
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            v = _daily_vol(ps.closes, self.vol_window)
            if v is None or v <= 0:
                continue
            cands.append((v, sym))
        if not cands:
            return {CASH: 1.0}
        cands.sort()   # ascending — lowest vol first
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
