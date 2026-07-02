"""Time-series momentum (Moskowitz, Ooi, Pedersen 2012, "Time Series Momentum").

Where cross-sectional momentum compares assets to each other, time-series
momentum judges each asset on its OWN trailing return — positive means hold,
negative means cash. Documented across 58 instruments / 25 years / multiple
asset classes; the most universally-validated tactical signal in the literature.

Implementation: each asset gets a 1/N share if its trailing return > 0
(or > T-bill floor), 0 otherwise. The number of assets held varies with
how many are trending. In a strong broad uptrend, fully invested; in a
broad downturn, mostly cash.

Two tunable params (lookback, T-bill gate) — minimal overfit surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class TimeSeriesMomentum:
    universe: tuple[str, ...]
    lookback_days: int = 252

    @property
    def n_params(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return f"time-series momentum lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_floor = annual_rate * (self.lookback_days / 252.0)

        holders: list[str] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is None or r <= tbill_floor:
                continue
            holders.append(sym)

        if not holders:
            return {CASH: 1.0}
        w = 1.0 / len(holders)
        return {sym: w for sym in holders}
