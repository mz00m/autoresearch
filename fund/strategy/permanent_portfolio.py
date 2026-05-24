"""Permanent Portfolio (Harry Browne, "Fail-Safe Investing", 1981).

Four equal buckets, one for each major economic state:
  25% US stocks (SPY)  — prosperity
  25% long bonds (TLT) — deflation
  25% gold (GLD)       — inflation
  25% cash/T-bills (BIL) — recession

Real-world track record across 40+ years: lower returns than 60/40 but
much smoother. Rarely loses more than ~5% in a calendar year. The
"if it ever blows up, capitalism is over" baseline. Zero knobs.

Implementation notes:
  - BIL is the cash sleeve (1-3mo T-bills) — earns the cash rate.
  - Monthly rebalance back to 25/25/25/25 is enforced by the harness.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class PermanentPortfolio:
    @property
    def n_params(self) -> int:
        return 0

    @property
    def name(self) -> str:
        return "Permanent Portfolio (25 × 4: SPY/TLT/GLD/BIL)"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        base = {"SPY": 0.25, "TLT": 0.25, "GLD": 0.25, "BIL": 0.25}
        out: dict[str, float] = {}
        missing = 0.0
        for sym, w in base.items():
            ps = panel_asof.series.get(sym)
            if ps and ps.last is not None:
                out[sym] = w
            else:
                missing += w
        if missing > 0:
            out[CASH] = missing
        return out
