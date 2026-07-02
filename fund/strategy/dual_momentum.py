"""Dual-momentum strategy spec (Antonacci-style GEM).

A single, reviewable strategy spec — the analog of one edit to ``train.py``.
Two gates, both long-only (so bounded-liability holds automatically):

  1. Relative momentum: hold the asset with the best trailing return.
  2. Absolute momentum: but only if that return beats the T-bill over the same
     window; otherwise sit in CASH.

It is handed an *already point-in-time-sliced* panel, so it cannot see the
future. Only one tunable parameter (lookback), which keeps overfit surface small.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries

CASH = "CASH"


@dataclass(frozen=True)
class DualMomentum:
    universe: tuple[str, ...]
    lookback_days: int = 252  # ~12 months

    @property
    def n_params(self) -> int:
        return 1  # universe is fixed; only the lookback is tuned

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        best_sym, best_ret = None, float("-inf")
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is not None and r > best_ret:
                best_sym, best_ret = sym, r

        if best_sym is None:
            return {CASH: 1.0}

        # absolute momentum: compare to the T-bill return over the same window
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_window_ret = annual_rate * (self.lookback_days / 252.0)
        if best_ret <= tbill_window_ret:
            return {CASH: 1.0}
        return {best_sym: 1.0}
