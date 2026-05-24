"""Real data fetchers — prices (Yahoo + Stooq), macro (FRED), fundamentals (SEC).

All keyless and stdlib-only (urllib). They are wired and ready; in a locked-down
network they raise ``DataUnavailable`` and the loader falls back to synthetic
data. Yahoo Finance's v8 chart JSON is the primary price source (Stooq started
gating CSV downloads behind an API key in 2025); Stooq remains as a fallback
where it works. Run where Yahoo/FRED/SEC are allowlisted to get real data.

Point-in-time note for EDGAR: each XBRL fact carries both a period-end (`end`)
and a *filing* date (`filed`). For honest backtests you may only "know" a
fundamental as of its **filed** date, never its period end. This fetcher returns
both so strategies can respect that.
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.request
from datetime import date, datetime

from fund.data.pit import PriceSeries

# SEC asks for a descriptive UA with contact info. Set FUND_CONTACT_EMAIL (or the
# whole FUND_SEC_USER_AGENT) in your shell so your email stays out of the repo.
_CONTACT = os.environ.get("FUND_CONTACT_EMAIL", "set-your-email@example.com")
USER_AGENT = os.environ.get(
    "FUND_SEC_USER_AGENT",
    f"autoresearch-fund/0.1 (research; contact: {_CONTACT})",
)


class DataUnavailable(Exception):
    pass


def _get(url: str, headers: dict | None = None, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception as e:  # network blocked, host down, etc.
        raise DataUnavailable(f"fetch failed for {url}: {e}") from e


def _iso(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def fetch_yahoo(symbol: str, *, start: date | None = None,
                end: date | None = None, interval: str = "1d") -> PriceSeries:
    """Daily adjusted closes from Yahoo Finance v8 chart API. Keyless.

    Returns adjusted closes (split + dividend adjusted) so total-return is
    captured for ETFs that pay distributions. Yahoo's UA filter rejects empty
    User-Agents, so we send a browser-ish one.

    Always uses explicit period1/period2 unix timestamps — Yahoo's ``range=max``
    silently downsamples to monthly bars on long histories, which would corrupt
    a daily backtest. Default span: 1990-01-01..today.
    """
    sym = symbol.upper()
    start = start or date(1990, 1, 1)
    end = end or date.today()
    p1 = int(datetime(start.year, start.month, start.day).timestamp())
    p2 = int(datetime(end.year, end.month, end.day).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval={interval}"
           f"&events=div%2Csplit")
    text = _get(url, headers={"User-Agent": "Mozilla/5.0 " + USER_AGENT,
                              "Accept": "application/json"})
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise DataUnavailable(f"yahoo bad json for {sym!r}: {e}") from e
    err = (data.get("chart") or {}).get("error")
    if err:
        raise DataUnavailable(f"yahoo error for {sym!r}: {err}")
    result = ((data.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise DataUnavailable(f"yahoo empty result for {sym!r}")
    stamps = result.get("timestamp") or []
    # adjclose preferred; fall back to raw close if missing
    adj_block = ((result.get("indicators") or {}).get("adjclose") or [{}])[0]
    closes_raw = adj_block.get("adjclose")
    if not closes_raw:
        closes_raw = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close")
    if not stamps or not closes_raw:
        raise DataUnavailable(f"yahoo missing price arrays for {sym!r}")
    dates: list[date] = []
    closes: list[float] = []
    for ts, c in zip(stamps, closes_raw):
        if ts is None or c is None:
            continue
        dates.append(datetime.utcfromtimestamp(int(ts)).date())
        closes.append(float(c))
    if not dates:
        raise DataUnavailable(f"yahoo parse empty for {sym!r}")
    # Yahoo can return same date twice across timezone boundaries; dedupe.
    seen = set()
    uniq_d, uniq_c = [], []
    for d, c in zip(dates, closes):
        if d in seen:
            continue
        seen.add(d)
        uniq_d.append(d)
        uniq_c.append(c)
    return PriceSeries(sym, tuple(uniq_d), tuple(uniq_c))


def fetch_stooq(symbol: str) -> PriceSeries:
    """Daily adjusted closes from Stooq. e.g. 'SPY' -> spy.us."""
    s = symbol.lower()
    if "." not in s:
        s = f"{s}.us"
    text = _get(f"https://stooq.com/q/d/l/?s={s}&i=d")
    if "Date,Open" not in text:
        raise DataUnavailable(f"stooq returned no data for {symbol!r}: {text[:60]!r}")
    dates: list[date] = []
    closes: list[float] = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            dates.append(_iso(row["Date"]))
            closes.append(float(row["Close"]))
        except (KeyError, ValueError):
            continue
    if not dates:
        raise DataUnavailable(f"stooq parse empty for {symbol!r}")
    return PriceSeries(symbol.upper(), tuple(dates), tuple(closes))


def fetch_fred(series_id: str) -> PriceSeries:
    """A FRED series as a date-indexed track (e.g. DTB3 = 3-month T-bill, %)."""
    text = _get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    dates: list[date] = []
    vals: list[float] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[0] in ("DATE", "observation_date"):
            continue
        if row[1] in (".", ""):  # FRED missing marker
            continue
        try:
            dates.append(_iso(row[0]))
            vals.append(float(row[1]))
        except ValueError:
            continue
    if not dates:
        raise DataUnavailable(f"fred parse empty for {series_id!r}")
    return PriceSeries(series_id, tuple(dates), tuple(vals))


def fetch_edgar_concept(cik: int | str, tag: str,
                        taxonomy: str = "us-gaap") -> list[dict]:
    """Point-in-time XBRL facts for one concept. Returns dicts with keys
    end, filed, val, form. Use ``filed`` as the knowable-from date."""
    cik10 = str(cik).zfill(10)
    url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
           f"CIK{cik10}/{taxonomy}/{tag}.json")
    text = _get(url, headers={"User-Agent": USER_AGENT})
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise DataUnavailable(f"edgar bad json for CIK{cik10}/{tag}: {e}") from e
    out: list[dict] = []
    for unit_rows in data.get("units", {}).values():
        for r in unit_rows:
            if "filed" in r and "val" in r:
                out.append({"end": r.get("end"), "filed": r["filed"],
                            "val": r["val"], "form": r.get("form")})
    out.sort(key=lambda r: r["filed"])  # ascending by knowable-from date
    return out
