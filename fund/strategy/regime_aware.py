"""Regime-aware allocator — forward-correlated macro signals, not trailing returns.

The honest-test data showed that the trailing-Sortino picker (``adaptive``)
chases noise. This is the alternative: classify today's market state from
*forward-correlated* signals — signals that *describe current risk pricing*
rather than past performance — and route allocation to the strategy that
historically fits that regime.

Signals (all cheap, daily, free):

  * **VIX level** (^VIX) — implied vol of SPX options, a real-time fear gauge.
    < 17 calm; 17-25 normal; 25-35 stressed; > 35 panic.
  * **Yield curve slope** (^TNX 10y - ^IRX 3mo) — recession lead indicator.
    Positive and steepening = expansion; flat or inverted = late-cycle stress.
  * **SPY 200d trend** — golden-cross filter. Below 200d = defensive bias.

Regime → routing:

  CALM       → top_n_momentum (aggressive, captures trend persistence)
  NORMAL     → top_n_momentum (same — still risk-on territory)
  STRESSED   → risk_parity (smooth equity, bond-heavy)
  PANIC      → sixty_forty (max defense within the bench)

The classifier is a simple decision tree, not ML. The whole point is that the
signal *isn't* "what just worked" — it's "what's the world like right now."
That can fail too (no detector is perfect), but it fails differently from
trailing-return chasing — and the two failure modes are uncorrelated.

When VIX or curve data isn't loaded in the panel, falls back to NORMAL
(top_n_momentum). When SPY isn't loaded, runs without the trend filter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


REGIMES = ("CALM", "NORMAL", "STRESSED", "PANIC")

# Regime → (strategy_name, params)
DEFAULT_ROUTING: dict[str, tuple[str, dict]] = {
    "CALM":     ("top_n_momentum", {"n": 2, "lookback_days": 126}),
    "NORMAL":   ("top_n_momentum", {"n": 2, "lookback_days": 126}),
    "STRESSED": ("risk_parity",    {"vol_window": 63}),
    "PANIC":    ("sixty_forty",    {}),
}


def _sma(closes: tuple[float, ...], window: int) -> float | None:
    if len(closes) < window or window <= 0:
        return None
    return sum(closes[-window:]) / window


def _classify(panel_asof: Panel) -> tuple[str, dict]:
    """Return (regime_label, signals_dict). Defensive against missing data."""
    signals: dict = {}

    vix = panel_asof.series.get("^VIX")
    vix_level = vix.last if vix and vix.last is not None else None
    signals["vix"] = vix_level

    tnx = panel_asof.series.get("^TNX")
    irx = panel_asof.series.get("^IRX")
    tnx_level = tnx.last if tnx and tnx.last is not None else None
    irx_level = irx.last if irx and irx.last is not None else None
    curve_slope = (tnx_level - irx_level) if (tnx_level is not None
                                              and irx_level is not None) else None
    signals["tnx"] = tnx_level
    signals["irx"] = irx_level
    signals["curve_slope"] = curve_slope

    spy = panel_asof.series.get("SPY")
    spy_above_200d: bool | None = None
    if spy and len(spy.closes) >= 200:
        sma200 = _sma(spy.closes, 200)
        if sma200 is not None:
            spy_above_200d = spy.closes[-1] > sma200
    signals["spy_above_200d"] = spy_above_200d

    # Decision tree — order matters, most-severe first.
    if vix_level is not None and vix_level > 35:
        return "PANIC", signals
    if vix_level is not None and vix_level > 25:
        return "STRESSED", signals
    if curve_slope is not None and curve_slope < -0.5:
        return "STRESSED", signals  # deeply inverted
    if spy_above_200d is False:
        return "STRESSED", signals  # SPY in confirmed downtrend
    if vix_level is not None and vix_level < 17 and (
            curve_slope is None or curve_slope > 0) and (
            spy_above_200d is None or spy_above_200d):
        return "CALM", signals
    return "NORMAL", signals


@dataclass(frozen=True)
class RegimeAwareAllocator:
    routing: dict[str, tuple[str, dict]] = None  # type: ignore[assignment]

    def __post_init__(self):
        # Frozen dataclass workaround for mutable default
        if self.routing is None:
            object.__setattr__(self, "routing", dict(DEFAULT_ROUTING))

    @property
    def n_params(self) -> int:
        # The thresholds are constants of the design, not tunable knobs.
        return 0

    @property
    def name(self) -> str:
        return "regime-aware (VIX + curve + 200d trend)"

    def classify(self, panel_asof: Panel) -> tuple[str, dict]:
        """Expose classification for the dashboard / debugging."""
        return _classify(panel_asof)

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        from fund.strategy.registry import build as build_strategy

        regime, _signals = _classify(panel_asof)
        strat_name, params = self.routing.get(regime, ("sixty_forty", {}))
        try:
            strat = build_strategy(strat_name, params)
        except Exception:
            return {CASH: 1.0}
        return strat.target_weights(panel_asof, tbill_asof)
