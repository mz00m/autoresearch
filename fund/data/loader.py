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
from fund.data.sources import DataUnavailable, fetch_fred, fetch_stooq, fetch_yahoo
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


CACHE_STALE_DAYS = 3  # refetch any cache whose last bar is > N days before `end`


def _is_stale(series: PriceSeries, end: date, stale_days: int) -> bool:
    """A cache is stale if its most recent bar is more than `stale_days` before
    `end` — accounting for weekends/holidays. Used by the daily ops loop so
    yesterday's tickets don't get sized against last month's price."""
    if not series.dates:
        return True
    last = series.dates[-1]
    # Don't trigger refresh just because `end` is a weekend with no new bar yet.
    requested_floor = end
    while requested_floor.weekday() >= 5:  # roll to most recent weekday
        requested_floor = date.fromordinal(requested_floor.toordinal() - 1)
    return (requested_floor - last).days > stale_days


def load_panel(symbols: list[str], start: date, end: date, *,
               source: str = "auto", seed: int = 7,
               stale_days: int = CACHE_STALE_DAYS) -> tuple[Panel, PriceSeries]:
    """source: 'real' (network required), 'synthetic' (offline, deterministic),
    or 'auto' (cache -> real -> synthetic). Cached price files older than
    `stale_days` vs `end` are refetched when source != 'synthetic'."""
    if source == "synthetic":
        return (synth_panel(symbols, start, end, seed=seed),
                synth_tbill(start, end, seed=seed))

    series: dict[str, PriceSeries] = {}
    try:
        for sym in symbols:
            cached = _load_cached(sym)
            if cached is not None and _is_stale(cached, end, stale_days) \
                    and source in ("auto", "real"):
                # Stale cache — fetch fresh and replace
                try:
                    fresh = _fetch_price(sym)
                    _save(fresh)
                    cached = fresh
                except DataUnavailable:
                    pass  # fall back to whatever stale data we had
            if cached is None:
                if source in ("auto", "real"):
                    cached = _fetch_price(sym)
                    _save(cached)
                else:
                    raise DataUnavailable(f"no cache and source={source}")
            series[sym] = _clip(cached, start, end)
        tbill = _load_cached(TBILL_FRED_SERIES)
        if tbill is not None and _is_stale(tbill, end, stale_days) \
                and source in ("auto", "real"):
            try:
                fresh_t = fetch_fred(TBILL_FRED_SERIES)
                _save(fresh_t)
                tbill = fresh_t
            except DataUnavailable:
                pass
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


def _fetch_price(sym: str) -> PriceSeries:
    """Try Yahoo first (keyless JSON), then Stooq. Raise DataUnavailable if both
    fail so the caller can decide whether to fall back to synthetic."""
    errors: list[str] = []
    for name, fetch in (("yahoo", fetch_yahoo), ("stooq", fetch_stooq)):
        try:
            return fetch(sym)
        except DataUnavailable as e:
            errors.append(f"{name}: {e}")
    raise DataUnavailable(f"no price source returned data for {sym!r}: "
                          + " | ".join(errors))
