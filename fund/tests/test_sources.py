"""Yahoo Finance / FRED fetchers — URL shape, JSON parsing, edge cases."""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.data import sources


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self._body


def _patch_urlopen(body: bytes):
    """Return a function that monkey-patches urlopen to return `body`."""
    captured: dict = {}

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        return _FakeResponse(body)
    return fake_urlopen, captured


# --- yahoo ------------------------------------------------------------------

def _yahoo_payload(timestamps, adjcloses) -> bytes:
    return json.dumps({
        "chart": {
            "result": [{
                "meta": {"symbol": "SPY", "currency": "USD"},
                "timestamp": timestamps,
                "indicators": {
                    "adjclose": [{"adjclose": adjcloses}],
                },
            }],
            "error": None,
        }
    }).encode()


def test_yahoo_url_uses_explicit_period_bounds():
    fake, captured = _patch_urlopen(_yahoo_payload(
        [int(date(2024, 1, 2).strftime("%s")), int(date(2024, 1, 3).strftime("%s"))],
        [100.0, 101.0]))
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        sources.fetch_yahoo("SPY", start=date(2024, 1, 1), end=date(2024, 1, 5))
    finally:
        urllib.request.urlopen = orig
    assert "period1=" in captured["url"]
    assert "period2=" in captured["url"]
    assert "range=max" not in captured["url"]
    assert "interval=1d" in captured["url"]


def test_yahoo_parses_adjclose_and_dedupes():
    """Same ts twice should be folded to one row."""
    ts1 = int(date(2024, 1, 2).strftime("%s"))
    ts2 = int(date(2024, 1, 3).strftime("%s"))
    body = _yahoo_payload([ts1, ts1, ts2], [100.0, 100.0, 101.0])
    fake, _ = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        ps = sources.fetch_yahoo("SPY")
    finally:
        urllib.request.urlopen = orig
    assert len(ps.dates) == 2
    assert ps.closes == (100.0, 101.0)


def test_yahoo_skips_null_prices():
    ts1 = int(date(2024, 1, 2).strftime("%s"))
    ts2 = int(date(2024, 1, 3).strftime("%s"))
    body = _yahoo_payload([ts1, ts2], [100.0, None])
    fake, _ = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        ps = sources.fetch_yahoo("SPY")
    finally:
        urllib.request.urlopen = orig
    assert len(ps.dates) == 1
    assert ps.closes == (100.0,)


def test_yahoo_raises_on_chart_error():
    body = json.dumps({"chart": {"result": None,
                                  "error": {"code": "NotFound",
                                            "description": "no data"}}}).encode()
    fake, _ = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        sources.fetch_yahoo("ZZZ")
    except sources.DataUnavailable:
        return
    finally:
        urllib.request.urlopen = orig
    raise AssertionError("expected DataUnavailable for chart.error")


def test_yahoo_raises_on_empty_result():
    body = json.dumps({"chart": {"result": [], "error": None}}).encode()
    fake, _ = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        sources.fetch_yahoo("SPY")
    except sources.DataUnavailable:
        return
    finally:
        urllib.request.urlopen = orig
    raise AssertionError("expected DataUnavailable for empty result list")


def test_yahoo_falls_back_to_raw_close_when_adjclose_missing():
    ts = int(date(2024, 1, 2).strftime("%s"))
    body = json.dumps({
        "chart": {
            "result": [{
                "meta": {"symbol": "SPY", "currency": "USD"},
                "timestamp": [ts],
                "indicators": {"quote": [{"close": [100.0]}]},
            }],
            "error": None,
        }
    }).encode()
    fake, _ = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        ps = sources.fetch_yahoo("SPY")
    finally:
        urllib.request.urlopen = orig
    assert ps.closes == (100.0,)


def test_yahoo_sends_browser_user_agent():
    body = _yahoo_payload([int(date(2024, 1, 2).strftime("%s"))], [100.0])
    fake, captured = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        sources.fetch_yahoo("SPY")
    finally:
        urllib.request.urlopen = orig
    # Header key casing varies by urllib; normalize
    ua = next((v for k, v in captured["headers"].items()
               if k.lower() == "user-agent"), "")
    assert "Mozilla" in ua


# --- fred -------------------------------------------------------------------

def test_fred_skips_missing_marker():
    body = b"observation_date,DTB3\n2024-01-02,5.25\n2024-01-03,.\n2024-01-04,5.30\n"
    fake, _ = _patch_urlopen(body)
    orig = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        ps = sources.fetch_fred("DTB3")
    finally:
        urllib.request.urlopen = orig
    assert len(ps.dates) == 2
    assert ps.closes == (5.25, 5.30)


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in globals().items()
             if n.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
