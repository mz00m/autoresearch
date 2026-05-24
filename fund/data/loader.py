"""High-level data loading: real -> CSV cache -> synthetic fallback.

``load_panel`` returns (Panel of prices, T-bill PriceSeries). It tries the cache
first, then real fetchers (Stooq for prices, FRED for the short rate), and falls
back to deterministic synthetic data when the network is locked down — so the
research loop always runs. The cache makes real-data runs reproducible.
"""

from __future__ import annotations

import csv
import os
from datetime import date, datetime

from fund.data.pit import Panel, PriceSeries
from fund.data.sources import DataUnavailable, fetch_fred, fetch_stooq
from fund.data.synthetic import synth_panel, synth_tbill

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
TBILL_FRED_SERIES = "DTB3"  # 3-month Treasury bill, secondary market, annual %


def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.csv")


def _save(series: PriceSeries) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(series.symbol), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for d, c in zip(series.dates, series.closes):
            w.writerow([d.isoformat(), c])


def _load_cached(name: str) -> PriceSeries | None:
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    dates, closes = [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            dates.append(datetime.strptime(row["date"], "%Y-%m-%d").date())
            closes.append(float(row["close"]))
    return PriceSeries(name, tuple(dates), tuple(closes))


def _clip(s: PriceSeries, start: date, end: date) -> PriceSeries:
    pairs = [(d, c) for d, c in zip(s.dates, s.closes) if start <= d <= end]
    ds, cs = zip(*pairs) if pairs else ((), ())
    return PriceSeries(s.symbol, tuple(ds), tuple(cs))


def load_panel(symbols: list[str], start: date, end: date, *,
               source: str = "auto", seed: int = 7) -> tuple[Panel, PriceSeries]:
    """source: 'real' (network required), 'synthetic' (offline, deterministic),
    or 'auto' (cache -> real -> synthetic)."""
    if source == "synthetic":
        return (synth_panel(symbols, start, end, seed=seed),
                synth_tbill(start, end, seed=seed))

    series: dict[str, PriceSeries] = {}
    try:
        for sym in symbols:
            cached = _load_cached(sym)
            if cached is None:
                if source == "auto" or source == "real":
                    cached = fetch_stooq(sym)
                    _save(cached)
                else:
                    raise DataUnavailable(f"no cache and source={source}")
            series[sym] = _clip(cached, start, end)
        tbill = _load_cached(TBILL_FRED_SERIES)
        if tbill is None:
            tbill = fetch_fred(TBILL_FRED_SERIES)
            _save(tbill)
        return Panel(series), _clip(tbill, start, end)
    except DataUnavailable as e:
        if source == "real":
            raise
        print(f"[loader] real data unavailable ({e}); falling back to synthetic.")
        return (synth_panel(symbols, start, end, seed=seed),
                synth_tbill(start, end, seed=seed))
