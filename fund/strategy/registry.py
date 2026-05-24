"""Strategy registry — name + params -> strategy object.

Keeps the morning guide and the closeout decoupled from imports; the active
strategy is stored as a string in portfolio_state.json so a human can switch
it without editing Python. Adding a new strategy requires one line here.
"""

from __future__ import annotations

from fund.strategy.adaptive import DEFAULT_CANDIDATES, AdaptiveAllocator
from fund.strategy.all_weather import AllWeather
from fund.strategy.concentrated_leveraged import ConcentratedLeveraged
from fund.strategy.dual_momentum import DualMomentum
from fund.strategy.faber_gtaa import FABER_UNIVERSE, FaberGTAA
from fund.strategy.leveraged_momentum import LEVERAGED_UNIVERSE, LeveragedMomentum
from fund.strategy.low_vol import LowVol
from fund.strategy.ma_crossover import MovingAverageCrossover
from fund.strategy.mean_reversion import MeanReversion
from fund.strategy.multi import MultiStrategy
from fund.strategy.permanent_portfolio import PermanentPortfolio
from fund.strategy.regime_aware import RegimeAwareAllocator
from fund.strategy.risk_parity import RiskParity
from fund.strategy.rp_with_crisis_hedge import RiskParityCrisisHedge
from fund.strategy.single_stock_momentum import CURATED_STOCKS, SingleStockMomentum
from fund.strategy.sixty_forty import SixtyForty
from fund.strategy.skip_month_momentum import SkipMonthMomentum
from fund.strategy.stable_adaptive import StableAdaptiveAllocator
from fund.strategy.time_series_momentum import TimeSeriesMomentum
from fund.strategy.top_n_momentum import TopNMomentum
from fund.strategy.trend_carry import TrendCarry
from fund.strategy.vix_gated_momentum import VixGatedMomentum
from fund.strategy.vol_scaled_momentum import VolScaledMomentum

# Macro tickers consumed by RegimeAwareAllocator. Kept separate from the
# tradeable universe — these are signal-only.
REGIME_SIGNALS = ("^VIX", "^TNX", "^IRX")

# Broad-asset menu the momentum strategies rotate over. The five originals are
# the textbook GEM universe (US equities, intl equities, bonds, gold, tech).
# The four extensions give the strategies a chance to react to geopolitical /
# energy / crypto regimes — when oil trends because of Mideast tension, or
# BTC trends because of monetary regime change, momentum picks them up.
DEFAULT_UNIVERSE = (
    "SPY",  # US large-cap equity
    "EFA",  # international developed equity
    "AGG",  # aggregate bonds
    "GLD",  # gold
    "QQQ",  # Nasdaq-100 (tech)
    "XLE",  # energy sector — moves on oil and geopolitical stress
    "USO",  # WTI oil ETF — direct energy signal
    "URA",  # uranium miners — nuclear/energy security signal
    "BITO",  # BTC futures ETF — monetary regime signal
)


def build(name: str, params: dict | None = None):
    """Resolve a strategy by name + params. Unknown names raise ValueError."""
    params = dict(params or {})
    universe = tuple(params.get("universe", DEFAULT_UNIVERSE))
    if name == "sixty_forty":
        return SixtyForty(
            equity=params.get("equity", "SPY"),
            bonds=params.get("bonds", "AGG"),
            equity_weight=float(params.get("equity_weight", 0.60)),
        )
    if name == "dual_momentum":
        return DualMomentum(
            universe=universe,
            lookback_days=int(params.get("lookback_days", 252)),
        )
    if name == "risk_parity":
        return RiskParity(
            universe=universe,
            vol_window=int(params.get("vol_window", 63)),
        )
    if name == "top_n_momentum":
        return TopNMomentum(
            universe=universe,
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 126)),
        )
    if name == "ma_crossover":
        return MovingAverageCrossover(
            asset=params.get("asset", "SPY"),
            fast=int(params.get("fast", 50)),
            slow=int(params.get("slow", 200)),
        )
    if name == "leveraged_momentum":
        return LeveragedMomentum(
            universe=tuple(params.get("universe", LEVERAGED_UNIVERSE)),
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 63)),
        )
    if name == "adaptive":
        return AdaptiveAllocator(
            candidates=tuple(
                (n_, dict(p_)) for n_, p_ in
                params.get("candidates", DEFAULT_CANDIDATES)
            ),
            lookback_days=int(params.get("lookback_days", 90)),
        )
    if name == "stable_adaptive":
        return StableAdaptiveAllocator(
            candidates=tuple(
                (n_, dict(p_)) for n_, p_ in
                params.get("candidates", DEFAULT_CANDIDATES)
            ),
            lookback_windows=tuple(params.get("lookback_windows",
                                              (180, 90, 60, 30))),
            switch_margin=float(params.get("switch_margin", 0.30)),
        )
    if name == "vol_scaled_momentum":
        return VolScaledMomentum(
            universe=universe,
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 126)),
            vol_window=int(params.get("vol_window", 63)),
        )
    if name == "skip_month_momentum":
        return SkipMonthMomentum(
            universe=universe,
            n=int(params.get("n", 2)),
            long_lookback=int(params.get("long_lookback", 252)),
            skip_lookback=int(params.get("skip_lookback", 21)),
        )
    if name == "time_series_momentum":
        return TimeSeriesMomentum(
            universe=universe,
            lookback_days=int(params.get("lookback_days", 252)),
        )
    if name == "faber_gtaa":
        return FaberGTAA(
            universe=tuple(params.get("universe", FABER_UNIVERSE)),
            sma_window=int(params.get("sma_window", 200)),
        )
    if name == "all_weather":
        return AllWeather()
    if name == "permanent_portfolio":
        return PermanentPortfolio()
    if name == "mean_reversion":
        return MeanReversion(
            universe=universe,
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 126)),
        )
    if name == "low_vol":
        return LowVol(
            universe=universe,
            n=int(params.get("n", 3)),
            vol_window=int(params.get("vol_window", 63)),
        )
    if name == "vix_gated_momentum":
        return VixGatedMomentum(
            universe=universe,
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 126)),
            vix_gate_low=float(params.get("vix_gate_low", 20.0)),
            vix_gate_high=float(params.get("vix_gate_high", 25.0)),
        )
    if name == "rp_crisis_hedge":
        return RiskParityCrisisHedge(
            universe=universe,
            vol_window=int(params.get("vol_window", 63)),
            hedge_share=float(params.get("hedge_share", 0.15)),
        )
    if name == "trend_carry":
        return TrendCarry(
            universe=universe,
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 252)),
            vol_window=int(params.get("vol_window", 63)),
        )
    if name == "single_stock_momentum":
        return SingleStockMomentum(
            universe=tuple(params.get("universe", CURATED_STOCKS)),
            n=int(params.get("n", 2)),
            lookback_days=int(params.get("lookback_days", 21)),
            skip_lookback=int(params.get("skip_lookback", 0)),
        )
    if name == "concentrated_leveraged":
        return ConcentratedLeveraged(
            universe=tuple(params.get("universe", LEVERAGED_UNIVERSE)),
            lookback_days=int(params.get("lookback_days", 42)),
        )
    if name == "regime_aware":
        return RegimeAwareAllocator()
    if name == "multi":
        # Default blend: 60% momentum + 40% defensive. Override via params.
        allocs = params.get("allocations") or [
            ["top_n_momentum", {"n": 2, "lookback_days": 126}, 0.6],
            ["risk_parity",    {"vol_window": 63},              0.4],
        ]
        norm = tuple((n_, dict(p_), float(w_)) for n_, p_, w_ in allocs)
        return MultiStrategy(allocations=norm)
    raise ValueError(f"unknown strategy: {name!r}")


