"""Strategy registry — name + params -> strategy object.

Keeps the morning guide and the closeout decoupled from imports; the active
strategy is stored as a string in portfolio_state.json so a human can switch
it without editing Python. Adding a new strategy requires one line here.
"""

from __future__ import annotations

from fund.strategy.adaptive import DEFAULT_CANDIDATES, AdaptiveAllocator
from fund.strategy.dual_momentum import DualMomentum
from fund.strategy.leveraged_momentum import LEVERAGED_UNIVERSE, LeveragedMomentum
from fund.strategy.ma_crossover import MovingAverageCrossover
from fund.strategy.multi import MultiStrategy
from fund.strategy.regime_aware import RegimeAwareAllocator
from fund.strategy.risk_parity import RiskParity
from fund.strategy.sixty_forty import SixtyForty
from fund.strategy.stable_adaptive import StableAdaptiveAllocator
from fund.strategy.top_n_momentum import TopNMomentum

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
            "top_n_momentum", "ma_crossover",
            "leveraged_momentum", "adaptive", "stable_adaptive",
            "regime_aware", "multi"]


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
    return tuple(params.get("universe", DEFAULT_UNIVERSE))
