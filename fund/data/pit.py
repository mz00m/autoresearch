"""Point-in-time data structures + the look-ahead guard.

The cardinal sin of backtesting is look-ahead bias: using data at decision time
that wasn't actually known yet. Here that is structurally prevented: a
``PriceSeries`` exposes ``as_of(date)`` which returns only rows dated <= date.
Strategies are handed an already-sliced view, so they *cannot* peek at the
future even by accident.

Pure stdlib. A series is just a date-indexed float track (works for prices and
for rate series like T-bills alike).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    dates: tuple[date, ...]      # strictly ascending
    closes: tuple[float, ...]    # adjusted close (or rate value), aligned

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.closes):
            raise ValueError(f"{self.symbol}: dates/closes length mismatch")

    def as_of(self, asof: date) -> "PriceSeries":
        """Return the sub-series with dates <= asof. The look-ahead guard."""
        i = bisect.bisect_right(self.dates, asof)
        return PriceSeries(self.symbol, self.dates[:i], self.closes[:i])

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def last(self) -> float | None:
        return self.closes[-1] if self.closes else None

    def trailing_return(self, lookback: int) -> float | None:
        """Return over the last ``lookback`` observations, or None if too short."""
        if len(self.closes) <= lookback or self.closes[-1 - lookback] == 0:
            return None
        return self.closes[-1] / self.closes[-1 - lookback] - 1.0


@dataclass(frozen=True)
class Panel:
    series: dict[str, PriceSeries]

    @property
    def symbols(self) -> list[str]:
        return sorted(self.series)

    def as_of(self, asof: date) -> "Panel":
        return Panel({s: ps.as_of(asof) for s, ps in self.series.items()})

    def common_dates(self) -> list[date]:
        """Dates present for every symbol (intersection), ascending."""
        if not self.series:
            return []
        sets = [set(ps.dates) for ps in self.series.values()]
        return sorted(set.intersection(*sets))

    def trading_dates(self, driver: str = "SPY") -> list[date]:
        """Calendar of trading days driven by one symbol's history.

        Used by the backtester so symbols with shorter histories (e.g. BITO
        only goes back to 2021) don't truncate the whole backtest. Each
        candidate strategy already handles missing-data symbols by excluding
        them at its decision step; this just lets the harness iterate over
        every day the market was open.
        """
        ps = self.series.get(driver)
        if ps is None:
            return self.common_dates()
        return list(ps.dates)