def list_strategies() -> list[str]:
    return ["sixty_forty", "dual_momentum", "risk_parity",
            "top_n_momentum", "vol_scaled_momentum", "ma_crossover",
            "leveraged_momentum", "adaptive", "stable_adaptive",
            "regime_aware", "multi",
            # 2026-05-24 cycles
            "skip_month_momentum", "time_series_momentum",
            "faber_gtaa", "all_weather", "permanent_portfolio",
            "mean_reversion", "low_vol", "vix_gated_momentum",
            "rp_crisis_hedge", "trend_carry",
            # 2026-05-25 creative aggressive layer
            "single_stock_momentum", "concentrated_leveraged"]


def universe_for(name: str, params: dict | None = None) -> tuple[str, ...]:
    """Symbols a strategy will reference. The morning guide loads prices for
    the union of these so it can compute target weights."""
    params = dict(params or {})
    if name == "sixty_forty":
        return (params.get("equity", "SPY"), params.get("bonds", "AGG"))
    if name == "ma_crossover":
        return (params.get("asset", "SPY"),)
    if name == "leveraged_momentum":
        return tuple(params.get("universe", LEVERAGED_UNIVERSE))
    if name in ("adaptive", "stable_adaptive"):
        # Allocator needs every symbol any candidate might pick.
        cands = params.get("candidates", DEFAULT_CANDIDATES)
        syms: set[str] = set()
        for cand_name, cand_params in cands:
            syms.update(universe_for(cand_name, cand_params))
        return tuple(sorted(syms))
    if name == "regime_aware":
        # Tradeable union of routed strategies + the macro signal tickers.
        from fund.strategy.regime_aware import DEFAULT_ROUTING
        syms: set[str] = set(REGIME_SIGNALS)
        for cand_name, cand_params in DEFAULT_ROUTING.values():
            syms.update(universe_for(cand_name, cand_params))
        return tuple(sorted(syms))
    if name == "multi":
        # Match the default blend resolved by build("multi", {})
        allocs = params.get("allocations") or [
            ["top_n_momentum", {"n": 2, "lookback_days": 126}, 0.6],
            ["risk_parity",    {"vol_window": 63},              0.4],
        ]
        syms: set[str] = set()
        for cand_name, cand_params, _w in allocs:
            if cand_name == "cash":
                continue
            syms.update(universe_for(cand_name, dict(cand_params)))
        return tuple(sorted(syms))
    if name == "faber_gtaa":
        return tuple(params.get("universe", FABER_UNIVERSE))
    if name == "all_weather":
        return ("SPY", "TLT", "AGG", "GLD", "USO")
    if name == "permanent_portfolio":
        return ("SPY", "TLT", "GLD", "BIL")
    if name == "vix_gated_momentum":
        # Needs the tradeable universe plus the VIX signal
        return tuple(sorted(set(params.get("universe", DEFAULT_UNIVERSE))
                            | {"^VIX"}))
    if name == "rp_crisis_hedge":
        return tuple(sorted(set(params.get("universe", DEFAULT_UNIVERSE))
                            | {"TLT"}))
    if name == "single_stock_momentum":
        return tuple(params.get("universe", CURATED_STOCKS))
    if name == "concentrated_leveraged":
        return tuple(params.get("universe", LEVERAGED_UNIVERSE))
    return tuple(params.get("universe", DEFAULT_UNIVERSE))
