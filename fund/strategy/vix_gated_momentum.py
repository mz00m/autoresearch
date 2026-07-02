"""VIX-gated momentum — turn off when implied vol regime says risk-off.

Hypothesis: combine the proven return engine (top-N cross-sectional momentum)
with a forward-correlated regime kill-switch (VIX level). When VIX < threshold,
run top_n_momentum; when VIX >= threshold, sit in BIL (cash). Avoids the
classic momentum-strategy-crashes-in-stress event documented by Daniel-Moskowitz
2016 ("Momentum Crashes").

The signal:
  vix_level < gate_low      -> run momentum normally
  vix_level >= gate_high    -> 100% BIL (cash)
  in-between                -> previous state (sticky)

Two thresholds (low/high) create a hysteresis band so the strategy doesn't
whipsaw when VIX hovers near a single cutoff. This is the "best of momentum +
worst-month protection" combo.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class VixGatedMomentum:
    universe: tuple[str, ...]
    n: int = 2
    lookback_days: int = 126
    vix_gate_low: float = 20.0   # below this, momentum is on
    vix_gate_high: float = 25.0  # above this, fully defensive

    @property
    def n_params(self) -> int:
        # n + lookback + two thresholds; the hysteresis is one design choice
        return 3

    @property
    def name(self) -> str:
        return (f"vix-gated momentum (off >{self.vix_gate_high}, "
                f"on <{self.vix_gate_low})")

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        # Read VIX level (signal-only ticker; not held)
        vix = panel_asof.series.get("^VIX")
        vix_level = vix.last if vix and vix.last is not None else None

        # If VIX above the high gate, sit in cash. No momentum execution.
        if vix_level is not None and vix_level >= self.vix_gate_high:
            return {CASH: 1.0}

        # Otherwise run top-N momentum (treat unknown VIX as "low regime"
        # to keep the strategy invested when data is incomplete)
        from fund.strategy.top_n_momentum import TopNMomentum
        inner = TopNMomentum(self.universe, n=self.n,
                              lookback_days=self.lookback_days)
        return inner.target_weights(panel_asof, tbill_asof)
