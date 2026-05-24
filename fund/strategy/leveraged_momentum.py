"""Leveraged-ETF momentum — the spicy cousin of dual_momentum.

Universe is daily-rebalanced 2x/3x ETFs (TQQQ, SOXL, UPRO, TMF, UGL). Holds
the top-N trending names that clear the T-bill gate, equal-weighted. Long-only
and weights sum to 1.0, so bounded liability still holds — the most you can
lose on any position is the cash you put into it, which is the whole point of
buying the ETF instead of using actual leverage.

Two important caveats baked into the design:

  1. **Path dependence.** 3x leveraged ETFs deliver 3x the *daily* return, not
     3x the cumulative return. In choppy markets they decay even when the
     underlying is flat. Momentum is exactly the regime where this hurts least:
     trending markets compound the leverage in your favor.
  2. **Vol budget.** A single 3x position can drop 30% in a day on a 10% move.
     The T-bill gate filters out risk-off regimes, and the top-N split caps
     concentration — but a deep -30% session is plausible. This is the strategy
     for capital you're willing to swing.

A real -50% drawdown here would not breach the §2 one-rule (you still owe
nothing), but it would absolutely breach the §6 watchlist limits if you set
``drawdown_halt_frac=0.35``. Set the halt explicitly if you run this live.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH

# 2x and 3x ETFs spanning equity, semis, long bonds, and gold.
# UVXY is deliberately excluded — VIX-future ETFs decay too aggressively to
# hold across days, even on a momentum signal.
LEVERAGED_UNIVERSE = ("TQQQ", "SOXL", "UPRO", "TMF", "UGL")


@dataclass(frozen=True)
class LeveragedMomentum:
    universe: tuple[str, ...] = LEVERAGED_UNIVERSE
    n: int = 2
    lookback_days: int = 63   # 3 months — leveraged trends move faster

    @property
    def n_params(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return f"leveraged-momentum top-{self.n} lb={self.lookback_days}d"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        annual_rate = (tbill_asof.last or 0.0) / 100.0
        tbill_window_ret = annual_rate * (self.lookback_days / 252.0)

        cands: list[tuple[float, str]] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is None:
                continue
            if r <= tbill_window_ret:
                continue
            cands.append((r, sym))

        if not cands:
            return {CASH: 1.0}
        cands.sort(reverse=True)
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
