"""All-Weather (Bridgewater / Ray Dalio).

Premise: economic regimes are determined by two axes — growth (high/low)
and inflation (high/low) — giving 4 buckets. Each bucket has assets that
do well. By holding ~25% risk in each bucket, the portfolio is "all-weather"
across regimes. Bridgewater's institutional version uses leveraged bonds to
equalize risk; the retail simplification uses fixed dollar weights:

  30% US stocks (SPY)             — growth-up bucket
  40% long bonds (TLT)            — growth-down bucket (rates fall in slowdowns)
  15% intermediate bonds (AGG)    — sleeve, dampens TLT vol
  7.5% gold (GLD)                 — inflation-up bucket
  7.5% commodities (USO)          — inflation-up bucket

Fixed-weight monthly rebalance. Zero tunable parameters. The defensive
sibling of 60/40 — different regime bets, similar low maintenance.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class AllWeather:
    @property
    def n_params(self) -> int:
        return 0

    @property
    def name(self) -> str:
        return "All-Weather (30/40/15/7.5/7.5 SPY/TLT/AGG/GLD/USO)"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        base = {"SPY": 0.30, "TLT": 0.40, "AGG": 0.15, "GLD": 0.075, "USO": 0.075}
        # If any symbol is missing data, route its share to cash so weights
        # still sum to 1.0.
        out: dict[str, float] = {}
        missing_share = 0.0
        for sym, w in base.items():
            ps = panel_asof.series.get(sym)
            if ps and ps.last is not None:
                out[sym] = w
            else:
                missing_share += w
        if missing_share > 0:
            out[CASH] = missing_share
        return out
