"""Faber Global Tactical Asset Allocation (Faber 2007, "A Quantitative Approach
to Tactical Asset Allocation").

The most widely-replicated tactical strategy in practitioner literature.
One rule: for each asset, hold a 1/N share if price > its 10-month SMA
(~200-day), else hold cash for that slice. Conservative, slow, monthly
rebalance. Demonstrated to roughly match buy-and-hold returns with ~half
the drawdown across 5 asset classes / 1973-2020.

Faber's original universe was 5 broad indices (US stocks, intl stocks,
US bonds, commodities, real estate). We map to our ETF universe:
  US large       -> SPY
  Intl developed -> EFA
  US bonds       -> AGG
  Real assets    -> GLD
  Commodities    -> USO (oil proxy)

Each gets 1/5 weight if above its SMA; cash otherwise. Sum < 1 means
the rest sits in cash.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH

# Sticking close to Faber's original 5 asset classes
FABER_UNIVERSE = ("SPY", "EFA", "AGG", "GLD", "USO")


def _above_sma(closes: tuple[float, ...], window: int) -> bool | None:
    if len(closes) < window:
        return None
    sma = sum(closes[-window:]) / window
    return closes[-1] > sma


@dataclass(frozen=True)
class FaberGTAA:
    universe: tuple[str, ...] = FABER_UNIVERSE
    sma_window: int = 200   # ~10 months of trading days

    @property
    def n_params(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return f"Faber GTAA (SMA{self.sma_window}) on {len(self.universe)} assets"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        share = 1.0 / len(self.universe)
        out: dict[str, float] = {}
        cash_share = 0.0
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            verdict = _above_sma(ps.closes, self.sma_window) if ps else None
            if verdict is True:
                out[sym] = share
            else:
                # Couldn't compute or below SMA -> that slice goes to cash
                cash_share += share
        if cash_share > 0:
            out[CASH] = cash_share
        if not out:
            return {CASH: 1.0}
        return out
