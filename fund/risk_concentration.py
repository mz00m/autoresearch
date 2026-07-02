"""Sector + correlated-exposure caps on top of the worst-case-loss engine.

risk_engine.py enforces the one bounded-liability rule: no order's worst-case
loss may exceed the equity behind it. But "I can't lose more than I deployed"
is silent on *concentration* — a portfolio that's 100% in TQQQ + SOXL + QQQ
is technically bounded-liability and structurally one giant tech bet.

This module adds two complementary checks the risk engine calls in:

  1. **Sector cap** — sum of exposure to any one sector tag (energy, tech,
     bonds, etc.) capped at a max fraction of equity. Default 40%.
  2. **Correlated-exposure cap** — symbols on the same correlation cluster
     (SPY/UPRO; QQQ/TQQQ; XLE/USO; AGG/TLT/TMF) count together. Cap default 60%.

The taxonomy is hand-curated, not learned, because the universe is small and
the clusters are obvious — better than the false precision of a 9-asset
correlation matrix on noisy daily returns. Update SECTOR + CORRELATION_GROUPS
as the universe grows.
"""

from __future__ import annotations

from dataclasses import dataclass

# Asset → sector. One-to-one (a symbol has one home sector). Add new tickers here.
SECTOR: dict[str, str] = {
    # US broad equity
    "SPY": "us_equity", "QQQ": "us_equity", "IWM": "us_equity",
    "UPRO": "us_equity", "TQQQ": "us_equity",
    # International equity
    "EFA": "intl_equity", "EEM": "intl_equity",
    # Bonds
    "AGG": "bonds", "TLT": "bonds", "TMF": "bonds", "BIL": "cash_like",
    # Gold / precious metals
    "GLD": "gold", "UGL": "gold",
    # Energy
    "XLE": "energy", "USO": "energy",
    # Semis (carved out — concentrated tech exposure)
    "SOXL": "semis",
    # Uranium / nuclear
    "URA": "uranium",
    # Crypto
    "BITO": "crypto",
}

# Correlation clusters — symbols inside one cluster count as the same bet for
# concentration purposes. A symbol absent from any cluster is its own cluster.
CORRELATION_GROUPS: list[set[str]] = [
    {"SPY", "QQQ", "UPRO", "TQQQ", "SOXL"},   # US equity, levered tech rides along
    {"AGG", "TLT", "TMF"},                     # US duration
    {"XLE", "USO"},                            # energy / oil complex
    {"GLD", "UGL"},                            # gold
    {"EFA", "EEM"},                            # intl equity (rough)
]


@dataclass(frozen=True)
class ConcentrationLimits:
    # Defaults are deliberately permissive — they're meant to catch egregious
    # accidental concentration (e.g., 95% in one sector from a chain of small
    # adds), not block deliberately-concentrated strategies like dual_momentum
    # (100% single symbol) or sixty_forty (60% in one sector). Tighten these
    # explicitly when running a mandate that requires diversification.
    max_sector_frac: float = 0.85         # any one sector ≤ 85% of equity
    max_cluster_frac: float = 0.90        # any correlation cluster ≤ 90%
    max_single_symbol_frac: float = 1.0   # off by default (ETF universe)


def _sector_of(symbol: str) -> str:
    return SECTOR.get(symbol, "uncategorized")


def _cluster_of(symbol: str) -> frozenset[str]:
    for group in CORRELATION_GROUPS:
        if symbol in group:
            return frozenset(group)
    return frozenset({symbol})


def evaluate(open_book: dict[str, float], proposed: dict[str, float],
             equity: float,
             limits: ConcentrationLimits = ConcentrationLimits()
             ) -> list[str]:
    """Return a list of REJECT reasons (empty list = pass).

    Inputs:
      open_book: {symbol: dollar exposure} already on the book
      proposed:  {symbol: incremental dollar exposure} this order adds
      equity:    account equity for fraction-of-equity math
    """
    reasons: list[str] = []
    if equity <= 0:
        return reasons   # other checks will catch this

    # Combine existing + proposed
    combined: dict[str, float] = dict(open_book)
    for s, v in proposed.items():
        combined[s] = combined.get(s, 0.0) + v

    # 1. Single-symbol cap
    for sym, dollars in combined.items():
        frac = dollars / equity
        if frac > limits.max_single_symbol_frac + 1e-9:
            reasons.append(
                f"REJECT: {sym} would be {frac:.1%} of equity > "
                f"{limits.max_single_symbol_frac:.0%} single-symbol cap"
            )

    # 2. Sector cap
    by_sector: dict[str, float] = {}
    for sym, dollars in combined.items():
        by_sector[_sector_of(sym)] = by_sector.get(_sector_of(sym), 0.0) + dollars
    for sector, dollars in by_sector.items():
        if sector == "cash_like" or sector == "uncategorized":
            continue
        frac = dollars / equity
        if frac > limits.max_sector_frac + 1e-9:
            members = sorted(s for s in combined if _sector_of(s) == sector
                             and combined[s] > 0)
            reasons.append(
                f"REJECT: {sector} sector would be {frac:.1%} of equity > "
                f"{limits.max_sector_frac:.0%} cap (members: {', '.join(members)})"
            )

    # 3. Correlation cluster cap
    by_cluster: dict[frozenset[str], float] = {}
    cluster_members_seen: dict[frozenset[str], set[str]] = {}
    for sym, dollars in combined.items():
        if dollars <= 0:
            continue
        c = _cluster_of(sym)
        by_cluster[c] = by_cluster.get(c, 0.0) + dollars
        cluster_members_seen.setdefault(c, set()).add(sym)
    for cluster, dollars in by_cluster.items():
        if len(cluster) <= 1:
            continue   # single-symbol cluster — already covered by single-symbol cap
        frac = dollars / equity
        if frac > limits.max_cluster_frac + 1e-9:
            members = sorted(cluster_members_seen[cluster])
            reasons.append(
                f"REJECT: correlated-cluster ({', '.join(sorted(cluster))}) "
                f"would be {frac:.1%} of equity > {limits.max_cluster_frac:.0%} "
                f"cap (actually held: {', '.join(members)})"
            )

    return reasons
