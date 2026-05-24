"""Skip-month momentum (Jegadeesh-Titman 1993).

Standard academic fix for raw-trailing momentum: the last ~21 trading days
exhibit short-term mean reversion, while the 12-2 month window (drop the
most recent month) is the cleanest persistent-trend signal. Originally
documented for equity cross-sections; works on ETFs as a regime-detector
overlay.

  signal = trailing_252d_return − trailing_21d_return
         ≈ "what did this do from month-12 to month-2, ignoring last month"

Pick top-N by that score, gated by T-bill floor.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class SkipMonthMomentum:
    universe: tuple[str, ...]
    n: int = 2
    long_lookback: int = 252
    skip_lookback: int = 21

    @property
    def n_params(self) -> int:
        return 3   # n, long_lookback, skip_lookback

    @property
    def name(self) -> str:
        return f"skip-month momentum top-{self.n} ({self.long_lookback}d − {self.skip_lookback}d)"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_floor = annual_rate * (self.long_lookback / 252.0)

        cands: list[tuple[float, str]] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r_long = ps.trailing_return(self.long_lookback)
            r_skip = ps.trailing_return(self.skip_lookback)
            if r_long is None or r_skip is None:
                continue
            score = r_long - r_skip
            if score <= tbill_floor:
                continue
            cands.append((score, sym))
        if not cands:
            return {CASH: 1.0}
        cands.sort(reverse=True)
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
