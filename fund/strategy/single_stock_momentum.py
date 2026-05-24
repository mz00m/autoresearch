"""Single-stock momentum — top-N highest-trending US single stocks.

ETFs smooth the bet across a basket. Single stocks DON'T. NVDA's +200%
year crushed every ETF in 2024; PLTR did 4x in 2024. The same trend
signal applied to individual names produces dramatically higher beta —
and dramatically higher single-name blow-up risk.

Universe is curated to "names with persistent momentum + institutional
liquidity + thesis-attachable narratives" (AI compute, AI software,
defense, fintech). Not a full S&P 500 scan — that would over-index on
random noise.

Long-only, bounded liability holds (you can't lose more than the cash
deployed per name). The 10% trailing stop is the structural floor.

Add to / remove from CURATED_UNIVERSE as your conviction in specific
narratives evolves. Each name should have a current jobsdata/world-
informed thesis before the strategy holds it.
"""

from __future__ import annotations

from dataclasses import dataclass

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH

# Curated single-stock universe — AI compute, AI software, defense,
# fintech. Update as conviction changes. ~$50k market cap minimum,
# all liquid US-listed.
CURATED_STOCKS = (
    # AI compute
    "NVDA", "AVGO", "TSM", "AMD", "ASML",
    # AI software / hyperscalers
    "MSFT", "META", "GOOG", "AMZN", "PLTR",
    # Other high-beta names with real thesis attachment
    "AAPL", "TSLA", "NFLX", "COIN",
)


@dataclass(frozen=True)
class SingleStockMomentum:
    universe: tuple[str, ...] = CURATED_STOCKS
    n: int = 2
    lookback_days: int = 21       # fast turnover, weekly-ish rotation
    skip_lookback: int = 0        # set to 21 for skip-month version

    @property
    def n_params(self) -> int:
        return 3

    @property
    def name(self) -> str:
        return (f"single-stock momentum top-{self.n} "
                f"lb={self.lookback_days}d "
                f"skip={self.skip_lookback}d "
                f"({len(self.universe)} names)")

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        cands: list[tuple[float, str]] = []
        for sym in self.universe:
            ps = panel_asof.series.get(sym)
            if ps is None:
                continue
            r = ps.trailing_return(self.lookback_days)
            if r is None:
                continue
            if self.skip_lookback > 0:
                r_skip = ps.trailing_return(self.skip_lookback)
                if r_skip is None:
                    continue
                score = r - r_skip
            else:
                score = r
            if score <= 0:   # no T-bill gate — equity momentum needs positive return
                continue
            cands.append((score, sym))
        if not cands:
            return {CASH: 1.0}
        cands.sort(reverse=True)
        picks = cands[: max(1, self.n)]
        w = 1.0 / len(picks)
        return {sym: w for _, sym in picks}
