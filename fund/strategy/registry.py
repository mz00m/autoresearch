"""Strategy registry — name + params -> strategy object.

Keeps the morning guide and the closeout decoupled from imports; the active
strategy is stored as a string in portfolio_state.json so a human can switch
it without editing Python. Adding a new strategy requires one line here.
"""

from __future__ import annotations

from fund.strategy.dual_momentum import DualMomentum
from fund.strategy.ma_crossover import MovingAverageCrossover
from fund.strategy.risk_parity import RiskParity
from fund.strategy.sixty_forty import SixtyForty
from fund.strategy.top_n_momentum import TopNMomentum

DEFAULT_UNIVERSE = ("SPY", "EFA", "AGG", "GLD", "QQQ")


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
    raise ValueError(f"unknown strategy: {name!r}")


def list_strategies() -> list[str]:
    return ["sixty_forty", "dual_momentum", "risk_parity",
            "top_n_momentum", "ma_crossover"]


def universe_for(name: str, params: dict | None = None) -> tuple[str, ...]:
    """Symbols a strategy will reference. The morning guide loads prices for
    the union of these so it can compute target weights."""
    params = dict(params or {})
    if name == "sixty_forty":
        return (params.get("equity", "SPY"), params.get("bonds", "AGG"))
    if name == "ma_crossover":
        return (params.get("asset", "SPY"),)
    return tuple(params.get("universe", DEFAULT_UNIVERSE))
