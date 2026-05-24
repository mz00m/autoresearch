"""Contrarian / mean-reversion baseline (DeBondt-Thaler 1985 + Lo-MacKinlay).

The honest negative-result strategy. Take the BOTTOM-N trailing-return
assets each rebalance — "buy the losers." Documented to work in equity
cross-sections at multi-year horizons, well-known to FAIL at monthly
horizons (where momentum dominates).

We expect this to underperform — the value is in seeing HOW MUCH it
underperforms, which gives an upper bound on how much pure momentum is
worth in this universe.

  signal = trailing_lookback_days return
  pick:   the N WORST scores (no gate)
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class MeanReversion:
    universe: tuple[str, ...]
    n: int = 2
    lookback_days: int = 126

    @property
    def n_params(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return f"mean-reversion bottom-{self.n} lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        cands: list[tuple[float, str]] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is None:
                continue
            cands.append((r, sym))
        if not cands:
            return {CASH: 1.0}
        cands.sort()   # ascending — worst first
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
