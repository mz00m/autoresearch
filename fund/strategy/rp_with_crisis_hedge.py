"""Risk parity with an explicit crisis hedge sleeve.

Standard risk parity weights inversely to vol, which already lands bond-heavy.
This adds an explicit long-duration sleeve (TLT) sized as a fixed crisis
hedge. Premise: in equity crises, long-dated Treasuries rally hard
(flight-to-quality) — having a dedicated bucket sized for that lifts the
portfolio's worst-month performance materially. The cost is mild drag in
flat or rising-rate regimes.

  hedge_share fraction  -> TLT
  remainder             -> standard inverse-vol risk parity across universe
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH
from fund.strategy.risk_parity import _daily_vol


@dataclass(frozen=True)
class RiskParityCrisisHedge:
    universe: tuple[str, ...]
    vol_window: int = 63
    hedge_share: float = 0.15   # 15% in TLT regardless

    @property
    def n_params(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return f"risk-parity + {int(self.hedge_share * 100)}% TLT crisis hedge"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        # Inverse-vol weights over the universe (excl. TLT to avoid double-count)
        rp_universe = tuple(s for s in self.universe if s != "TLT")
        inv_vols: dict[str, float] = {}
        for sym in rp_universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            v = _daily_vol(ps.closes, self.vol_window)
            if v is None or v <= 0:
                continue
            inv_vols[sym] = 1.0 / v
        total = sum(inv_vols.values())
        rp_share = 1.0 - self.hedge_share
        out: dict[str, float] = {}
        if total > 0:
            for sym, iv in inv_vols.items():
                out[sym] = rp_share * (iv / total)
        else:
            out[CASH] = rp_share

        # TLT hedge sleeve — if TLT isn't loaded, fall back to AGG
        tlt = panel_asof.series.get("TLT")
        agg = panel_asof.series.get("AGG")
        if tlt and tlt.last is not None:
            out["TLT"] = out.get("TLT", 0.0) + self.hedge_share
        elif agg and agg.last is not None:
            out["AGG"] = out.get("AGG", 0.0) + self.hedge_share
        else:
            out[CASH] = out.get(CASH, 0.0) + self.hedge_share
        return out
