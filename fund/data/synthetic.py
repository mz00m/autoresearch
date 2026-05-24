"""Deterministic synthetic market data, so the full loop runs offline.

Assets share a common market factor (so they're correlated like real ETFs) plus
idiosyncratic drift/vol, which gives momentum strategies something real to chew
on. Fully reproducible given a seed. This is a TEST FIXTURE, not a market model —
a passing backtest here proves the *plumbing*, never an edge.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from fund.data.pit import Panel, PriceSeries

# (annual drift, annual vol, beta to market) per asset — varied so ranks rotate.
_DEFAULT_PROFILE = {
    "SPY": (0.08, 0.16, 1.00),   # US equity
    "EFA": (0.05, 0.18, 0.95),   # intl equity
    "AGG": (0.02, 0.05, 0.10),   # bonds
    "GLD": (0.04, 0.15, 0.20),   # gold
    "QQQ": (0.11, 0.22, 1.20),   # tech
}


def _trading_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def synth_panel(symbols: list[str], start: date, end: date, seed: int = 7) -> Panel:
    days = _trading_days(start, end)
    n = len(days)
    mrng = random.Random(seed)
    # common market factor with a couple of regime shifts (bear patches)
    market = []
    for t in range(n):
        regime = -0.0012 if (n // 3) <= t < (n // 3 + n // 12) else 0.0
        regime += -0.0015 if (2 * n // 3) <= t < (2 * n // 3 + n // 10) else 0.0
        market.append(mrng.gauss(0.0003, 0.010) + regime)

    series: dict[str, PriceSeries] = {}
    for i, sym in enumerate(symbols):
        mu_a, vol_a, beta = _DEFAULT_PROFILE.get(sym, (0.05, 0.18, 0.9))
        srng = random.Random(seed * 1000 + i)
        mu_d = mu_a / 252.0
        vol_d = vol_a / (252 ** 0.5)
        idio_vol = max(1e-4, (vol_d ** 2 - (beta * 0.010) ** 2) ** 0.5)
        closes, p = [], 100.0
        for t in range(n):
            r = mu_d + beta * market[t] + srng.gauss(0.0, idio_vol)
            p *= (1.0 + r)
            closes.append(p)
        series[sym] = PriceSeries(sym, tuple(days), tuple(closes))
    return Panel(series)


def synth_tbill(start: date, end: date, seed: int = 7) -> PriceSeries:
    """A slowly varying short rate (annual %), e.g. 1.5%..5%."""
    days = _trading_days(start, end)
    rng = random.Random(seed + 99)
    rate, out = 2.0, []
    for _ in days:
        rate = min(5.0, max(0.5, rate + rng.gauss(0.0, 0.01)))
        out.append(rate)
    return PriceSeries("TBILL", tuple(days), tuple(out))
